"""SQLite access. One short-lived connection per request."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from .menu_data import CATEGORIES, ITEMS, PACKAGED

SCHEMA = """
CREATE TABLE IF NOT EXISTS menu_items (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price       INTEGER NOT NULL CHECK (price >= 0),
    veg         INTEGER NOT NULL DEFAULT 0,
    spice       INTEGER NOT NULL DEFAULT 0,
    hue         INTEGER NOT NULL DEFAULT 20,
    available   INTEGER NOT NULL DEFAULT 1,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customers (
    phone       TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    order_count INTEGER NOT NULL DEFAULT 0,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       INTEGER NOT NULL,
    token_date  TEXT NOT NULL,
    phone       TEXT NOT NULL REFERENCES customers(phone),
    name        TEXT NOT NULL,
    order_type  TEXT NOT NULL CHECK (order_type IN ('Dine in', 'Takeaway')),
    table_no    INTEGER,
    subtotal    INTEGER NOT NULL,
    gst         INTEGER NOT NULL,
    total       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'preparing', 'ready', 'served', 'cancelled')),
    created_at  TEXT NOT NULL,
    printed     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (token_date, token)
);
CREATE INDEX IF NOT EXISTS idx_orders_date_status ON orders (token_date, status);
CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders (phone);

CREATE TABLE IF NOT EXISTS order_items (
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    item_id  TEXT NOT NULL,
    name     TEXT NOT NULL,
    price    INTEGER NOT NULL,
    qty      INTEGER NOT NULL CHECK (qty > 0)
);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items (order_id);

-- A running bill for one table: every dine-in order at that table joins it until staff close it.
CREATE TABLE IF NOT EXISTS table_bills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    table_no    INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'bill_requested', 'closed')),
    opened_at   TEXT NOT NULL,
    closed_at   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bills_one_open ON table_bills (table_no) WHERE status != 'closed';
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            conn.execute("PRAGMA user_version = 1")
        # v2: orders belong to a table bill. Older databases get the column added in place.
        if "bill_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}:
            conn.execute("ALTER TABLE orders ADD COLUMN bill_id INTEGER REFERENCES table_bills(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_bill ON orders (bill_id)")
        # v3: the guest who placed an order can edit it until the kitchen starts (edit_key), and edits are stamped.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}
        if "edit_key" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN edit_key TEXT")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN updated_at TEXT")
        if conn.execute("PRAGMA user_version").fetchone()[0] < 3:
            conn.execute("PRAGMA user_version = 3")
        # v4: a dish can have a photo (file in the images folder) and a credit line for its photographer.
        mcols = {r["name"] for r in conn.execute("PRAGMA table_info(menu_items)")}
        if "image" not in mcols:
            conn.execute("ALTER TABLE menu_items ADD COLUMN image TEXT")
        if "image_credit" not in mcols:
            conn.execute("ALTER TABLE menu_items ADD COLUMN image_credit TEXT")
        if conn.execute("PRAGMA user_version").fetchone()[0] < 4:
            conn.execute("PRAGMA user_version = 4")
        # v5: packaged items sold at MRP carry no GST on the bill (menu flag, copied onto each order line),
        # and a small key/value table for shop-wide things such as the UPI payment QR.
        if "no_gst" not in {r["name"] for r in conn.execute("PRAGMA table_info(menu_items)")}:
            conn.execute("ALTER TABLE menu_items ADD COLUMN no_gst INTEGER NOT NULL DEFAULT 0")
        if "no_gst" not in {r["name"] for r in conn.execute("PRAGMA table_info(order_items)")}:
            conn.execute("ALTER TABLE order_items ADD COLUMN no_gst INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if conn.execute("PRAGMA user_version").fetchone()[0] < 5:
            conn.execute("PRAGMA user_version = 5")
        # v6: who placed an order (guest or waiter) and who last changed it, shown on the kitchen screen.
        ocols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}
        if "source" not in ocols:
            conn.execute("ALTER TABLE orders ADD COLUMN source TEXT NOT NULL DEFAULT 'guest'")
        if "updated_by" not in ocols:
            conn.execute("ALTER TABLE orders ADD COLUMN updated_by TEXT")
        if conn.execute("PRAGMA user_version").fetchone()[0] < 6:
            conn.execute("PRAGMA user_version = 6")
        # v7: how a table paid when staff closed it (UPI, cash or card) and the amount they checked.
        bcols = {r["name"] for r in conn.execute("PRAGMA table_info(table_bills)")}
        if "paid_method" not in bcols:
            conn.execute("ALTER TABLE table_bills ADD COLUMN paid_method TEXT")
        if "paid_amount" not in bcols:
            conn.execute("ALTER TABLE table_bills ADD COLUMN paid_amount INTEGER")
        if conn.execute("PRAGMA user_version").fetchone()[0] < 7:
            conn.execute("PRAGMA user_version = 7")
        if conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0] == 0:
            order = {c: i for i, c in enumerate(CATEGORIES)}
            rows = [
                (i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], order[i[1]] * 1000 + n)
                for n, i in enumerate(ITEMS)
            ]
            conn.executemany(
                "INSERT INTO menu_items (id, category, name, description, price, veg, spice, hue, available, sort) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.executemany("UPDATE menu_items SET no_gst = 1 WHERE id = ?", [(i,) for i in PACKAGED])
            _seed_sample_photos(conn, Path(path).parent / "images")
    finally:
        conn.close()


SAMPLE_PHOTOS = Path(__file__).resolve().parent.parent / "static" / "sample-photos"


def _seed_sample_photos(conn: sqlite3.Connection, images: Path) -> None:
    """A new sample menu starts with the bundled photos; the owner can replace them in admin."""
    try:
        credits = json.loads((SAMPLE_PHOTOS / "credits.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    images.mkdir(parents=True, exist_ok=True)
    for item_id, credit in credits.items():
        src = SAMPLE_PHOTOS / f"{item_id}.jpg"
        if not src.is_file():
            continue
        name = f"{item_id}-sample.jpg"
        shutil.copyfile(src, images / name)
        conn.execute("UPDATE menu_items SET image = ?, image_credit = ? WHERE id = ?", (name, credit, item_id))
