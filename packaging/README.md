# Building and installing OrderDesk (Windows)

OrderDesk is an ordinary Windows program. You build the installer once, then run it on each shop's computer. No Python, no cloud, no monthly cost.

## 1. Build the installer (you, once per release)

You do not need a Windows PC. GitHub builds it for free:

1. Put this project in a GitHub repository (private is fine).
2. Open the **Actions** tab, choose **Build Windows installer**, click **Run workflow**.
3. When it finishes, download the artifact **OrderDesk-Windows-Installer**. Inside is `OrderDesk-Setup-<version>.exe`.

The run first checks that the built program starts and accepts a test order. If a step fails, the log shows which one.

To build on your own Windows PC instead:

```
pip install -r requirements.txt -r requirements-printer.txt pyinstaller
pyinstaller packaging/orderdesk.spec --noconfirm --distpath dist --workpath build
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\orderdesk.iss
```

Before your first release, open `packaging/orderdesk.iss` and change `AppPublisher`. "OrderDesk" is a placeholder name; change `AppName` there and `PRODUCT` in `orderdesk.py` if you rename it.

## 2. Install at the shop (about 10 minutes)

1. Run `OrderDesk-Setup-<version>.exe` on the shop computer. Keep "start automatically" ticked.
2. The setup page opens. Enter the restaurant name, address, GSTIN, number of tables, printer and two PINs (kitchen and owner).
3. Open **Table QR codes** from the Start menu and print them for the tables.
4. Use **Counter screen, full screen** for the self-order kiosk. Kitchen and Admin shortcuts are in the Start menu.

Printer: choose "Windows printer" and pick the thermal printer by its name in Windows. Choose "Network" or "USB" for printers that are not installed in Windows.

## 3. Things to get right

- **Fixed address.** Guests scan a QR code that holds the computer's address on the shop network (for example `http://192.168.1.20:8000`). In the router, reserve that address for this computer, or the codes break when the router hands out a new one. After a change, reprint the codes.
- **Shop Wi-Fi only.** Phones must be on the shop Wi-Fi. A phone on mobile data cannot reach the computer. Put a "Wi-Fi name and password" card next to the QR codes.
- **Keep the computer on** during opening hours, and set Windows not to sleep.
- **Windows Firewall.** The installer adds a rule that allows only devices on the local network. If a phone cannot connect, check that the Wi-Fi network is not set to "guest/isolated" mode in the router.
- **Data.** Orders, settings, daily backups (last 30) and logs are in `C:\ProgramData\OrderDesk`. Uninstalling keeps them.
- **Updating.** Run the newer installer over the old one. Data stays.
- **Security.** PINs travel unencrypted on the shop's own network. Do not expose port 8000 to the internet.
