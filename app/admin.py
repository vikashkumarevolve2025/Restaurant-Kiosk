"""Owner-only operations: menu editing, reports, order search, customers, CSV."""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import Settings
from .models import MenuItemIn, MenuItemPatch
from .orders import OrderError, _row_to_order, now

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- menu ----------
def _item(conn: sqlite3.Connection, item_id: str) -> dict:
    r = conn.execute("SELECT * FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not r:
        raise OrderError(404, "not_found", "Item not found.")
    return {"id": r["id"], "category": r["category"], "name": r["name"], "description": r["description"],
            "price": r["price"], "veg": bool(r["veg"]), "spice": r["spice"], "hue": r["hue"],
            "available": bool(r["available"]), "no_gst": bool(r["no_gst"]),
            "image": image_url(r["image"]), "image_credit": r["image_credit"] or ""}


# ---------- dish photos ----------
# The browser shrinks photos before upload; the server only checks what arrived and stores it.
IMAGE_TYPES = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}\.(jpg|png|webp)$")


def images_dir(settings: Settings) -> Path:
    return Path(settings.db_path).parent / "images"


def image_url(name: str | None) -> str | None:
    return f"/images/{name}" if name else None


def _image_kind(data: bytes) -> str | None:
    for magic, ext in IMAGE_TYPES.items():
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _decode_image(data_url: str) -> tuple[bytes, str]:
    """A data URL from the admin screen -> image bytes and extension. Anything that is not a real photo is refused."""
    m = re.fullmatch(r"data:image/(?:jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)", data_url.strip())
    try:
        data = base64.b64decode(m.group(1), validate=False) if m else b""
    except (binascii.Error, ValueError):
        data = b""
    ext = _image_kind(data)
    if not ext:
        raise OrderError(422, "bad_image", "That file is not a JPEG, PNG or WebP photo.")
    if len(data) > MAX_IMAGE_BYTES:
        raise OrderError(422, "too_big", "That photo is too large. Use one under 2 MB.")
    return data, ext


# ---------- UPI payment QR (shown on the kiosk slip) ----------
UPI_ID_RE = re.compile(r"^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9.]{1,63}$")


def _setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def _put_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    if value:
        conn.execute("INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    else:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))


def payment_info(conn: sqlite3.Connection) -> dict:
    return {"qr": image_url(_setting(conn, "payment_qr")), "upi_id": _setting(conn, "upi_id")}


def set_payment(conn: sqlite3.Connection, settings: Settings, data_url: str | None, upi_id: str | None) -> dict:
    """Save the shop's UPI QR (a photo of it, or the image from the bank app) and/or its UPI ID."""
    if upi_id is not None:
        upi_id = upi_id.strip()
        if upi_id and not UPI_ID_RE.match(upi_id):
            raise OrderError(422, "bad_upi", "A UPI ID looks like shopname@okaxis.")
        _put_setting(conn, "upi_id", upi_id)
    if data_url:
        data, ext = _decode_image(data_url)
        folder = images_dir(settings)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"payqr-{hashlib.sha256(data).hexdigest()[:10]}.{ext}"
        (folder / name).write_bytes(data)
        old = _setting(conn, "payment_qr")
        _put_setting(conn, "payment_qr", name)
        _drop_image_file(settings, old, keep=name)
    return payment_info(conn)


def remove_payment_qr(conn: sqlite3.Connection, settings: Settings) -> dict:
    old = _setting(conn, "payment_qr")
    _put_setting(conn, "payment_qr", "")
    _drop_image_file(settings, old)
    return payment_info(conn)


def set_image(conn: sqlite3.Connection, settings: Settings, item_id: str, data_url: str, credit: str = "") -> dict:
    old = conn.execute("SELECT image FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not old:
        raise OrderError(404, "not_found", "Item not found.")
    data, ext = _decode_image(data_url)
    folder = images_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", item_id)[:24] or "dish"
    name = f"{safe_id}-{hashlib.sha256(data).hexdigest()[:10]}.{ext}"
    (folder / name).write_bytes(data)
    conn.execute("UPDATE menu_items SET image = ?, image_credit = ? WHERE id = ?", (name, credit.strip()[:300], item_id))
    _drop_image_file(settings, old["image"], keep=name)
    return _item(conn, item_id)


def remove_image(conn: sqlite3.Connection, settings: Settings, item_id: str) -> dict:
    old = conn.execute("SELECT image FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not old:
        raise OrderError(404, "not_found", "Item not found.")
    conn.execute("UPDATE menu_items SET image = NULL, image_credit = NULL WHERE id = ?", (item_id,))
    _drop_image_file(settings, old["image"])
    return _item(conn, item_id)


def _drop_image_file(settings: Settings, name: str | None, keep: str | None = None) -> None:
    if name and name != keep and IMAGE_NAME_RE.match(name):
        try:
            (images_dir(settings) / name).unlink()
        except OSError:
            pass


def _sort_for_category(conn: sqlite3.Connection, category: str) -> int:
    row = conn.execute("SELECT MAX(sort) FROM menu_items WHERE category = ?", (category,)).fetchone()[0]
    if row is not None:
        return row + 1
    top = conn.execute("SELECT MAX(sort) FROM menu_items").fetchone()[0]
    return 0 if top is None else (top // 1000 + 1) * 1000


def _new_id(conn: sqlite3.Connection) -> str:
    best = 0
    for (i,) in conn.execute("SELECT id FROM menu_items"):
        m = re.fullmatch(r"m(\d+)", i)
        if m:
            best = max(best, int(m.group(1)))
    return f"m{best + 1}"


def _default_hue(name: str) -> int:
    return sum(ord(c) for c in name) % 360


def create_item(conn: sqlite3.Connection, d: MenuItemIn) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        dup = conn.execute("SELECT 1 FROM menu_items WHERE lower(name) = lower(?) AND category = ?", (d.name, d.category)).fetchone()
        if dup:
            raise OrderError(409, "duplicate", f"{d.name} is already in {d.category}.")
        iid = _new_id(conn)
        conn.execute(
            "INSERT INTO menu_items (id, category, name, description, price, veg, spice, hue, available, sort, no_gst) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (iid, d.category, d.name, d.description, d.price, int(d.veg), d.spice,
             d.hue if d.hue is not None else _default_hue(d.name), int(d.available), _sort_for_category(conn, d.category), int(d.no_gst)),
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return _item(conn, iid)


def update_item(conn: sqlite3.Connection, item_id: str, p: MenuItemPatch) -> dict:
    cur = _item(conn, item_id)
    changes = p.model_dump(exclude_none=True)
    if not changes:
        return cur
    conn.execute("BEGIN IMMEDIATE")
    try:
        new_name = changes.get("name", cur["name"])
        new_cat = changes.get("category", cur["category"])
        dup = conn.execute(
            "SELECT 1 FROM menu_items WHERE lower(name) = lower(?) AND category = ? AND id != ?", (new_name, new_cat, item_id)
        ).fetchone()
        if dup:
            raise OrderError(409, "duplicate", f"{new_name} is already in {new_cat}.")
        sets, vals = [], []
        for k, v in changes.items():
            sets.append(f"{k} = ?")
            vals.append(int(v) if isinstance(v, bool) else v)
        if new_cat != cur["category"]:
            sets.append("sort = ?")
            vals.append(_sort_for_category(conn, new_cat))
        conn.execute(f"UPDATE menu_items SET {', '.join(sets)} WHERE id = ?", (*vals, item_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return _item(conn, item_id)


def delete_item(conn: sqlite3.Connection, item_id: str, settings: Settings | None = None) -> None:
    _item(conn, item_id)
    image = conn.execute("SELECT image FROM menu_items WHERE id = ?", (item_id,)).fetchone()["image"]
    # Past orders keep their own copy of name and price, so history is unaffected.
    conn.execute("DELETE FROM menu_items WHERE id = ?", (item_id,))
    if settings is not None:
        _drop_image_file(settings, image)


def move_item(conn: sqlite3.Connection, item_id: str, direction: str) -> None:
    cur = conn.execute("SELECT category, sort FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not cur:
        raise OrderError(404, "not_found", "Item not found.")
    op, order = ("<", "DESC") if direction == "up" else (">", "ASC")
    other = conn.execute(
        f"SELECT id, sort FROM menu_items WHERE category = ? AND sort {op} ? ORDER BY sort {order} LIMIT 1",
        (cur["category"], cur["sort"]),
    ).fetchone()
    if not other:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE menu_items SET sort = ? WHERE id = ?", (other["sort"], item_id))
        conn.execute("UPDATE menu_items SET sort = ? WHERE id = ?", (cur["sort"], other["id"]))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# ---------- reports ----------
def parse_range(settings: Settings, start: str | None, end: str | None) -> tuple[str, str]:
    today = now(settings).date()
    try:
        e = date.fromisoformat(end) if end else today
        s = date.fromisoformat(start) if start else e - timedelta(days=6)
    except ValueError:
        raise OrderError(422, "bad_date", "Dates must look like 2026-10-23.")
    if s > e:
        raise OrderError(422, "bad_range", "The start date is after the end date.")
    if (e - s).days > 366:
        raise OrderError(422, "bad_range", "Choose a range of one year or less.")
    return s.isoformat(), e.isoformat()


def sales_report(conn: sqlite3.Connection, settings: Settings, start: str | None, end: str | None) -> dict:
    s, e = parse_range(settings, start, end)
    live = "token_date BETWEEN ? AND ? AND status != 'cancelled'"
    t = conn.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(subtotal),0) sub, COALESCE(SUM(gst),0) gst, COALESCE(SUM(total),0) total FROM orders WHERE {live}",
        (s, e),
    ).fetchone()
    cancelled = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE token_date BETWEEN ? AND ? AND status = 'cancelled'", (s, e)
    ).fetchone()[0]
    per_day = {r["d"]: (r["n"], r["total"]) for r in conn.execute(
        f"SELECT token_date d, COUNT(*) n, SUM(total) total FROM orders WHERE {live} GROUP BY token_date", (s, e))}
    days, d = [], date.fromisoformat(s)
    while d <= date.fromisoformat(e):
        n, total = per_day.get(d.isoformat(), (0, 0))
        days.append({"date": d.isoformat(), "orders": n, "sales": total})
        d += timedelta(days=1)
    top = [dict(r) for r in conn.execute(
        "SELECT oi.name AS name, SUM(oi.qty) AS qty, SUM(oi.qty * oi.price) AS sales "
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.token_date BETWEEN ? AND ? AND o.status != 'cancelled' "
        "GROUP BY oi.item_id, oi.name ORDER BY qty DESC, sales DESC LIMIT 10", (s, e))]
    by_type = [dict(r) for r in conn.execute(
        f"SELECT order_type AS label, COUNT(*) AS orders, SUM(total) AS sales FROM orders WHERE {live} GROUP BY order_type ORDER BY sales DESC", (s, e))]
    by_table = [dict(r) for r in conn.execute(
        f"SELECT 'Table ' || table_no AS label, COUNT(*) AS orders, SUM(total) AS sales FROM orders WHERE {live} AND table_no IS NOT NULL GROUP BY table_no ORDER BY table_no", (s, e))]
    repeat = conn.execute(
        f"SELECT COUNT(DISTINCT phone) FROM orders WHERE {live} AND phone NOT IN ('walkin', 'deleted')", (s, e)).fetchone()[0]
    return {
        "start": s, "end": e,
        "orders": t["n"], "subtotal": t["sub"], "gst": t["gst"], "sales": t["total"],
        "average": round(t["total"] / t["n"]) if t["n"] else 0,
        "cancelled": cancelled, "guests": repeat,
        "days": days, "top_items": top, "by_type": by_type, "by_table": by_table,
    }


# ---------- orders and customers ----------
def search_orders(conn: sqlite3.Connection, settings: Settings, start: str | None, end: str | None,
                  phone: str | None, status: str | None, limit: int) -> list[dict]:
    s, e = parse_range(settings, start, end)
    q, args = "SELECT * FROM orders WHERE token_date BETWEEN ? AND ?", [s, e]
    digits = re.sub(r"\D", "", phone or "")
    if digits:
        q += " AND phone LIKE ?"
        args.append(digits + "%")
    if status:
        q += " AND status = ?"
        args.append(status)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return [_row_to_order(conn, r, settings) for r in conn.execute(q, args).fetchall()]


def _safe_cell(v) -> str:
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def orders_csv(orders: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "time", "token", "name", "phone", "type", "table", "status", "items", "subtotal", "gst", "total"])
    for o in reversed(orders):
        created = datetime.fromisoformat(o["created_at"])
        items = "; ".join(f"{i['qty']}x {i['name']}" for i in o["items"])
        w.writerow([_safe_cell(x) for x in (created.date().isoformat(), created.strftime("%H:%M"), o["token"], o["name"], o["phone"],
                                            o["order_type"], o["table"], o["status"], items, o["subtotal"], o["gst"], o["total"])])
    return buf.getvalue()


def list_customers(conn: sqlite3.Connection, q: str | None, limit: int) -> list[dict]:
    sql = ("SELECT c.phone, c.name, c.order_count, c.first_seen, c.last_seen, "
           "COALESCE(SUM(CASE WHEN o.status != 'cancelled' THEN o.total END), 0) AS spend "
           "FROM customers c LEFT JOIN orders o ON o.phone = c.phone WHERE c.phone NOT IN ('deleted', 'walkin')")
    args: list = []
    if q and q.strip():
        like = "%" + q.strip().replace("%", "").replace("_", "") + "%"
        sql += " AND (c.name LIKE ? OR c.phone LIKE ?)"
        args += [like, like]
    sql += " GROUP BY c.phone ORDER BY c.last_seen DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def forget_customer(conn: sqlite3.Connection, phone: str) -> int:
    """Remove a guest's name and number. Their past orders stay, anonymised, so sales totals still add up."""
    if not conn.execute("SELECT 1 FROM customers WHERE phone = ?", (phone,)).fetchone():
        raise OrderError(404, "not_found", "No guest with that number.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT OR IGNORE INTO customers (phone, name, order_count, first_seen, last_seen) VALUES ('deleted','Deleted guest',0,'','')")
        n = conn.execute("UPDATE orders SET phone = 'deleted', name = 'Deleted guest' WHERE phone = ?", (phone,)).rowcount
        conn.execute("DELETE FROM customers WHERE phone = ?", (phone,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return n


def sample_order(settings: Settings) -> dict:
    t = now(settings)
    return {
        "id": 0, "token": 0, "name": "Test Print", "phone": "9000000000", "phone_masked": "90XXXXX000",
        "order_type": "Dine in", "table": 1, "type_label": "TEST PRINT",
        "items": [{"id": "x", "name": "Chicken Dum Biryani", "price": 340, "qty": 2, "line": 680},
                  {"id": "y", "name": "Butter Naan", "price": 50, "qty": 3, "line": 150}],
        "subtotal": 830, "gst": 42, "gst_percent": settings.gst_percent, "total": 872,
        "status": "new", "printed": False, "created_at": t.isoformat(timespec="seconds"),
        "created_label": t.strftime("%d %b %Y, %I:%M %p"),
    }
