# Going live on a shop computer (no cloud costs)

The server runs on a computer in the shop. A free Cloudflare Tunnel makes it reachable at your domain.
You pay for nothing beyond the domain you already own.

Assumed computer: mini PC or Raspberry Pi 4/5 running Ubuntu or Raspberry Pi OS, always on, wired to the shop router.

## 0. One-time shop setup
- Give the receipt printer a fixed IP address in your router (look for "DHCP reservation" or "static lease").
- On the computer: turn off sleep, and in the BIOS set "restart after power loss" to on.
- Run the tests on any machine first: `pip install -r requirements-dev.txt && pytest`.

## 1. Install the app
Copy the project folder to the shop computer, then:

    sudo bash deploy/install.sh https://order.yourshop.in

It installs everything, creates the service, schedules a nightly backup, and prints two PINs
(kitchen and owner). Write them down. Then edit `/opt/karam-kitchen/.env`:

    SHOP_NAME, SHOP_ADDRESS, SHOP_GSTIN
    PRINTER=network
    PRINTER_HOST=<the printer's fixed IP>

and restart: `sudo systemctl restart karam-kitchen`.
Check it: `curl http://127.0.0.1:8000/healthz` should print `{"ok":true}`.
Logs: `journalctl -u karam-kitchen -f`

USB printer instead: set `PRINTER=usb`, `PRINTER_USB_VENDOR` and `PRINTER_USB_PRODUCT` (from `lsusb`, for example 04b8:0e15 becomes 0x04b8 and 0x0e15),
then `sudo usermod -aG lp,plugdev karam` and restart. Some printers also need a udev rule for non-root access.

## 2. Point your domain at it (free)
1. Create a free Cloudflare account and add your domain. Cloudflare shows two nameservers.
2. At the company where you bought the domain, replace its nameservers with those two. Wait until Cloudflare says the domain is active (minutes to a few hours).
   If the domain already has email or other DNS records, copy them into Cloudflare first.
3. On the shop computer, install `cloudflared` (use Cloudflare's current instructions for Debian/Ubuntu, search "cloudflared install linux"), then:

       cloudflared tunnel login
       cloudflared tunnel create karam-kitchen
       cloudflared tunnel route dns karam-kitchen order.yourshop.in

4. Copy `deploy/cloudflared-config.yml.example` to `/etc/cloudflared/config.yml`, fill in the tunnel id and hostname,
   copy the credentials file `~/.cloudflared/<id>.json` to `/etc/cloudflared/`, then:

       sudo cloudflared service install
       sudo systemctl enable --now cloudflared

5. Open `https://order.yourshop.in/` on your phone using mobile data (not shop Wi-Fi). You should see the menu.
   HTTPS is handled by Cloudflare.

## 3. Table QR codes
Open `https://order.yourshop.in/tables`, press Print, cut out the cards.

## 4. Counter kiosk
On the kiosk screen's computer run `bash deploy/kiosk.sh` (it opens `http://127.0.0.1:8000/` full screen and prints with no dialog).
Set the receipt printer as that computer's default printer, and add the script to its startup applications.
The kiosk talks to the server directly, so ordering and printing at the counter keep working even if the shop's internet is down.
Orders from guests' phones need the internet.

## 5. Dry run, then open
Place test orders from a phone and from the kiosk. Check the slip, the kitchen screen at `/kitchen` and the admin report at `/admin`.
Press Tools, then Print test slip. Then clear the test data:

    sudo systemctl stop karam-kitchen && sudo rm /opt/karam-kitchen/data/orders.db* && sudo systemctl start karam-kitchen

## Keeping it safe
- `/kitchen` and `/admin` are on the public internet, protected only by their PINs (wrong guesses are rate limited).
  To lock them to your staff, use Cloudflare Access (free for small teams): add a rule for `order.yourshop.in/admin*` and `/kitchen*` that allows only your email addresses.
- Backups: nightly at 3 am to `/opt/karam-kitchen/backups` (last 30 kept). Better: plug in a USB drive and change the cron line to
  `backup.sh /media/yourdrive/karam-backups`.
- Updating the app later: copy the new project over and run `sudo bash deploy/install.sh https://order.yourshop.in` again.
  It keeps your database, PINs and settings.
- Phone numbers are personal data. Show a short notice at the kiosk, and use Customers, then Forget, on request.
