import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

KITCHEN = {"X-Staff-Pin": "4321"}
OWNER = {"X-Staff-Pin": "9999"}


@pytest.fixture()
def client(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), print_dir=str(tmp_path / "prints"), staff_pin="4321", admin_pin="9999", printer="file")
    with TestClient(create_app(s)) as c:
        yield c


def place(client, name="Asha", phone="9876543210", items=None):
    r = client.post("/api/orders", json={"name": name, "phone": phone, "order_type": "Dine in", "table": 1,
                                         "items": items or [{"id": "b1", "qty": 2}]})
    assert r.status_code == 201, r.text
    return r.json()


def test_kitchen_pin_cannot_use_admin(client):
    assert client.get("/api/admin/settings").status_code == 401
    assert client.get("/api/admin/settings", headers=KITCHEN).status_code == 401
    assert client.get("/api/admin/settings", headers=OWNER).status_code == 200
    assert client.post("/api/admin/menu", json={"name": "Tea", "category": "Drinks", "price": 20}, headers=KITCHEN).status_code == 401


def test_owner_pin_also_works_for_kitchen_endpoints(client):
    assert client.get("/api/orders", headers=OWNER).status_code == 200


def test_polling_with_correct_pin_is_never_rate_limited(client):
    assert all(client.get("/api/orders", headers=KITCHEN).status_code == 200 for _ in range(60))


def test_wrong_pins_are_rate_limited_then_blocked_even_for_right_pin(client):
    codes = [client.get("/api/orders", headers={"X-Staff-Pin": "nope"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert client.get("/api/orders", headers=KITCHEN).status_code == 429


def test_menu_crud_and_order_of_categories(client):
    r = client.post("/api/admin/menu", json={"name": "Filter Coffee", "category": "Hot Drinks", "price": 40, "veg": True}, headers=OWNER)
    assert r.status_code == 201 and r.json()["id"] == "m1"
    menu = client.get("/api/menu").json()
    assert menu["categories"][-1] == "Hot Drinks"
    assert client.patch("/api/admin/menu/m1", json={"price": 45}, headers=OWNER).json()["price"] == 45
    assert client.post("/api/admin/menu", json={"name": "filter coffee", "category": "Hot Drinks", "price": 1}, headers=OWNER).status_code == 409
    assert client.post("/api/admin/menu", json={"name": "X", "category": "Hot Drinks", "price": 1}, headers=OWNER).status_code == 422
    assert client.post("/api/admin/menu/m1/move", json={"direction": "up"}, headers=OWNER).status_code == 200
    assert client.delete("/api/admin/menu/m1", headers=OWNER).status_code == 200
    assert client.delete("/api/admin/menu/m1", headers=OWNER).status_code == 404


def test_new_price_applies_to_new_orders_only(client):
    first = place(client)
    client.patch("/api/admin/menu/b1", json={"price": 400}, headers=OWNER)
    second = place(client)
    assert first["subtotal"] == 680 and second["subtotal"] == 800


def test_report_orders_csv_customers_forget(client):
    a = place(client)
    place(client, name='=cmd|" /c calc"', phone="9123456780")
    rep = client.get("/api/admin/report", headers=OWNER).json()
    assert rep["orders"] == 2 and rep["sales"] == a["total"] * 2 and len(rep["days"]) == 7
    assert client.get("/api/admin/report?start=2026-10-10&end=2026-10-01", headers=OWNER).status_code == 422
    csv_text = client.get("/api/admin/orders.csv", headers=OWNER)
    assert csv_text.status_code == 200 and csv_text.headers["content-type"].startswith("text/csv")
    assert "'=cmd" in csv_text.text and ",=cmd" not in csv_text.text
    assert len(client.get("/api/admin/orders?phone=9876", headers=OWNER).json()["orders"]) == 1
    assert len(client.get("/api/admin/customers", headers=OWNER).json()["customers"]) == 2
    assert client.delete("/api/admin/customers/9876543210", headers=OWNER).json() == {"orders_anonymised": 1}
    assert client.delete("/api/admin/customers/9876543210", headers=OWNER).status_code == 404
    assert client.delete("/api/admin/customers/abc", headers=OWNER).status_code == 422
    assert client.get("/api/admin/report", headers=OWNER).json()["sales"] == rep["sales"]


def test_print_test_and_page(client):
    assert client.post("/api/admin/print-test", headers=OWNER).json()["printed"] is True
    assert client.get("/admin").status_code == 200


def test_settings_view_shape(client):
    v = client.get("/api/admin/settings", headers=OWNER).json()
    assert v["editable"] is False and v["tables"] == 3 and "staff_pin" not in v and "admin_pin" not in v


# A 1x1 PNG and JPEG are enough to exercise the checks; the browser does the real resizing.
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
JPEG = "data:image/jpeg;base64," + __import__("base64").b64encode(b"\xff\xd8\xff\xe0" + b"0" * 64).decode()


def test_dish_photo_upload_replace_remove(client):
    assert client.put("/api/admin/menu/b1/image", json={"data": PNG}, headers=KITCHEN).status_code == 401   # owner only
    r = client.put("/api/admin/menu/b1/image", json={"data": PNG, "credit": "Photo: A. Cook, CC BY 4.0"}, headers=OWNER)
    assert r.status_code == 200
    first = r.json()["image"]
    assert first.startswith("/images/b1-") and first.endswith(".png")
    menu = {i["id"]: i for i in client.get("/api/menu").json()["items"]}
    assert menu["b1"]["image"] == first and menu["b1"]["image_credit"] == "Photo: A. Cook, CC BY 4.0"
    got = client.get(first)
    assert got.status_code == 200 and got.content.startswith(b"\x89PNG") and "immutable" in got.headers["cache-control"]
    assert "A. Cook" in client.get("/credits").text

    second = client.put("/api/admin/menu/b1/image", json={"data": JPEG}, headers=OWNER).json()["image"]
    assert second.endswith(".jpg") and client.get(first).status_code == 404                              # old file removed
    assert client.delete("/api/admin/menu/b1/image", headers=OWNER).json()["image"] is None
    assert client.get(second).status_code == 404


@pytest.mark.parametrize("data", [
    "data:image/png;base64,SGVsbG8gd29ybGQgdGhpcyBpcyBub3QgYW4gaW1hZ2U=",        # text pretending to be a PNG
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "not a data url at all, just some text",
])
def test_dish_photo_rejects_non_images(client, data):
    assert client.put("/api/admin/menu/b1/image", json={"data": data}, headers=OWNER).status_code == 422


def test_image_route_only_serves_photo_names(client):
    assert client.get("/images/..%2Ft.db").status_code == 404
    assert client.get("/images/t.db").status_code == 404
    assert client.put("/api/admin/menu/nope/image", json={"data": PNG}, headers=OWNER).status_code == 404


def test_fresh_sample_menu_comes_with_photos(client):
    items = {i["id"]: i for i in client.get("/api/menu").json()["items"]}
    assert items["b1"]["image"] == "/images/b1-sample.jpg" and "Wikimedia Commons" in items["b1"]["image_credit"]
    assert client.get("/images/b1-sample.jpg").content.startswith(b"\xff\xd8\xff")
    assert sum(1 for i in items.values() if i["image"]) == 24


def test_owner_marks_item_no_gst(client):
    new = client.post("/api/admin/menu", json={"name": "Packaged Water", "category": "Sides & Drinks", "price": 20, "no_gst": True}, headers=OWNER).json()
    assert new["no_gst"] is True
    assert client.patch(f"/api/admin/menu/{new['id']}", json={"no_gst": False}, headers=OWNER).json()["no_gst"] is False


def test_upi_payment_qr(client):
    assert client.get("/api/payment").json() == {"qr": None, "upi_id": ""}
    assert client.put("/api/admin/payment", json={"qr": PNG}, headers=KITCHEN).status_code == 401          # owner only
    p = client.put("/api/admin/payment", json={"qr": PNG, "upi_id": "karamkitchen@okaxis"}, headers=OWNER).json()
    assert p["qr"].startswith("/images/payqr-") and p["upi_id"] == "karamkitchen@okaxis"
    assert client.get("/api/payment").json() == p and client.get(p["qr"]).status_code == 200
    assert client.put("/api/admin/payment", json={"upi_id": "not an id"}, headers=OWNER).status_code == 422
    assert client.put("/api/admin/payment", json={"qr": "data:text/html;base64,PGgxPg=="}, headers=OWNER).status_code == 422
    # Changing only the UPI ID keeps the QR; removing the QR deletes its file and keeps the ID.
    assert client.put("/api/admin/payment", json={"upi_id": "shop@ybl"}, headers=OWNER).json()["qr"] == p["qr"]
    gone = client.delete("/api/admin/payment/qr", headers=OWNER).json()
    assert gone == {"qr": None, "upi_id": "shop@ybl"} and client.get(p["qr"]).status_code == 404
