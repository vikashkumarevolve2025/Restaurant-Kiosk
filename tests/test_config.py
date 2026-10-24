"""Settings file, validation and printing rules. These need no web server."""
import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app import runtime_config as rc
from app.config import Settings
from app.models import SettingsIn, SetupIn
from app.printer import render_slip


def tmp():
    return Path(tempfile.mkdtemp())


def raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


def test_save_and_load_roundtrip():
    d = tmp()
    s = Settings(db_path=str(d / "o.db"), config_file=str(d / "settings.json"), staff_pin="1111", admin_pin="2222", shop_name="Spice Hut", tables=7, gst_percent=12)
    s.save()
    s2 = Settings(db_path=str(d / "o.db"), config_file=str(d / "settings.json"))
    assert s2.load_saved() is True
    assert (s2.shop_name, s2.tables, s2.gst_percent, s2.staff_pin, s2.admin_pin) == ("Spice Hut", 7, 12, "1111", "2222")
    assert s2.configured is True
    assert not list(d.glob("*.tmp"))


def test_load_ignores_wrong_types_and_bad_files():
    d = tmp()
    f = d / "settings.json"
    f.write_text(json.dumps({"tables": "lots", "shop_name": "Okay", "configured": True}))
    s = Settings(config_file=str(f))
    assert s.load_saved() and s.tables == 3 and s.shop_name == "Okay"
    f.write_text("{not json")
    assert Settings(config_file=str(f)).load_saved() is False
    f.write_text("[1, 2]")
    assert Settings(config_file=str(f)).load_saved() is False
    assert Settings(config_file=str(d / "missing.json")).load_saved() is False


def test_first_run_has_locked_temporary_pins():
    d = tmp()
    old = {k: os.environ.get(k) for k in ("CONFIG_FILE", "STAFF_PIN", "ADMIN_PIN")}
    try:
        os.environ["CONFIG_FILE"] = str(d / "settings.json")
        os.environ.pop("STAFF_PIN", None)
        os.environ.pop("ADMIN_PIN", None)
        s = Settings.from_env()
        assert s.configured is False and len(s.staff_pin) >= 12 and len(s.admin_pin) >= 12 and s.staff_pin != s.admin_pin
        s.configured = True
        s.save()
        again = Settings.from_env()
        assert again.configured is True and again.staff_pin == s.staff_pin
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_server_mode_without_config_file_is_configured():
    old = os.environ.pop("CONFIG_FILE", None)
    try:
        s = Settings.from_env()
        assert s.configured is True and s.config_file == ""
    finally:
        if old:
            os.environ["CONFIG_FILE"] = old


def test_apply_settings_rules():
    s = Settings(staff_pin="1111", admin_pin="2222")
    rc.apply_settings(s, {"shop_name": "A Cafe", "tables": 9, "unknown_field": 1})
    assert s.shop_name == "A Cafe" and s.tables == 9 and not hasattr(s, "unknown_field")
    assert raises(ValueError, lambda: rc.apply_settings(s, {"admin_pin": "1111"}))
    assert s.admin_pin == "2222"                       # nothing changed when a rule failed
    assert raises(ValueError, lambda: rc.apply_settings(s, {"staff_pin": "2222", "shop_name": "Changed"}))
    assert s.shop_name == "A Cafe"
    rc.apply_settings(s, {"staff_pin": "3333", "admin_pin": "4444"})
    assert (s.staff_pin, s.admin_pin) == ("3333", "4444")

    alike = Settings(staff_pin="1111", admin_pin="1111")                   # both PINs set the same in .env
    rc.apply_settings(alike, {"shop_name": "Demo Dhaba"})                   # other settings still save
    assert alike.shop_name == "Demo Dhaba"
    assert raises(ValueError, lambda: rc.apply_settings(alike, {"staff_pin": "1111"}))


def test_settings_view_never_contains_pins():
    s = Settings(staff_pin="1111", admin_pin="2222", config_file="x.json", lan_url="http://192.168.1.20:8000")
    v = rc.settings_view(s)
    assert "staff_pin" not in v and "admin_pin" not in v and "1111" not in json.dumps(v) and "2222" not in json.dumps(v)
    assert v["guest_url"] == "http://192.168.1.20:8000" and v["editable"] is True and v["separate_admin_pin"] is True
    s.public_url = "https://order.example.com"
    assert rc.settings_view(s)["guest_url"] == "https://order.example.com"


def test_validation_of_owner_input():
    ok = SettingsIn(shop_name="  Spice   Hut ", gstin="29abcde1234f1z5", usb_vendor="4B8", public_url="http://192.168.1.20:8000/", printer="windows", cols=32)
    d = ok.model_dump(exclude_none=True)
    assert d["shop_name"] == "Spice Hut" and d["gstin"] == "29ABCDE1234F1Z5" and d["usb_vendor"] == "0x04b8"
    assert d["public_url"] == "http://192.168.1.20:8000" and d["printer"] == "windows" and d["cols"] == 32
    assert SettingsIn(gstin="", public_url="", printer_host="").model_dump(exclude_none=True) == {"gstin": "", "public_url": "", "printer_host": ""}
    for bad in ({"shop_name": "X"}, {"gstin": "123"}, {"gst_percent": 99}, {"tables": 0}, {"tables": 500}, {"printer": "laser"}, {"cols": 40},
                {"public_url": "ftp://x"}, {"public_url": "http://a b"}, {"printer_host": "a b;rm"}, {"staff_pin": "12"}, {"admin_pin": "pin with space"},
                {"usb_vendor": "zz"}, {"printer_port": 70000}):
        assert raises(ValidationError, lambda bad=bad: SettingsIn(**bad)), bad


def test_setup_requires_the_essentials():
    assert raises(ValidationError, lambda: SetupIn(shop_name="Spice Hut"))
    assert raises(ValidationError, lambda: SetupIn(staff_pin="1234", admin_pin="5678"))
    s = SetupIn(shop_name="Spice Hut", staff_pin="1234", admin_pin="5678")
    assert s.sample_menu is True
    assert "sample_menu" not in s.model_dump(exclude={"sample_menu"}, exclude_none=True)


def test_slip_skips_empty_address_and_gstin():
    order = {"token": 5, "type_label": "Takeaway", "created_label": "24 Oct 2026, 01:00 PM", "name": "Asha Rao", "phone_masked": "98XXXXX210",
             "items": [{"qty": 1, "name": "Tea", "line": 20}], "subtotal": 20, "gst": 1, "gst_percent": 5, "total": 21}
    text = render_slip(order, Settings(shop_name="Tea Stall"))
    assert "GSTIN" not in text and "Tea Stall" in text and "Rs 21" in text
    text2 = render_slip(order, Settings(shop_name="Tea Stall", shop_addr="1 Main Rd", gstin="29ABCDE1234F1Z5"))
    assert "GSTIN 29ABCDE1234F1Z5" in text2 and "1 Main Rd" in text2
