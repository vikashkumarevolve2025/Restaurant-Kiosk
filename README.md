# Karam Kitchen ordering server

Self-order kiosk, table QR ordering, kitchen screen and receipt printing for a small restaurant.
FastAPI and SQLite, no build step.

| Address | What it is | Who uses it |
|---|---|---|
| `/home` | Landing page: one card per user. Customers open the menu; kitchen staff and the owner type their PIN there and land in their screen already signed in. | Everyone |
| `/` | Menu, cart, name and phone, order slip. `/?table=2` pre-selects Table 2. | Guests (kiosk or phone) |
| `/kitchen` | Live order board, sound alert, mark items sold out. Asks for the staff PIN. | Kitchen |
| `/admin` | Owner screen: edit menu and prices, sales reports, order history and CSV, guests, printer test. Asks for the owner PIN. | Owner |
| `/tables` | Printable QR card for each table. | You, once |
| `/api/...` | JSON API used by the pages. | |

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set STAFF_PIN, ADMIN_PIN and PUBLIC_URL at least
uvicorn app.main:create_app --factory --env-file .env --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/`, then `/kitchen` in a second tab. Orders appear within 4 seconds.

Tests: `pip install -r requirements-dev.txt && pytest`  (the route tests need FastAPI's test client, so run them on your machine)

## Admin screen

Open `/admin` and enter `ADMIN_PIN`. If you leave `ADMIN_PIN` empty, the kitchen PIN opens it too, so set a separate one.
The kitchen PIN cannot change prices or read reports.

- **Menu:** add, edit, delete, reorder, mark unavailable. New categories appear as soon as you type one. A price change applies to new orders only; past orders keep the price they were placed at. Deleting an item leaves history unchanged.
- **Dish photos:** in Menu, each dish has **Add photo / Change photo** and **Remove photo**. The browser shrinks the photo (longest side 1000 px, JPEG) before upload, so phone photos are fine; the server accepts JPEG, PNG or WebP up to 2 MB and stores them in `data/images` next to the database. Dishes without a photo show a drawn 3D picture. Credits for photos taken from elsewhere are listed at `/credits` (linked from the menu and the landing page). The sample menu's photos are bundled in `static/sample-photos` and loaded into a new database automatically; they come from Wikimedia Commons under Creative Commons licences (see `static/sample-photos/CREDITS.md`), so keep the credits page if you keep those photos.
- **Packaged items (no GST):** tick **No GST: packaged item sold at MRP** on items like bottled water or soft drinks. GST is then charged only on the other items; the cart, slip and table bill mark these items with `*`. Orders keep the rule they were placed with.
- **UPI payment:** in Tools, upload the shop's UPI QR (a screenshot from the bank or UPI app is fine) and optionally the UPI ID. After ordering at the counter kiosk, guests see **Pay by UPI** with the QR and the exact amount; cash or card at the counter still works. Remove the QR to hide the box.
- **Sales:** any date range up to a year: sales, orders, average order, GST collected, daily bars, top ten items, dine in versus takeaway, sales by table. Cancelled orders are left out.
- **Orders:** search by dates, phone prefix or status. Reprint a slip. Download a CSV for your accountant (cells that start with `=`, `+`, `-` or `@` are neutralised so a guest name cannot run a spreadsheet formula).
- **Customers:** list and search guests. Forget removes a guest's name and number; their past orders stay without personal details, so totals do not change.
- **Tools:** edit shop name, address, GSTIN, GST, table count, printer, guest address and PINs, and print a test slip. Editing needs `CONFIG_FILE=data/settings.json` in `.env`; changes are saved to that file and override `.env`. Without it the settings are read-only and come from `.env`.

## Table QR codes

1. Set `PUBLIC_URL` in `.env` to the address guests can open on their phones, then restart.
2. Open `/tables` and press Print. Cut out one card for each table.
3. Change the number of tables with `TABLE_COUNT`.

A guest who scans Table 2 lands on `/?table=2`. The table is fixed by the QR code and cannot be changed at checkout; only the counter kiosk (no `?table=`) shows the table picker.

Every order from a table joins that table's running bill until staff tap **Paid, close table** on the kitchen screen. After ordering, a table guest stays on a live order screen showing each order's kitchen status. They can **edit** an order (change quantities, remove dishes, or remove the whole order) until the kitchen taps Start cooking; the kitchen screen then marks it **Updated by guest**, beeps, and a fresh slip prints. **Add more items** joins their order while the kitchen has not started it, otherwise it goes as a new order on the same bill. Only the phone that placed an order can edit it. Their phone remembers their name and number while the bill is open (even after a reload or rescan), so later orders go straight from the cart. **Finish & ask for bill** alerts the kitchen screen, and **Print bill** prints all rounds on one slip. Once the table is closed, the next scan starts a new bill.

## Receipt printer

Set `PRINTER` in `.env`:

| Value | Use |
|---|---|
| `file` | Default. Writes each slip to `prints/` as text. Good for testing. |
| `network` | ESC/POS over TCP port 9100. Set `PRINTER_HOST`. Most Ethernet and Wi-Fi receipt printers. |
| `usb` | Set `PRINTER_USB_VENDOR` and `PRINTER_USB_PRODUCT` (hex ids from `lsusb`). |
| `none` | No printing. |

For `network` and `usb`: `pip install -r requirements-printer.txt`. Use `PRINTER_COLS=32` for 58 mm paper.
The slip prints automatically when an order is placed. The kitchen screen has a Reprint button.
If the printer is off, the order is still saved and shows on the kitchen screen; the failure is logged.

The kiosk page also has a Print slip button (browser printing). To print without a dialog, start Chrome with `--kiosk-printing`.

## Going live

Step by step for a shop computer with a free Cloudflare Tunnel (no cloud costs): see `deploy/DEPLOY.md`.

## Where to run it

The printer sits on the shop network, so the server should too.

- **Recommended:** a mini PC or Raspberry Pi in the shop, running this with `systemd` or Docker. It reaches the printer on the LAN. Expose it to guests with a tunnel (for example Cloudflare Tunnel) or your router, on a domain with HTTPS, and put that domain in `PUBLIC_URL`.
- **Cloud server (EC2, Lightsail):** works for ordering and the kitchen screen, but cannot reach a printer on your LAN. You would need a small print agent in the shop that polls the server.

Behind a tunnel or proxy, set `TRUST_PROXY=1`. Otherwise every guest looks like the same address to the rate limiter, and a few wrong PIN attempts would block the kitchen screen for a minute.

Back up `data/orders.db` (a single file). Run only one server process, because the rate limiter keeps its counters in memory.

## What it protects against

- Prices, totals, GST and tokens are computed on the server. The browser sends only item ids and quantities.
- Kitchen endpoints need the kitchen PIN; admin endpoints need the owner PIN. Both are sent in the `X-Staff-Pin` header, compared in constant time. Ten wrong PINs in a minute block that address for the rest of the minute. Correct PINs are never counted, so the kitchen screen's polling is not affected.
- Guests see only a masked phone number. The open "welcome back" lookup returns a first name and an order count, and is rate limited. Full phone numbers are visible only on the kitchen screen.
- Customer names are escaped before display. Orders and lookups are rate limited per IP.
- Unavailable items are rejected on the server, even if a kiosk still shows them.

Not included: online payment, individual staff accounts, and HTTPS. Terminate HTTPS in your proxy or tunnel.

Phone numbers are personal data. Decide how long you keep them, and tell guests why you ask.

## Layout

```
app/main.py        routes, auth, rate limits, /tables page
app/orders.py      pricing, tokens, status rules
app/admin.py       menu editing, reports, search, CSV, forget guest
app/printer.py     slip layout, file / network / usb printing
app/db.py          schema and seed
app/menu_data.py   starter menu
deploy/            install script, systemd service, backup, kiosk launcher, tunnel config
static/index.html  kiosk and guest page
static/kitchen.html
static/admin.html
tests/test_api.py, tests/test_admin.py
```

## Installed app for Windows (no server, no cloud)

For a shop that just wants a program on its computer: build `OrderDesk-Setup.exe` (GitHub Actions does it for free, see `packaging/README.md`), run it on the shop PC, and finish the setup page that opens. Shop details, printer and PINs are then edited on screen under Admin, Tools. Guests scan the table QR codes on the shop Wi-Fi. Details, printer notes and the fixed-IP advice are in `packaging/README.md`.
