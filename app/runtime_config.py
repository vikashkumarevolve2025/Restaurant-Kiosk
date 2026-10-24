"""On-screen settings: apply, show, and the guest address."""
from __future__ import annotations

from . import __version__
from .config import SAVED_FIELDS, Settings


def apply_settings(s: Settings, data: dict) -> None:
    """Apply already-validated changes. Raises ValueError for rules that span several fields."""
    changes = {k: v for k, v in data.items() if k in SAVED_FIELDS}
    staff = changes.get("staff_pin", s.staff_pin)
    admin = changes.get("admin_pin", s.admin_pin)
    # Checked only when a PIN is being changed, so a shop that set both PINs alike in .env can still save its name.
    if ("staff_pin" in changes or "admin_pin" in changes) and staff and admin and staff == admin:
        raise ValueError("The owner PIN and the kitchen PIN must be different.")
    for k, v in changes.items():
        setattr(s, k, v)


def guest_url(s: Settings) -> str:
    """The address guests' phones should open: the public address if set, else the shop network address."""
    return s.public_url or s.lan_url


def settings_view(s: Settings) -> dict:
    """What the admin screen shows. PINs are never included."""
    return {
        "shop_name": s.shop_name, "shop_addr": s.shop_addr, "gstin": s.gstin, "gst_percent": s.gst_percent,
        "tables": s.tables, "printer": s.printer, "printer_name": s.printer_name, "printer_host": s.printer_host,
        "printer_port": s.printer_port, "usb_vendor": s.usb_vendor, "usb_product": s.usb_product, "cols": s.cols,
        "public_url": s.public_url, "lan_url": s.lan_url, "guest_url": guest_url(s), "timezone": s.tz,
        "editable": bool(s.config_file), "separate_admin_pin": bool(s.admin_pin and s.admin_pin != s.staff_pin),
        "version": __version__,
    }
