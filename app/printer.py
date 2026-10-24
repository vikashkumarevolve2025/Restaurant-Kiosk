"""Slip rendering and printing.

PRINTER=file     writes each slip to PRINT_DIR (default, good for testing)
PRINTER=network  ESC/POS over TCP 9100 (most Ethernet/Wi-Fi receipt printers)
PRINTER=usb      ESC/POS over USB (set PRINTER_USB_VENDOR and PRINTER_USB_PRODUCT)
PRINTER=windows  a printer installed in Windows (PRINTER_NAME, empty means the default printer)
PRINTER=none     prints nothing

Receipt printers have patchy support for the rupee sign, so slips use "Rs".
"""
from __future__ import annotations

import logging
import textwrap
from datetime import datetime
from pathlib import Path

from .config import Settings

log = logging.getLogger("karam.printer")


class PrinterError(Exception):
    pass


def inr(n: int) -> str:
    s = str(int(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "Rs " + s


def _lr(left: str, right: str, cols: int) -> str:
    gap = max(1, cols - len(left) - len(right))
    return left + " " * gap + right


def render_lines(order: dict, s: Settings) -> list[tuple[str, str]]:
    """Return (style, text) pairs. style is 'n' normal, 'c' centred, 'b' bold, 'T' big token."""
    w, rule = s.cols, "-" * s.cols
    out: list[tuple[str, str]] = [("cb", s.shop_name)]
    if s.shop_addr:
        out.append(("c", s.shop_addr))
    if s.gstin:
        out.append(("c", f"GSTIN {s.gstin}"))
    out += [
        ("n", rule),
        ("c", "TOKEN"),
        ("T", f"#{order['token']}"),
        ("cb", order["type_label"]),
    ]
    if order.get("updated_at"):
        out.append(("cb", "** UPDATED ORDER **"))
    out += [
        ("n", rule),
        ("n", order["created_label"]),
        ("n", _lr("Name", order["name"][: w - 6], w)),
        ("n", _lr("Phone", "+91 " + order["phone_masked"], w)),
        ("n", rule),
    ]
    for it in order["items"]:
        amount = inr(it["line"])
        name_w = max(8, w - len(amount) - 5)
        label = it["name"] + (" *" if it.get("no_gst") else "")   # packaged item at MRP
        wrapped = textwrap.wrap(label, name_w) or [label]
        out.append(("n", _lr(f"{it['qty']:>2}x {wrapped[0]}", amount, w)))
        out.extend(("n", "    " + extra) for extra in wrapped[1:])
    out += [
        ("n", rule),
        ("n", _lr("Subtotal", inr(order["subtotal"]), w)),
        ("n", _lr(f"GST {order['gst_percent']}%", inr(order["gst"]), w)),
        ("b", _lr("TOTAL", inr(order["total"]), w)),
        ("n", rule),
    ]
    out += _mrp_note(order["items"], w)
    out.append(("c", f"Thank you, {order['name'].split(' ')[0]}!"))
    return out


def render_bill_lines(bill: dict, s: Settings, when: str) -> list[tuple[str, str]]:
    """The final bill for a table: every round on one slip, dishes combined."""
    w, rule = s.cols, "-" * s.cols
    out: list[tuple[str, str]] = [("cb", s.shop_name)]
    if s.shop_addr:
        out.append(("c", s.shop_addr))
    if s.gstin:
        out.append(("c", f"GSTIN {s.gstin}"))
    tokens = ", ".join(f"#{r['token']}" for r in bill["rounds"])
    out += [("n", rule), ("c", "BILL"), ("T", f"Table {bill['table']}"), ("n", rule), ("n", when)]
    out += [("n", line) for line in textwrap.wrap(f"Tokens {tokens}", w)] + [("n", rule)]
    for it in bill["items"]:
        amount = inr(it["line"])
        name_w = max(8, w - len(amount) - 5)
        label = it["name"] + (" *" if it.get("no_gst") else "")   # packaged item at MRP
        wrapped = textwrap.wrap(label, name_w) or [label]
        out.append(("n", _lr(f"{it['qty']:>2}x {wrapped[0]}", amount, w)))
        out.extend(("n", "    " + extra) for extra in wrapped[1:])
    out += [
        ("n", rule),
        ("n", _lr("Subtotal", inr(bill["subtotal"]), w)),
        ("n", _lr(f"GST {bill['gst_percent']}%", inr(bill["gst"]), w)),
        ("b", _lr("TOTAL", inr(bill["total"]), w)),
        ("n", rule),
    ]
    out += _mrp_note(bill["items"], w)
    out.append(("c", "Thank you! Please visit again."))
    return out


def _as_text(lines: list[tuple[str, str]], s: Settings) -> str:
    out = []
    for style, text in lines:
        out.append(text.center(s.cols).rstrip() if ("c" in style or style == "T") else text)
    return "\n".join(out) + "\n"


def _mrp_note(items: list[dict], w: int) -> list[tuple[str, str]]:
    if not any(i.get("no_gst") for i in items):
        return []
    return [("n", line) for line in textwrap.wrap("* Packaged item at MRP, no GST", w)]


def render_slip(order: dict, s: Settings) -> str:
    return _as_text(render_lines(order, s), s)


def _print_escpos(p, lines: list[tuple[str, str]]) -> None:
    for style, text in lines:
        align = "center" if "c" in style else "left"
        if style == "T":
            p.set(align="center", bold=True, width=4, height=4)
        else:
            p.set(align=align, bold=("b" in style), width=1, height=1)
        p.text(text + "\n")
    p.set(align="left", bold=False, width=1, height=1)
    p.text("\n\n")
    p.cut()


def print_order(order: dict, s: Settings) -> str:
    """Print one slip. Returns the backend used. Raises PrinterError on failure."""
    stamp = datetime.fromisoformat(order["created_at"]).strftime("%Y%m%d")
    stem = f"{stamp}-token-{order['token']:03d}"
    if order.get("updated_at"):
        stem += "-updated-" + datetime.fromisoformat(order["updated_at"]).strftime("%H%M%S")
    return _send(render_lines(order, s), s, stem)


def print_bill(bill: dict, s: Settings, at: datetime) -> str:
    """Print a table's final bill. Returns the backend used. Raises PrinterError on failure."""
    lines = render_bill_lines(bill, s, at.strftime("%d %b %Y, %I:%M %p"))
    return _send(lines, s, f"{at.strftime('%Y%m%d-%H%M%S')}-bill-table-{bill['table']}")


def _send(lines: list[tuple[str, str]], s: Settings, file_stem: str) -> str:
    mode = s.printer
    if mode == "none":
        return "none"
    if mode == "file":
        out_dir = Path(s.print_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{file_stem}.txt"
        path.write_text(_as_text(lines, s), encoding="utf-8")
        return f"file:{path}"
    if mode == "windows":
        try:
            from escpos.printer import Win32Raw  # type: ignore
        except ImportError as exc:
            raise PrinterError("Windows printing is not available here (python-escpos or pywin32 is missing).") from exc
        try:
            p = Win32Raw(s.printer_name or "")
            try:
                _print_escpos(p, lines)
            finally:
                p.close()
        except Exception as exc:  # printer offline, wrong name, driver problem ...
            raise PrinterError(f"Could not print: {exc}") from exc
        return "windows"
    if mode in ("network", "usb"):
        try:
            from escpos.printer import Network, Usb  # type: ignore
        except ImportError as exc:
            raise PrinterError("python-escpos is not installed. Run: pip install -r requirements-printer.txt") from exc
        try:
            if mode == "network":
                if not s.printer_host:
                    raise PrinterError("PRINTER_HOST is not set.")
                p = Network(s.printer_host, port=s.printer_port, timeout=5)
            else:
                if not (s.usb_vendor and s.usb_product):
                    raise PrinterError("PRINTER_USB_VENDOR and PRINTER_USB_PRODUCT are not set.")
                p = Usb(int(s.usb_vendor, 16), int(s.usb_product, 16))
            try:
                _print_escpos(p, lines)
            finally:
                p.close()
        except PrinterError:
            raise
        except Exception as exc:  # network down, paper out, device busy ...
            raise PrinterError(f"Could not print: {exc}") from exc
        return mode
    raise PrinterError(f"Unknown PRINTER value: {mode!r}")


def list_system_printers() -> list[str]:
    """Names of printers installed in Windows. Empty on other systems."""
    try:
        import win32print  # type: ignore
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return sorted({p[2] for p in win32print.EnumPrinters(flags)})
    except Exception:
        return []
