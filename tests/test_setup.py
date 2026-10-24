"""First-run setup and on-screen settings (installed-app mode)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SHOP = ("127.0.0.1", 50000)      # the shop computer itself
GUEST = ("192.168.1.77", 50000)  # a phone on the shop Wi-Fi

BODY = {"shop_name": "Spice Hut", "shop_addr": "1 Main Rd", "gstin": "29ABCDE1234F1Z5", "gst_percent": 5, "tables": 5,
        "printer": "file", "staff_pin": "1234", "admin_pin": "5678", "sample_menu": True}


@pytest.fixture()
def paths(tmp_path):
    return {"db_path": str(tmp_path / "o.db"), "print_dir": str(tmp_path / "p"), "config_file": str(tmp_path / "settings.json")}


def fresh(paths):
    s = Settings(**paths, staff_pin="temp-staff-xxxxxx", admin_pin="temp-admin-xxxxxx", configured=False, lan_url="http://192.168.1.20:8000")
    return s, create_app(s)


def test_state_and_guest_cannot_finish_setup(paths):
    s, app = fresh(paths)
    with TestClient(app, client=GUEST) as c:
        st = c.get("/api/setup/state").json()
        assert st == {"configured": False, "local": False, "guest_url": "http://192.168.1.20:8000", "can_save": True}
        r = c.post("/api/setup", json=BODY)
        assert r.status_code == 403
    assert s.configured is False and s.shop_name != "Spice Hut"


def test_setup_from_shop_computer(paths):
    s, app = fresh(paths)
    with TestClient(app, client=SHOP) as c:
        assert c.get("/api/setup/state").json()["local"] is True
        assert c.post("/api/setup", json={**BODY, "admin_pin": "1234"}).status_code == 422       # same PIN twice
        assert c.post("/api/setup", json={**BODY, "staff_pin": "12"}).status_code == 422          # too short
        assert c.post("/api/setup", json={k: v for k, v in BODY.items() if k != "staff_pin"}).status_code == 422
        r = c.post("/api/setup", json=BODY)
        assert r.status_code == 201 and r.json()["guest_url"] == "http://192.168.1.20:8000"
        assert c.post("/api/setup", json=BODY).status_code == 409                                  # only once
        saved = json.load(open(paths["config_file"]))
        assert saved["configured"] is True and saved["shop_name"] == "Spice Hut" and saved["tables"] == 5
        # the new PINs work, the temporary ones do not
        assert c.get("/api/admin/settings", headers={"X-Staff-Pin": "5678"}).status_code == 200
        assert c.get("/api/admin/settings", headers={"X-Staff-Pin": "temp-admin-xxxxxx"}).status_code == 401
        assert c.get("/api/orders", headers={"X-Staff-Pin": "1234"}).status_code == 200
        assert c.get("/api/admin/settings", headers={"X-Staff-Pin": "1234"}).status_code == 401   # kitchen PIN is not the owner PIN
        menu = c.get("/api/menu").json()
        assert menu["shop"]["name"] == "Spice Hut" and menu["shop"]["tables"] == 5 and len(menu["items"]) == 24


def test_setup_without_sample_menu(paths):
    _, app = fresh(paths)
    with TestClient(app, client=SHOP) as c:
        assert c.post("/api/setup", json={**BODY, "sample_menu": False}).status_code == 201
        assert c.get("/api/menu").json()["items"] == []


def test_staff_screens_locked_before_setup(paths):
    _, app = fresh(paths)
    with TestClient(app, client=SHOP) as c:
        assert c.get("/api/orders", headers={"X-Staff-Pin": ""}).status_code == 401
        assert c.get("/api/admin/settings", headers={"X-Staff-Pin": "1234"}).status_code == 401


def test_owner_edits_settings_and_pins(paths):
    s, app = fresh(paths)
    with TestClient(app, client=SHOP) as c:
        c.post("/api/setup", json=BODY)
        H = {"X-Staff-Pin": "5678"}
        v = c.get("/api/admin/settings", headers=H).json()
        assert v["editable"] is True and v["tables"] == 5 and "staff_pin" not in v
        r = c.put("/api/admin/settings", json={"tables": 8, "gst_percent": 18, "printer": "windows", "printer_name": "POS-80"}, headers=H)
        assert r.status_code == 200 and r.json()["tables"] == 8
        assert c.get("/api/menu").json()["shop"] == {"name": "Spice Hut", "tables": 8, "gst_percent": 18}
        assert c.put("/api/admin/settings", json={"tables": 0}, headers=H).status_code == 422
        assert c.put("/api/admin/settings", json={"admin_pin": "1234"}, headers=H).status_code == 422
        assert c.put("/api/admin/settings", json={"admin_pin": "9999"}, headers=H).status_code == 200
        assert c.get("/api/admin/settings", headers=H).status_code == 401                          # old owner PIN stopped working
        assert c.get("/api/admin/settings", headers={"X-Staff-Pin": "9999"}).status_code == 200
        assert json.load(open(paths["config_file"]))["admin_pin"] == "9999"
        assert c.get("/api/admin/printers", headers={"X-Staff-Pin": "9999"}).json() == {"printers": []}   # not Windows here


def test_settings_are_read_only_in_server_mode(tmp_path):
    s = Settings(db_path=str(tmp_path / "o.db"), print_dir=str(tmp_path / "p"), staff_pin="1234", admin_pin="5678")
    with TestClient(create_app(s), client=SHOP) as c:
        assert c.get("/api/admin/settings", headers={"X-Staff-Pin": "5678"}).json()["editable"] is False
        r = c.put("/api/admin/settings", json={"tables": 4}, headers={"X-Staff-Pin": "5678"})
        assert r.status_code == 409 and ".env" in r.json()["detail"]["message"]
        assert c.post("/api/setup", json=BODY).status_code == 409


def test_tables_page_uses_shop_network_address(paths):
    s, app = fresh(paths)
    with TestClient(app, client=SHOP) as c:
        c.post("/api/setup", json=BODY)
        page = c.get("/tables").text
        assert page.count("<svg") == 5 and "http://192.168.1.20:8000/?table=5" in page and "shop Wi-Fi" in page
        c.put("/api/admin/settings", json={"public_url": "https://order.example.com"}, headers={"X-Staff-Pin": "5678"})
        page = c.get("/tables").text
        assert "https://order.example.com/?table=1" in page and "shop Wi-Fi" not in page


def test_setup_page_is_served(paths):
    _, app = fresh(paths)
    with TestClient(app, client=SHOP) as c:
        assert c.get("/setup").status_code == 200
