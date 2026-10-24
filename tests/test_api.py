import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PIN = {"X-Staff-Pin": "4321"}


@pytest.fixture()
def client(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), print_dir=str(tmp_path / "prints"), staff_pin="4321", printer="file")
    with TestClient(create_app(s)) as c:
        c.settings = s
        yield c


def order(items=None, **kw):
    body = {"name": "Asha Rao", "phone": "9876543210", "order_type": "Dine in", "table": 2,
            "items": items or [{"id": "b1", "qty": 2}, {"id": "d2", "qty": 3}]}
    body.update(kw)
    return body


def test_menu(client):
    d = client.get("/api/menu").json()
    assert d["shop"]["tables"] == 3
    assert d["categories"][0] == "Starters"
    assert len(d["items"]) == 24 and d["items"][0]["price"] == 370


def test_prices_come_from_server(client):
    # 2 x 340 + 3 x 50 = 830; GST 5% = 41.5 -> 42 (round half up)
    r = client.post("/api/orders", json=order())
    assert r.status_code == 201
    o = r.json()
    assert (o["subtotal"], o["gst"], o["total"]) == (830, 42, 872)
    assert "phone" not in o and o["phone_masked"] == "98XXXXX210"
    assert o["type_label"] == "Dine in, Table 2" and o["token"] == 1


def test_client_cannot_set_price(client):
    body = order(items=[{"id": "b1", "qty": 1, "price": 1}])
    assert client.post("/api/orders", json=body).json()["subtotal"] == 340


def test_tokens_increment_and_duplicates_merge(client):
    client.post("/api/orders", json=order())
    o = client.post("/api/orders", json=order(items=[{"id": "d2", "qty": 1}, {"id": "d2", "qty": 2}])).json()
    assert o["token"] == 2 and o["items"][0]["qty"] == 3


@pytest.mark.parametrize("patch,needle", [
    ({"phone": "12345"}, "10-digit"),
    ({"phone": "5876543210"}, "starting with"),
    ({"name": "A"}, "name"),
    ({"table": None}, "table"),
    ({"table": 9}, "table"),
    ({"items": []}, ""),
    ({"order_type": "Delivery"}, ""),
])
def test_validation(client, patch, needle):
    r = client.post("/api/orders", json=order(**patch))
    assert r.status_code == 422
    assert needle.lower() in r.json()["detail"]["message"].lower()


def test_takeaway_ignores_table(client):
    o = client.post("/api/orders", json=order(order_type="Takeaway", table=2)).json()
    assert o["table"] is None and o["type_label"] == "Takeaway"


def test_unknown_and_unavailable_items(client):
    assert client.post("/api/orders", json=order(items=[{"id": "nope", "qty": 1}])).status_code == 409
    client.patch("/api/menu/b1", json={"available": False}, headers=PIN)
    r = client.post("/api/orders", json=order())
    assert r.status_code == 409 and "Chicken Dum Biryani" in r.json()["detail"]["message"]
    assert client.get("/api/orders", headers=PIN).json()["orders"] == []  # nothing was saved


def test_staff_auth(client):
    assert client.get("/api/orders").status_code == 401
    assert client.get("/api/orders", headers={"X-Staff-Pin": "0000"}).status_code == 401
    assert client.get("/api/orders", headers=PIN).status_code == 200
    assert client.patch("/api/menu/b1", json={"available": False}).status_code == 401


def test_status_flow(client):
    oid = client.post("/api/orders", json=order()).json()["id"]
    assert client.patch(f"/api/orders/{oid}/status", json={"status": "ready"}, headers=PIN).status_code == 409
    for st in ("preparing", "ready", "served"):
        assert client.patch(f"/api/orders/{oid}/status", json={"status": st}, headers=PIN).json()["status"] == st
    assert client.get("/api/orders", headers=PIN).json()["orders"] == []          # served leaves the active list
    assert len(client.get("/api/orders?status=all", headers=PIN).json()["orders"]) == 1
    assert client.get("/api/stats/today", headers=PIN).json()["orders"] == 1


def test_customer_lookup_first_name_only(client):
    assert client.get("/api/customers/lookup?phone=9876543210").json() == {"found": False}
    client.post("/api/orders", json=order())
    client.post("/api/orders", json=order())
    assert client.get("/api/customers/lookup?phone=9876543210").json() == {"found": True, "name": "Asha", "orders": 2}


def test_lookup_rate_limit(client):
    codes = [client.get("/api/customers/lookup?phone=9876543210").status_code for _ in range(12)]
    assert codes.count(429) == 2


def test_slip_is_printed_to_file(client):
    client.post("/api/orders", json=order())
    files = list(__import__("pathlib").Path(client.settings.print_dir).glob("*.txt"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "#1" in text and "Dine in, Table 2" in text and "Rs 872" in text and "98XXXXX210" in text
    assert all(len(line) <= client.settings.cols for line in text.splitlines())
    assert client.get("/api/orders?status=all", headers=PIN).json()["orders"][0]["printed"] is True


def test_reprint(client):
    oid = client.post("/api/orders", json=order()).json()["id"]
    r = client.post(f"/api/orders/{oid}/print", headers=PIN)
    assert r.status_code == 200 and r.json()["printed"] is True
    assert client.post("/api/orders/999/print", headers=PIN).status_code == 404


def test_table_orders_share_one_bill_until_closed(client):
    assert client.get("/api/tables/2/bill").json() == {"bill": None}
    first = client.post("/api/orders", json=order()).json()                                      # 872
    second = client.post("/api/orders", json=order(name="Ravi K", phone="9123456789",
                                                   items=[{"id": "d2", "qty": 1}])).json()       # 50 + 3 = 53
    assert first["bill_id"] == second["bill_id"] is not None
    client.post("/api/orders", json=order(table=3))                                              # another table
    client.post("/api/orders", json=order(order_type="Takeaway"))                                # no bill

    bill = client.get("/api/tables/2/bill").json()["bill"]
    assert [r["token"] for r in bill["rounds"]] == [1, 2]
    assert {i["id"]: (i["qty"], i["line"]) for i in bill["items"]} == {"b1": (2, 680), "d2": (4, 200)}   # rounds combined, item prices shown
    assert "guests" not in bill                                                                  # guests see no names
    assert not {"subtotal", "gst", "gst_percent", "total"} & set(bill)                         # nor the bill total or GST
    assert all("total" not in r for r in bill["rounds"])
    staff_bill = client.get("/api/bills", headers=PIN).json()["bills"][0]                          # staff do see them
    assert (staff_bill["subtotal"], staff_bill["gst"], staff_bill["total"]) == (880, 45, 925)

    staff = client.get("/api/bills", headers=PIN).json()["bills"]
    assert [b["table"] for b in staff] == [2, 3] and staff[0]["guests"] == ["Asha Rao", "Ravi K"]

    assert client.post("/api/tables/2/bill/request").json()["bill"]["status"] == "bill_requested"
    client.post("/api/orders", json=order(items=[{"id": "d2", "qty": 1}]))                     # one more after asking
    bill = client.get("/api/tables/2/bill").json()["bill"]
    assert bill["status"] == "open" and len(bill["rounds"]) == 3

    assert client.post("/api/tables/2/bill/close").status_code == 401                          # guests cannot close
    assert client.post("/api/tables/2/bill/close", headers=PIN).json()["bill"]["status"] == "closed"
    assert client.get("/api/tables/2/bill").json() == {"bill": None}
    assert client.post("/api/orders", json=order()).json()["bill_id"] != first["bill_id"]      # next guests, new bill


def test_cancelled_order_leaves_the_bill(client):
    oid = client.post("/api/orders", json=order()).json()["id"]
    client.post("/api/orders", json=order(items=[{"id": "d2", "qty": 1}]))
    client.patch(f"/api/orders/{oid}/status", json={"status": "cancelled"}, headers=PIN)
    assert len(client.get("/api/tables/2/bill").json()["bill"]["rounds"]) == 1
    assert client.get("/api/bills", headers=PIN).json()["bills"][0]["total"] == 53


def test_bill_errors_and_print(client):
    assert client.get("/api/tables/9/bill").status_code == 404
    assert client.post("/api/tables/1/bill/request").status_code == 404
    assert client.post("/api/tables/1/bill/print", headers=PIN).status_code == 404
    client.post("/api/orders", json=order())
    client.post("/api/orders", json=order(items=[{"id": "b1", "qty": 1}]))
    assert client.post("/api/tables/2/bill/print", headers=PIN).json()["printed"] is True
    slip = next(__import__("pathlib").Path(client.settings.print_dir).glob("*-bill-table-2.txt")).read_text()
    assert "Table 2" in slip and "#1, #2" in slip and " 3x " in slip and "Rs 1,229" in slip
    assert all(len(line) <= client.settings.cols for line in slip.splitlines())


def test_guest_edits_order_until_kitchen_starts(client):
    placed = client.post("/api/orders", json=order()).json()                                     # 2 x b1, 3 x d2
    oid, key = placed["id"], placed["edit_key"]
    assert "edit_key" not in client.get("/api/orders", headers=PIN).json()["orders"][0]          # never shown again

    # Change quantities and add a dish; the slip is reprinted marked UPDATED.
    r = client.put(f"/api/orders/{oid}/items", json={"edit_key": key, "items": [{"id": "b1", "qty": 1}, {"id": "s1", "qty": 1}]})
    assert r.status_code == 200
    o = r.json()
    assert {i["id"]: i["qty"] for i in o["items"]} == {"b1": 1, "s1": 1} and o["subtotal"] == 340 + 370
    assert o["token"] == placed["token"] and o["updated_at"]
    assert any("UPDATED ORDER" in p.read_text() for p in __import__("pathlib").Path(client.settings.print_dir).glob("*-updated-*.txt"))
    assert client.get("/api/bills", headers=PIN).json()["bills"][0]["total"] == o["total"]

    # Wrong key, or someone else's order: not found.
    assert client.put(f"/api/orders/{oid}/items", json={"edit_key": "x" * 20, "items": []}).status_code == 404

    # Once the kitchen starts, the order is locked.
    client.patch(f"/api/orders/{oid}/status", json={"status": "preparing"}, headers=PIN)
    r = client.put(f"/api/orders/{oid}/items", json={"edit_key": key, "items": [{"id": "b1", "qty": 5}]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "kitchen_started"


def test_guest_can_remove_whole_order_and_keeps_old_price(client):
    placed = client.post("/api/orders", json=order()).json()
    client.patch("/api/menu/b1", json={"available": False}, headers=PIN)
    # A dish already on the order may stay even though it sold out since; it cannot be increased.
    keep = client.put(f"/api/orders/{placed['id']}/items", json={"edit_key": placed["edit_key"], "items": [{"id": "b1", "qty": 2}]})
    assert keep.status_code == 200
    more = client.put(f"/api/orders/{placed['id']}/items", json={"edit_key": placed["edit_key"], "items": [{"id": "b1", "qty": 3}]})
    assert more.status_code == 409
    gone = client.put(f"/api/orders/{placed['id']}/items", json={"edit_key": placed["edit_key"], "items": []}).json()
    assert gone["status"] == "cancelled"
    assert client.get("/api/tables/2/bill").json()["bill"]["rounds"] == []


def test_old_database_gets_bill_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, token INTEGER NOT NULL, token_date TEXT NOT NULL, phone TEXT NOT NULL, "
        "name TEXT NOT NULL, order_type TEXT NOT NULL, table_no INTEGER, subtotal INTEGER NOT NULL, gst INTEGER NOT NULL, total INTEGER NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL, printed INTEGER NOT NULL DEFAULT 0, UNIQUE (token_date, token));"
        "PRAGMA user_version = 1;")
    old.close()
    s = Settings(db_path=str(path), print_dir=str(tmp_path / "p"), staff_pin="4321", printer="none")
    with TestClient(create_app(s)) as c:
        assert c.post("/api/orders", json=order()).json()["bill_id"] == 1


def test_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/kitchen").status_code == 200
    home = client.get("/home")
    assert home.status_code == 200 and 'href="/kitchen"' not in home.text and '"/admin"' in home.text
    t = client.get("/tables")
    assert t.status_code == 200 and t.text.count("<svg") == 3 and "/?table=3" in t.text


def test_requires_pin_setting(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(Settings(db_path=str(tmp_path / "x.db"), staff_pin=""))


def test_packaged_items_carry_no_gst(client):
    # 2 x biryani 680 (taxed) + 3 x soft drink 150 (packaged, MRP). GST 5% of 680 = 34.
    o = client.post("/api/orders", json=order(items=[{"id": "b1", "qty": 2}, {"id": "d5", "qty": 3}])).json()
    assert (o["subtotal"], o["gst"], o["total"]) == (830, 34, 864)
    assert {i["id"]: i["no_gst"] for i in o["items"]} == {"b1": False, "d5": True}
    slip = next(__import__("pathlib").Path(client.settings.print_dir).glob("*.txt")).read_text()
    assert "Soft Drink *" in slip and "no GST" in slip and "Rs 864" in slip

    # Editing keeps the rule; a drinks-only order has no GST at all.
    e = client.put(f"/api/orders/{o['id']}/items", json={"edit_key": o["edit_key"], "items": [{"id": "d5", "qty": 2}]}).json()
    assert (e["subtotal"], e["gst"], e["total"]) == (100, 0, 100)
    bill = client.get("/api/bills", headers=PIN).json()["bills"][0]
    assert bill["gst"] == 0 and bill["items"][0]["no_gst"] is True
    assert client.post("/api/tables/2/bill/print", headers=PIN).status_code == 200


def test_menu_marks_packaged_items(client):
    items = {i["id"]: i for i in client.get("/api/menu").json()["items"]}
    assert items["d5"]["no_gst"] is True and items["b1"]["no_gst"] is False
