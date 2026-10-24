"""Karam Kitchen ordering server.

Run:  uvicorn app.main:create_app --factory --env-file .env
"""
from __future__ import annotations

import hmac
import html
import logging
import time
from collections import defaultdict, deque
from pathlib import Path

import segno
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import admin as adm
from . import orders as svc
from . import runtime_config as rc
from .config import BASE_DIR, Settings
from .db import connect, init_db
from .models import AvailabilityIn, ImageIn, MenuItemIn, MenuItemPatch, MoveIn, OrderEditIn, OrderIn, PHONE_RE, SettingsIn, SetupIn, StatusIn
from .printer import PrinterError, list_system_printers, print_bill, print_order

log = logging.getLogger("karam")
STATIC = BASE_DIR / "static"


class RateLimiter:
    """Small in-memory sliding window. Fine for one shop on one server process."""

    def __init__(self) -> None:
        self.hits: dict[tuple, deque] = defaultdict(deque)

    def check(self, key: tuple, limit: int, window: float) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, detail={"code": "rate_limited", "message": "Too many requests. Please wait a minute and try again."})
        q.append(now)

    def blocked(self, key: tuple, limit: int, window: float) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        return len(q) >= limit

    def record(self, key: tuple) -> None:
        self.hits[key].append(time.monotonic())


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    if not s.staff_pin:
        raise RuntimeError("STAFF_PIN is not set. Copy .env.example to .env and choose a PIN for the kitchen screen.")
    init_db(s.db_path)

    app = FastAPI(title=s.shop_name + " ordering", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = s
    limiter = RateLimiter()

    # ---------- helpers ----------
    def client_ip(request: Request) -> str:
        if s.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def get_db():
        conn = connect(s.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def admin_pin() -> str:
        return s.admin_pin or s.staff_pin

    def pin_ok(given: str | None, expected: str) -> bool:
        return given is not None and hmac.compare_digest(given.encode(), expected.encode())

    def check_pin(request: Request, given: str | None, allowed: tuple[str, ...]) -> None:
        # Only wrong PINs count towards the limit, so a screen that polls every few seconds is never blocked.
        key = ("badpin", client_ip(request))
        if limiter.blocked(key, 10, 60):
            raise HTTPException(429, detail={"code": "rate_limited", "message": "Too many wrong PINs. Wait a minute and try again."})
        if not any(pin_ok(given, a) for a in allowed):
            limiter.record(key)
            raise HTTPException(401, detail={"code": "bad_pin", "message": "Wrong PIN."})

    def require_staff(request: Request, x_staff_pin: str | None = Header(default=None)) -> None:
        check_pin(request, x_staff_pin, (s.staff_pin, admin_pin()))   # the owner PIN works here too

    def require_admin(request: Request, x_staff_pin: str | None = Header(default=None)) -> None:
        check_pin(request, x_staff_pin, (admin_pin(),))

    def print_task(order: dict) -> None:
        conn = connect(s.db_path)
        try:
            where = print_order(order, s)
            svc.mark_printed(conn, order["id"])
            log.info("printed token %s via %s", order["token"], where)
        except PrinterError as exc:
            log.error("print failed for token %s: %s", order["token"], exc)
        finally:
            conn.close()

    def fail(e: svc.OrderError):
        raise HTTPException(e.status, detail={"code": e.code, "message": e.message})

    # ---------- errors and headers ----------
    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        msg = str(first.get("msg", "Please check your details.")).removeprefix("Value error, ")
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid", "message": msg}})

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------- guest API ----------
    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/menu")
    def menu(conn=Depends(get_db)):
        rows = conn.execute("SELECT * FROM menu_items ORDER BY sort").fetchall()
        items = [
            {"id": r["id"], "category": r["category"], "name": r["name"], "description": r["description"],
             "price": r["price"], "veg": bool(r["veg"]), "spice": r["spice"], "hue": r["hue"], "available": bool(r["available"]),
             "image": adm.image_url(r["image"]), "image_credit": r["image_credit"] or ""}
            for r in rows
        ]
        cats = list(dict.fromkeys(i["category"] for i in items))   # items are already sorted
        return {
            "shop": {"name": s.shop_name, "tables": s.tables, "gst_percent": s.gst_percent},
            "categories": cats,
            "items": items,
        }

    @app.get("/api/customers/lookup")
    def lookup(request: Request, phone: str = Query(min_length=10, max_length=10), conn=Depends(get_db)):
        limiter.check(("lookup", client_ip(request)), 10, 60)
        if not PHONE_RE.match(phone):
            return {"found": False}
        return svc.lookup_customer(conn, phone)

    @app.post("/api/orders", status_code=201)
    def create_order(payload: OrderIn, request: Request, background: BackgroundTasks, conn=Depends(get_db)):
        limiter.check(("order", client_ip(request)), 12, 60)
        try:
            order = svc.create_order(conn, s, payload)
        except svc.OrderError as e:
            fail(e)
        background.add_task(print_task, order)
        return svc.public_view(order)

    @app.put("/api/orders/{order_id}/items")
    def edit_order(order_id: int, payload: OrderEditIn, request: Request, background: BackgroundTasks, conn=Depends(get_db)):
        limiter.check(("edit", client_ip(request)), 20, 60)
        try:
            order = svc.edit_order(conn, s, order_id, payload.edit_key, payload.items)
        except svc.OrderError as e:
            fail(e)
        if order["status"] != "cancelled":
            background.add_task(print_task, order)   # the kitchen gets a fresh slip marked UPDATED
        return svc.public_view(order)

    @app.get("/api/tables/{table_no}/bill")
    def guest_bill(table_no: int, conn=Depends(get_db)):
        try:
            bill = svc.table_bill(conn, s, table_no)
        except svc.OrderError as e:
            fail(e)
        return {"bill": svc.public_bill(bill) if bill else None}

    @app.post("/api/tables/{table_no}/bill/request")
    def guest_request_bill(table_no: int, request: Request, conn=Depends(get_db)):
        limiter.check(("billreq", client_ip(request)), 6, 60)
        try:
            return {"bill": svc.public_bill(svc.request_bill(conn, s, table_no))}
        except svc.OrderError as e:
            fail(e)

    # ---------- staff API ----------
    @app.get("/api/orders", dependencies=[Depends(require_staff)])
    def list_orders(status: str = Query("active", pattern="^(active|all)$"), date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), conn=Depends(get_db)):
        return {"orders": svc.list_orders(conn, s, status, date)}

    @app.get("/api/stats/today", dependencies=[Depends(require_staff)])
    def stats(conn=Depends(get_db)):
        return svc.today_stats(conn, s)

    @app.patch("/api/orders/{order_id}/status", dependencies=[Depends(require_staff)])
    def change_status(order_id: int, body: StatusIn, conn=Depends(get_db)):
        try:
            return svc.set_status(conn, s, order_id, body.status)
        except svc.OrderError as e:
            fail(e)

    @app.post("/api/orders/{order_id}/print", dependencies=[Depends(require_staff)])
    def reprint(order_id: int, conn=Depends(get_db)):
        order = svc.get_order(conn, s, order_id)
        if not order:
            raise HTTPException(404, detail={"code": "not_found", "message": "Order not found."})
        try:
            where = print_order(order, s)
        except PrinterError as exc:
            raise HTTPException(502, detail={"code": "print_failed", "message": str(exc)})
        svc.mark_printed(conn, order_id)
        return {"printed": True, "via": where}

    @app.get("/api/bills", dependencies=[Depends(require_staff)])
    def staff_bills(conn=Depends(get_db)):
        return {"bills": svc.open_bills(conn, s)}

    @app.post("/api/tables/{table_no}/bill/print", dependencies=[Depends(require_staff)])
    def staff_print_bill(table_no: int, conn=Depends(get_db)):
        try:
            bill = svc.table_bill(conn, s, table_no)
        except svc.OrderError as e:
            fail(e)
        if not bill:
            raise HTTPException(404, detail={"code": "no_bill", "message": "This table has no open bill."})
        try:
            where = print_bill(bill, s, svc.now(s))
        except PrinterError as exc:
            raise HTTPException(502, detail={"code": "print_failed", "message": str(exc)})
        return {"printed": True, "via": where}

    @app.post("/api/tables/{table_no}/bill/close", dependencies=[Depends(require_staff)])
    def staff_close_bill(table_no: int, conn=Depends(get_db)):
        try:
            return {"bill": svc.close_bill(conn, s, table_no)}
        except svc.OrderError as e:
            fail(e)

    @app.patch("/api/menu/{item_id}", dependencies=[Depends(require_staff)])
    def set_available(item_id: str, body: AvailabilityIn, conn=Depends(get_db)):
        cur = conn.execute("UPDATE menu_items SET available = ? WHERE id = ?", (int(body.available), item_id))
        if cur.rowcount == 0:
            raise HTTPException(404, detail={"code": "not_found", "message": "Item not found."})
        return {"id": item_id, "available": body.available}

    # ---------- admin API (owner PIN) ----------
    A = [Depends(require_admin)]

    def guard(fn, *a):
        try:
            return fn(*a)
        except svc.OrderError as e:
            fail(e)

    @app.get("/api/admin/settings", dependencies=A)
    def admin_settings():
        return rc.settings_view(s)

    @app.put("/api/admin/settings", dependencies=A)
    def admin_save_settings(body: SettingsIn):
        if not s.config_file:
            raise HTTPException(409, detail={"code": "read_only", "message": "On this server the settings are kept in the .env file. Edit that file and restart."})
        try:
            rc.apply_settings(s, body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid", "message": str(exc)})
        s.save()
        return rc.settings_view(s)

    @app.get("/api/admin/printers", dependencies=A)
    def admin_printers():
        return {"printers": list_system_printers()}

    @app.post("/api/admin/menu", status_code=201, dependencies=A)
    def admin_add_item(body: MenuItemIn, conn=Depends(get_db)):
        return guard(adm.create_item, conn, body)

    @app.patch("/api/admin/menu/{item_id}", dependencies=A)
    def admin_edit_item(item_id: str, body: MenuItemPatch, conn=Depends(get_db)):
        return guard(adm.update_item, conn, item_id, body)

    @app.delete("/api/admin/menu/{item_id}", dependencies=A)
    def admin_delete_item(item_id: str, conn=Depends(get_db)):
        guard(adm.delete_item, conn, item_id, s)
        return {"deleted": item_id}

    @app.put("/api/admin/menu/{item_id}/image", dependencies=A)
    def admin_set_image(item_id: str, body: ImageIn, conn=Depends(get_db)):
        return guard(adm.set_image, conn, s, item_id, body.data, body.credit)

    @app.delete("/api/admin/menu/{item_id}/image", dependencies=A)
    def admin_remove_image(item_id: str, conn=Depends(get_db)):
        return guard(adm.remove_image, conn, s, item_id)

    @app.post("/api/admin/menu/{item_id}/move", dependencies=A)
    def admin_move_item(item_id: str, body: MoveIn, conn=Depends(get_db)):
        guard(adm.move_item, conn, item_id, body.direction)
        return {"ok": True}

    @app.get("/api/admin/report", dependencies=A)
    def admin_report(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), conn=Depends(get_db)):
        return guard(adm.sales_report, conn, s, start, end)

    @app.get("/api/admin/orders", dependencies=A)
    def admin_orders(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                     phone: str | None = Query(None, max_length=15), status: str | None = Query(None, pattern="^(new|preparing|ready|served|cancelled)$"),
                     limit: int = Query(200, ge=1, le=500), conn=Depends(get_db)):
        return {"orders": guard(adm.search_orders, conn, s, start, end, phone, status, limit)}

    @app.get("/api/admin/orders.csv", dependencies=A)
    def admin_orders_csv(start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), conn=Depends(get_db)):
        rows = guard(adm.search_orders, conn, s, start, end, None, None, 500)
        return Response(adm.orders_csv(rows), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="orders-{start or "recent"}-{end or "today"}.csv"'})

    @app.get("/api/admin/customers", dependencies=A)
    def admin_customers(q: str | None = Query(None, max_length=40), limit: int = Query(200, ge=1, le=500), conn=Depends(get_db)):
        return {"customers": adm.list_customers(conn, q, limit)}

    @app.delete("/api/admin/customers/{phone}", dependencies=A)
    def admin_forget(phone: str, conn=Depends(get_db)):
        if not PHONE_RE.match(phone):
            raise HTTPException(422, detail={"code": "invalid", "message": "That is not a valid number."})
        return {"orders_anonymised": guard(adm.forget_customer, conn, phone)}

    @app.post("/api/admin/print-test", dependencies=A)
    def admin_print_test():
        try:
            where = print_order(adm.sample_order(s), s)
        except PrinterError as exc:
            raise HTTPException(502, detail={"code": "print_failed", "message": str(exc)})
        return {"printed": True, "via": where}

    # ---------- first-run setup ----------
    def is_local(request: Request) -> bool:
        return (request.client.host if request.client else "") in ("127.0.0.1", "::1") and "x-forwarded-for" not in request.headers

    @app.get("/api/setup/state")
    def setup_state(request: Request):
        return {"configured": s.configured, "local": is_local(request), "guest_url": rc.guest_url(s) or None,
                "can_save": bool(s.config_file)}

    @app.post("/api/setup", status_code=201)
    def do_setup(body: SetupIn, request: Request, conn=Depends(get_db)):
        if s.configured:
            raise HTTPException(409, detail={"code": "done", "message": "Setup is already finished. Change settings in the admin screen."})
        if not is_local(request):
            raise HTTPException(403, detail={"code": "not_local", "message": "Open this page on the shop computer to finish setup."})
        if not s.config_file:
            raise HTTPException(409, detail={"code": "no_file", "message": "Setup is only for the installed app."})
        try:
            rc.apply_settings(s, body.model_dump(exclude={"sample_menu"}, exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "invalid", "message": str(exc)})
        if not body.sample_menu:
            conn.execute("DELETE FROM menu_items")
        s.configured = True
        s.save()
        return {"configured": True, "guest_url": rc.guest_url(s) or None}

    # ---------- pages ----------
    @app.get("/", include_in_schema=False)
    def kiosk_page():
        return FileResponse(STATIC / "index.html")

    @app.get("/images/{name}", include_in_schema=False)
    def dish_image(name: str):
        path = adm.images_dir(s) / name
        if not adm.IMAGE_NAME_RE.match(name) or not path.is_file():
            raise HTTPException(404, detail={"code": "not_found", "message": "No such image."})
        # File names change whenever a photo is replaced, so browsers may keep them for a long time.
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/credits", response_class=HTMLResponse, include_in_schema=False)
    def credits_page(conn=Depends(get_db)):
        rows = conn.execute("SELECT name, image, image_credit FROM menu_items WHERE image IS NOT NULL ORDER BY sort").fetchall()
        lis = "".join(
            f'<li><b>{html.escape(r["name"])}</b>: {html.escape(r["image_credit"] or "Photo by the restaurant")}</li>' for r in rows
        ) or "<li>No dish photos yet.</li>"
        return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Photo credits</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#f6f1ec;color:#231a16;line-height:1.5}}
main{{max-width:720px;margin:0 auto}} li{{margin:6px 0;overflow-wrap:anywhere}} a{{color:#b83a0b}}</style></head><body><main>
<h1>Photo credits</h1><p>Dish photos and who took them. Photos marked CC are used under their Creative Commons licence.</p>
<ul>{lis}</ul><p><a href="/home">Back</a></p></main></body></html>""")

    @app.get("/dish3d.js", include_in_schema=False)
    def dish_art():
        return FileResponse(STATIC / "dish3d.js", media_type="text/javascript")

    @app.get("/home", include_in_schema=False)
    def home_page():
        return FileResponse(STATIC / "home.html")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(STATIC / "admin.html")

    @app.get("/setup", include_in_schema=False)
    def setup_page():
        return FileResponse(STATIC / "setup.html")

    @app.get("/kitchen", include_in_schema=False)
    def kitchen_page():
        return FileResponse(STATIC / "kitchen.html")

    @app.get("/tables", response_class=HTMLResponse, include_in_schema=False)
    def tables_page(request: Request):
        base = rc.guest_url(s) or str(request.base_url).rstrip("/")
        cards = []
        for n in range(1, s.tables + 1):
            url = f"{base}/?table={n}"
            svg = segno.make(url, error="m").svg_inline(scale=1, border=4, dark="#000000", light="#ffffff", omitsize=True)
            cards.append(
                f'<section class="card"><h2>Table {n}</h2><div class="qr">{svg}</div>'
                f'<p class="scan">Scan to order</p><p class="url">{html.escape(url)}</p></section>'
            )
        warn = ""
        if not s.public_url and s.lan_url:
            warn = ('<p class="warn">These codes use this computer\'s address on the shop network: <b>' + html.escape(base) +
                    '</b>. Guests must be connected to the shop Wi-Fi to order. In your router, reserve this address for this computer, '
                    'or the printed codes stop working if it changes.</p>')
        elif not s.public_url:
            warn = ('<p class="warn">The guest address is not set, so these codes use <b>' + html.escape(base) +
                    '</b>. Guests can only scan them if their phones can open that address. '
                    'Set it in Admin, Tools, and reprint.</p>')
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Table QR codes</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#f6f1ec;color:#231a16}}
h1{{margin:0 0 6px}} .warn{{background:#fbe6da;padding:10px 14px;border-radius:8px;max-width:60ch}}
.hint{{color:#6f625b;margin:0 0 18px}} button{{font:inherit;font-weight:700;padding:12px 22px;border:0;border-radius:8px;background:#1f6f4a;color:#fff;cursor:pointer}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:20px}}
.card{{background:#fff;border:1px solid #e4d9d0;border-radius:12px;padding:20px;text-align:center;break-inside:avoid}}
.card h2{{font-size:2.6rem;margin:0;line-height:1}} .qr{{max-width:260px;margin:14px auto}} .qr svg{{width:100%;height:auto;display:block}}
.scan{{font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin:0}} .url{{font:11px ui-monospace,monospace;color:#555;overflow-wrap:anywhere;margin:8px 0 0}}
@media print{{body{{background:#fff;padding:0}} .noprint{{display:none}} .grid{{grid-template-columns:1fr 1fr}} .card{{border:2px solid #000}}}}
</style></head><body>
<div class="noprint"><h1>{html.escape(s.shop_name)} table QR codes</h1>
<p class="hint">Print this page and put one card on each table.</p>{warn}
<p><button onclick="window.print()">Print</button></p></div>
<div class="grid">{''.join(cards)}</div></body></html>"""
        return HTMLResponse(page)

    return app
