"""OrderDesk launcher: the program the installer's shortcut starts.

It keeps the shop's data in one folder, finds this computer's address on the shop network (for the
table QR codes), makes a daily backup, starts the server and opens the browser.

Options:  --no-browser   start quietly (used when Windows starts)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

PRODUCT = "OrderDesk"
PORT = int(os.environ.get("ORDERDESK_PORT", "8000"))
KEEP_BACKUPS = 30

log = logging.getLogger("orderdesk")


# ---------- helpers (no server needed, so they can be tested alone) ----------
def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir() -> Path:
    """Where orders, settings, backups and logs live. Survives upgrades and uninstalls."""
    override = os.environ.get("ORDERDESK_DATA")
    if override:
        folder = Path(override)
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    if sys.platform == "win32":
        candidates = [Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / PRODUCT,
                      Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / PRODUCT]
    elif sys.platform == "darwin":
        candidates = [Path.home() / "Library" / "Application Support" / PRODUCT]
    else:
        candidates = [Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / PRODUCT.lower()]
    for c in candidates:
        if _writable(c):
            return c
    raise RuntimeError("Cannot find a folder this program can write to.")


def lan_ip() -> str | None:
    """This computer's address on the shop network. No data is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        ip = sock.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        sock.close()


def already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def backup_db(db: Path, dest: Path, keep: int = KEEP_BACKUPS, today: dt.date | None = None) -> Path | None:
    """One copy per day, safe while the server is running. Returns the new file, or None if today's exists."""
    if not db.is_file():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"orders-{(today or dt.date.today()).strftime('%Y%m%d')}.db"
    if out.exists():
        return None
    tmp = out.with_suffix(".tmp")
    src, dst = sqlite3.connect(db), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, out)
    for old in sorted(dest.glob("orders-*.db"), reverse=True)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return out


def backup_loop(db: Path, dest: Path) -> None:
    while True:
        try:
            made = backup_db(db, dest)
            if made:
                log.info("backup written: %s", made)
        except Exception:
            log.exception("backup failed")
        time.sleep(6 * 3600)


def open_when_ready(url: str) -> None:
    for _ in range(60):
        if already_running(PORT):
            break
        time.sleep(0.5)
    webbrowser.open(url)


def setup_logging(folder: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        (folder / "logs").mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(folder / "logs" / "orderdesk.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"))
    except OSError:
        pass
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


# ---------- start ----------
def main(argv: list[str]) -> int:
    quiet = "--no-browser" in argv
    folder = data_dir()
    setup_logging(folder)
    os.environ.setdefault("DB_PATH", str(folder / "orders.db"))
    os.environ.setdefault("PRINT_DIR", str(folder / "prints"))
    os.environ.setdefault("CONFIG_FILE", str(folder / "settings.json"))

    if already_running(PORT):
        log.info("%s is already running.", PRODUCT)
        if not quiet:
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return 0
    if not port_is_free(PORT):
        print(f"Port {PORT} is used by another program. Close it, or set ORDERDESK_PORT to another number.")
        return 2

    from app.config import Settings          # imported here so the helpers above work without the server installed
    from app.main import create_app
    import uvicorn

    settings = Settings.from_env()
    ip = lan_ip()
    settings.lan_url = f"http://{ip}:{PORT}" if ip else ""
    app = create_app(settings)

    threading.Thread(target=backup_loop, args=(Path(settings.db_path), folder / "backups"), daemon=True).start()
    if not quiet:
        target = f"http://127.0.0.1:{PORT}/" + ("" if settings.configured else "setup")
        threading.Thread(target=open_when_ready, args=(target,), daemon=True).start()

    print("=" * 60)
    print(f" {PRODUCT} is running. Keep this window open (you can minimise it).")
    print(f" On this computer:  http://127.0.0.1:{PORT}/")
    if settings.lan_url:
        print(f" Guests' phones:    {settings.lan_url}/   (on the shop Wi-Fi)")
    print(f" Data folder:       {folder}")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_config=None)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logging.getLogger("orderdesk").exception("OrderDesk stopped because of an error")
        if getattr(sys, "frozen", False):
            input("Something went wrong. The details are in the log file. Press Enter to close.")
        sys.exit(1)
