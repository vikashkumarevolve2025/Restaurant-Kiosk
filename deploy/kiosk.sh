#!/usr/bin/env bash
# Opens the guest page full screen. Run this on the kiosk screen's computer, signed in to its desktop.
# --kiosk-printing sends "Print slip" straight to the default printer with no dialog.
URL="${1:-http://127.0.0.1:8000/}"
BROWSER=$(command -v chromium-browser || command -v chromium || command -v google-chrome)
exec "$BROWSER" --kiosk --kiosk-printing --noerrdialogs --disable-infobars --disable-pinch --overscroll-history-navigation=0 "$URL"
