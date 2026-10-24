"""Settings.

Server mode: read from environment variables (see .env.example).
Installed app: the same defaults plus a settings file the owner edits on screen (CONFIG_FILE).
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# The settings the owner can change on screen. In the installed app they are saved to CONFIG_FILE.
SAVED_FIELDS = (
    "shop_name", "shop_addr", "gstin", "gst_percent", "tables",
    "printer", "printer_name", "printer_host", "printer_port", "usb_vendor", "usb_product", "cols",
    "public_url", "staff_pin", "admin_pin",
)


def _resolve(p: str) -> str:
    path = Path(p)
    return str(path if path.is_absolute() else BASE_DIR / path)


@dataclass
class Settings:
    db_path: str = "data/orders.db"
    staff_pin: str = ""
    admin_pin: str = ""           # owner PIN for /admin; falls back to STAFF_PIN when empty
    shop_name: str = "My Restaurant"
    shop_addr: str = ""
    gstin: str = ""
    gst_percent: int = 5
    tables: int = 3
    tz: str = "Asia/Kolkata"
    public_url: str = ""          # e.g. https://order.example.com  (used inside table QR codes)
    trust_proxy: bool = False     # true only when behind your own reverse proxy / tunnel
    printer: str = "file"         # none | file | network | usb | windows
    printer_name: str = ""        # windows: printer name; empty means the default printer
    printer_host: str = ""
    printer_port: int = 9100
    usb_vendor: str = ""          # hex, e.g. 0x04b8
    usb_product: str = ""         # hex, e.g. 0x0e15
    print_dir: str = "prints"
    cols: int = 42                # 42 for 80 mm paper, 32 for 58 mm
    config_file: str = ""         # installed app: where on-screen settings are saved
    configured: bool = True       # False until the owner finishes first-run setup
    lan_url: str = ""             # runtime only: this computer's address on the shop network

    def __post_init__(self) -> None:
        self.db_path = _resolve(self.db_path)
        self.print_dir = _resolve(self.print_dir)

    # ---- saved settings file ----
    def save(self) -> None:
        if not self.config_file:
            raise RuntimeError("No settings file is configured.")
        data = {k: getattr(self, k) for k in SAVED_FIELDS}
        data["configured"] = self.configured
        path = Path(self.config_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def load_saved(self) -> bool:
        path = Path(self.config_file)
        if not path.is_file():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        for k in SAVED_FIELDS:
            if k in data and isinstance(data[k], type(getattr(self, k))):
                setattr(self, k, data[k])
        self.configured = bool(data.get("configured", True))
        return True

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        d = cls()
        s = cls(
            db_path=e("DB_PATH", "data/orders.db"),
            staff_pin=e("STAFF_PIN", ""),
            admin_pin=e("ADMIN_PIN", ""),
            shop_name=e("SHOP_NAME", d.shop_name),
            shop_addr=e("SHOP_ADDRESS", d.shop_addr),
            gstin=e("SHOP_GSTIN", d.gstin),
            gst_percent=int(e("GST_PERCENT", d.gst_percent)),
            tables=int(e("TABLE_COUNT", d.tables)),
            tz=e("TIMEZONE", d.tz),
            public_url=e("PUBLIC_URL", "").rstrip("/"),
            trust_proxy=e("TRUST_PROXY", "0") == "1",
            printer=e("PRINTER", d.printer).lower(),
            printer_name=e("PRINTER_NAME", ""),
            printer_host=e("PRINTER_HOST", ""),
            printer_port=int(e("PRINTER_PORT", d.printer_port)),
            usb_vendor=e("PRINTER_USB_VENDOR", ""),
            usb_product=e("PRINTER_USB_PRODUCT", ""),
            print_dir=e("PRINT_DIR", "prints"),
            cols=int(e("PRINTER_COLS", d.cols)),
        )
        cfg = e("CONFIG_FILE", "")
        if cfg:
            s.config_file = _resolve(cfg)
            if not s.load_saved():
                # First run: nobody knows these temporary PINs, so staff screens stay locked until setup is done.
                s.configured = False
                s.staff_pin = s.staff_pin or secrets.token_urlsafe(12)
                s.admin_pin = s.admin_pin or secrets.token_urlsafe(12)
        return s
