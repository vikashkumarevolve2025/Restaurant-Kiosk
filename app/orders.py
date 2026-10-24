"""Order logic: pricing, tokens, status changes. All money is whole rupees."""
from __future__ import annotations

import hmac
import secrets
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .models import OrderIn

ACTIVE = ("new", "preparing", "ready")
TRANSITIONS = {
    "new": {"preparing", "cancelled"},
    "preparing": {"ready", "cancelled"},
    "ready": {"served", "cancelled"},
    "served": set(),
    "cancelled": set(),
}


class OrderError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def now(settings: Settings) -> datetime:
    return datetime.now(ZoneInfo(settings.tz))


def gst_amount(subtotal: int, percent: int) -> int:
    return (subtotal * percent + 50) // 100  # round half up, integers only


def taxable(lines) -> int:
    """The part of a subtotal GST is charged on: (price, qty, no_gst) lines, leaving out packaged MRP items."""
    return sum(price * qty for price, qty, no_gst in lines if not no_gst)


# Orders a waiter takes without the guest's number use this placeholder (like "deleted" for forgotten guests).
WALKIN = "walkin"


def mask_phone(phone: str) -> str:
    if not phone.isdigit():
        return "not given"
    return phone[:2] + "XXXXX" + phone[7:]


def type_label(order_type: str, table_no: int | None) -> str:
    return f"Dine in, Table {table_no}" if order_type == "Dine in" and table_no else order_type


def _row_to_order(conn: sqlite3.Connection, row: sqlite3.Row, settings: Settings) -> dict:
    items = conn.execute(
        "SELECT item_id, name, price, qty, no_gst FROM order_items WHERE order_id = ? ORDER BY rowid", (row["id"],)
    ).fetchall()
    created = datetime.fromisoformat(row["created_at"])
    return {
        "id": row["id"],
        "token": row["token"],
        "name": row["name"],
        "phone": row["phone"],
        "phone_masked": mask_phone(row["phone"]),
        "order_type": row["order_type"],
        "table": row["table_no"],
        "bill_id": row["bill_id"],
        "type_label": type_label(row["order_type"], row["table_no"]),
        "items": [
            {"id": i["item_id"], "name": i["name"], "price": i["price"], "qty": i["qty"], "line": i["price"] * i["qty"],
             "no_gst": bool(i["no_gst"])}
            for i in items
        ],
        "subtotal": row["subtotal"],
        "gst": row["gst"],
        "gst_percent": settings.gst_percent,
        "total": row["total"],
        "status": row["status"],
        "printed": bool(row["printed"]),
        "created_at": row["created_at"],
        "created_label": created.strftime("%d %b %Y, %I:%M %p"),
        "updated_at": row["updated_at"],
        "source": row["source"],
        "updated_by": row["updated_by"],
    }


def public_view(order: dict) -> dict:
    """What a guest gets back: no full phone number."""
    return {k: v for k, v in order.items() if k != "phone"}


def get_order(conn: sqlite3.Connection, settings: Settings, order_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return _row_to_order(conn, row, settings) if row else None


def _merge_qty(items) -> dict[str, int]:
    qty_by_id: dict[str, int] = {}
    for it in items:
        qty_by_id[it.id] = qty_by_id.get(it.id, 0) + it.qty
    if any(q > 20 for q in qty_by_id.values()):
        raise OrderError(422, "bad_qty", "You can order at most 20 of one item.")
    return qty_by_id


def _menu_rows(conn: sqlite3.Connection, qty_by_id: dict[str, int], keep: dict[str, int] | None = None) -> dict:
    """Current menu rows for the ordered items. Items already on the order (keep) may stay even if sold out since."""
    ids = list(qty_by_id)
    rows = conn.execute(f"SELECT * FROM menu_items WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    by_id = {r["id"]: r for r in rows}
    if len(by_id) != len(ids):
        raise OrderError(409, "unknown_item", "An item on your order is no longer on the menu.")
    keep = keep or {}
    gone = [by_id[i]["name"] for i in ids if not by_id[i]["available"] and qty_by_id[i] > keep.get(i, 0)]
    if gone:
        raise OrderError(409, "unavailable", "Sorry, " + ", ".join(gone) + " is not available right now. It has been removed from your order.")
    return by_id


def create_order(conn: sqlite3.Connection, settings: Settings, data: OrderIn, source: str = "guest") -> dict:
    if data.order_type == "Dine in":
        if data.table is None or not (1 <= data.table <= settings.tables):
            raise OrderError(422, "bad_table", "Choose your table.")
        table_no: int | None = data.table
    else:
        table_no = None

    qty_by_id = _merge_qty(data.items)
    t = now(settings)
    ts, today = t.isoformat(timespec="seconds"), t.date().isoformat()
    edit_key = secrets.token_urlsafe(18)

    conn.execute("BEGIN IMMEDIATE")
    try:
        by_id = _menu_rows(conn, qty_by_id)
        subtotal = sum(by_id[i]["price"] * q for i, q in qty_by_id.items())
        gst = gst_amount(taxable(((by_id[i]["price"], q, by_id[i]["no_gst"]) for i, q in qty_by_id.items())), settings.gst_percent)
        token = conn.execute(
            "SELECT COALESCE(MAX(token), 0) + 1 FROM orders WHERE token_date = ?", (today,)
        ).fetchone()[0]

        # Dine-in orders join the table's running bill, opening one if the table has none.
        bill_id = None
        if table_no is not None:
            bill = _open_bill_row(conn, table_no)
            if bill is None:
                bill_id = conn.execute(
                    "INSERT INTO table_bills (table_no, status, opened_at) VALUES (?, 'open', ?)", (table_no, ts)
                ).lastrowid
            else:
                bill_id = bill["id"]
                if bill["status"] == "bill_requested":   # they ordered more after asking for the bill
                    conn.execute("UPDATE table_bills SET status = 'open' WHERE id = ?", (bill_id,))

        if data.phone == WALKIN:
            conn.execute("INSERT OR IGNORE INTO customers (phone, name, order_count, first_seen, last_seen) "
                         "VALUES (?, 'Walk-in guest', 0, '', '')", (WALKIN,))
        else:
            conn.execute(
                "INSERT INTO customers (phone, name, order_count, first_seen, last_seen) VALUES (?,?,1,?,?) "
                "ON CONFLICT(phone) DO UPDATE SET name = excluded.name, order_count = order_count + 1, last_seen = excluded.last_seen",
                (data.phone, data.name, ts, ts),
            )
        cur = conn.execute(
            "INSERT INTO orders (token, token_date, phone, name, order_type, table_no, subtotal, gst, total, status, created_at, bill_id, edit_key, source) "
            "VALUES (?,?,?,?,?,?,?,?,?, 'new', ?, ?, ?, ?)",
            (token, today, data.phone, data.name, data.order_type, table_no, subtotal, gst, subtotal + gst, ts, bill_id, edit_key, source),
        )
        oid = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_items (order_id, item_id, name, price, qty, no_gst) VALUES (?,?,?,?,?,?)",
            [(oid, i, by_id[i]["name"], by_id[i]["price"], q, by_id[i]["no_gst"]) for i, q in qty_by_id.items()],
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    order = get_order(conn, settings, oid)
    order["edit_key"] = edit_key  # type: ignore[index]  # handed only to the guest who placed it
    return order  # type: ignore[return-value]


def edit_order(conn: sqlite3.Connection, settings: Settings, order_id: int, edit_key: str | None, items, by: str = "guest") -> dict:
    """Change an order's dishes; an empty list cancels it.
    A guest (with the order's edit key) may do this only until the kitchen starts. A waiter (by="waiter", no key)
    may change any order not yet served, for example when the guest wants more before paying."""
    qty_by_id = _merge_qty(items)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if by == "waiter":
            if not row:
                raise OrderError(404, "not_found", "Order not found.")
            if row["status"] not in ACTIVE:
                raise OrderError(409, "closed_order", f"This order is already {row['status']}, so it cannot be changed.")
        else:
            if not row or not row["edit_key"] or not edit_key or not hmac.compare_digest(row["edit_key"], edit_key):
                raise OrderError(404, "not_found", "Order not found.")
            if row["status"] != "new":
                raise OrderError(409, "kitchen_started", "The kitchen has already started on this order, so it cannot be changed now. Anything you add goes on a new order.")
        ts = now(settings).isoformat(timespec="seconds")
        if not qty_by_id:
            conn.execute("UPDATE orders SET status = 'cancelled', updated_at = ?, updated_by = ? WHERE id = ?", (ts, by, order_id))
        else:
            current = {r["item_id"]: (r["qty"], r["price"], r["name"], r["no_gst"]) for r in conn.execute(
                "SELECT item_id, qty, price, name, no_gst FROM order_items WHERE order_id = ?", (order_id,))}
            by_id = _menu_rows(conn, qty_by_id, keep={k: v[0] for k, v in current.items()})
            # Dishes already on the order keep the price (and GST rule) they were ordered at; new dishes take today's.
            lines = []
            for i, q in qty_by_id.items():
                if i in current:
                    lines.append((i, current[i][2], current[i][1], q, current[i][3]))
                else:
                    lines.append((i, by_id[i]["name"], by_id[i]["price"], q, by_id[i]["no_gst"]))
            subtotal = sum(price * q for _, _, price, q, _ in lines)
            gst = gst_amount(taxable((price, q, ng) for _, _, price, q, ng in lines), settings.gst_percent)
            conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
            conn.executemany("INSERT INTO order_items (order_id, item_id, name, price, qty, no_gst) VALUES (?,?,?,?,?,?)",
                             [(order_id, *line) for line in lines])
            conn.execute("UPDATE orders SET subtotal = ?, gst = ?, total = ?, updated_at = ?, updated_by = ?, printed = 0 WHERE id = ?",
                         (subtotal, gst, subtotal + gst, ts, by, order_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return get_order(conn, settings, order_id)  # type: ignore[return-value]


def list_orders(conn: sqlite3.Connection, settings: Settings, status: str, date: str | None) -> list[dict]:
    date = date or now(settings).date().isoformat()
    if status == "active":
        q = f"SELECT * FROM orders WHERE token_date = ? AND status IN ({','.join('?' * len(ACTIVE))}) ORDER BY id"
        rows = conn.execute(q, (date, *ACTIVE)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders WHERE token_date = ? ORDER BY id DESC LIMIT 300", (date,)).fetchall()
    return [_row_to_order(conn, r, settings) for r in rows]


def set_status(conn: sqlite3.Connection, settings: Settings, order_id: int, new: str) -> dict:
    row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        raise OrderError(404, "not_found", "Order not found.")
    if new not in TRANSITIONS[row["status"]]:
        raise OrderError(409, "bad_transition", f"Cannot move an order from {row['status']} to {new}.")
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (new, order_id))
    return get_order(conn, settings, order_id)  # type: ignore[return-value]


# ---------- table bills ----------
def _open_bill_row(conn: sqlite3.Connection, table_no: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM table_bills WHERE table_no = ? AND status != 'closed'", (table_no,)).fetchone()


def _bill_view(conn: sqlite3.Connection, settings: Settings, bill: sqlite3.Row) -> dict:
    rows = conn.execute(
        "SELECT * FROM orders WHERE bill_id = ? AND status != 'cancelled' ORDER BY id", (bill["id"],)
    ).fetchall()
    orders = [_row_to_order(conn, r, settings) for r in rows]
    # One line per dish and price across all rounds, as on a restaurant bill.
    combined: dict[tuple, dict] = {}
    for o in orders:
        for i in o["items"]:
            line = combined.setdefault((i["id"], i["price"]), {"id": i["id"], "name": i["name"], "price": i["price"], "qty": 0, "line": 0,
                                                               "no_gst": i["no_gst"]})
            line["qty"] += i["qty"]
            line["line"] += i["line"]
    return {
        "id": bill["id"],
        "table": bill["table_no"],
        "status": bill["status"],
        "opened_at": bill["opened_at"],
        "rounds": [
            {"id": o["id"], "token": o["token"], "status": o["status"], "created_label": o["created_label"], "items": o["items"], "total": o["total"],
             "name": o["name"], "source": o["source"], "updated_by": o["updated_by"]}
            for o in orders
        ],
        "items": list(combined.values()),
        "subtotal": sum(o["subtotal"] for o in orders),
        "gst": sum(o["gst"] for o in orders),
        "gst_percent": settings.gst_percent,
        "total": sum(o["total"] for o in orders),
        "guests": sorted({o["name"] for o in orders}),
    }


def public_bill(bill: dict) -> dict:
    """What anyone at the table may see: the dishes and their prices. No names, and no totals or GST:
    the bill amount is given by staff when the guests pay."""
    hidden = {"guests", "subtotal", "gst", "gst_percent", "total"}
    view = {k: v for k, v in bill.items() if k not in hidden}
    view["rounds"] = [{k: v for k, v in r.items() if k not in ("total", "name")} for r in bill["rounds"]]
    return view


def _check_table(settings: Settings, table_no: int) -> None:
    if not 1 <= table_no <= settings.tables:
        raise OrderError(404, "bad_table", "There is no such table.")


def table_bill(conn: sqlite3.Connection, settings: Settings, table_no: int) -> dict | None:
    _check_table(settings, table_no)
    row = _open_bill_row(conn, table_no)
    return _bill_view(conn, settings, row) if row else None


def open_bills(conn: sqlite3.Connection, settings: Settings) -> list[dict]:
    rows = conn.execute("SELECT * FROM table_bills WHERE status != 'closed' ORDER BY table_no").fetchall()
    return [_bill_view(conn, settings, r) for r in rows]


def request_bill(conn: sqlite3.Connection, settings: Settings, table_no: int) -> dict:
    _check_table(settings, table_no)
    row = _open_bill_row(conn, table_no)
    if not row:
        raise OrderError(404, "no_bill", "This table has no open bill.")
    conn.execute("UPDATE table_bills SET status = 'bill_requested' WHERE id = ?", (row["id"],))
    return table_bill(conn, settings, table_no)  # type: ignore[return-value]


def close_bill(conn: sqlite3.Connection, settings: Settings, table_no: int) -> dict:
    _check_table(settings, table_no)
    row = _open_bill_row(conn, table_no)
    if not row:
        raise OrderError(404, "no_bill", "This table has no open bill.")
    bill = _bill_view(conn, settings, row)
    conn.execute("UPDATE table_bills SET status = 'closed', closed_at = ? WHERE id = ?",
                 (now(settings).isoformat(timespec="seconds"), row["id"]))
    bill["status"] = "closed"
    return bill


def mark_printed(conn: sqlite3.Connection, order_id: int) -> None:
    conn.execute("UPDATE orders SET printed = 1 WHERE id = ?", (order_id,))


def today_stats(conn: sqlite3.Connection, settings: Settings) -> dict:
    today = now(settings).date().isoformat()
    by_status = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM orders WHERE token_date = ? GROUP BY status", (today,))}
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS revenue FROM orders WHERE token_date = ? AND status != 'cancelled'",
        (today,),
    ).fetchone()
    return {"date": today, "orders": row["n"], "revenue": row["revenue"], "by_status": by_status}


def lookup_customer(conn: sqlite3.Connection, phone: str) -> dict:
    row = conn.execute("SELECT name, order_count FROM customers WHERE phone = ?", (phone,)).fetchone()
    if not row:
        return {"found": False}
    # First name only: this endpoint is open to guests, so it reveals as little as possible.
    return {"found": True, "name": row["name"].split(" ")[0], "orders": row["order_count"]}
