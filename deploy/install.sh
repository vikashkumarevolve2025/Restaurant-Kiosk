#!/usr/bin/env bash
# Installs Karam Kitchen on Ubuntu / Debian / Raspberry Pi OS.
# Run from the project folder:  sudo bash deploy/install.sh https://order.yourshop.in
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
PUBLIC_URL="${1:-}"
[ -n "$PUBLIC_URL" ] || { echo "Usage: sudo bash deploy/install.sh https://your-domain"; exit 1; }
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/karam-kitchen

apt-get update -y
apt-get install -y python3 python3-venv python3-pip chromium-browser 2>/dev/null || apt-get install -y python3 python3-venv python3-pip chromium

id karam >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin karam
mkdir -p "$APP"
# Copy the code; never overwrite the database, prints or .env of an existing install.
tar -C "$SRC" --exclude=.venv --exclude=data --exclude=prints --exclude=backups --exclude=.env --exclude=__pycache__ -cf - . | tar -C "$APP" -xf -
mkdir -p "$APP/data" "$APP/prints" "$APP/backups"

python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --upgrade pip
"$APP/.venv/bin/pip" install -r "$APP/requirements.txt" -r "$APP/requirements-printer.txt"

if [ ! -f "$APP/.env" ]; then
  cp "$APP/.env.example" "$APP/.env"
  STAFF=$(python3 -c "import secrets; print(secrets.randbelow(900000)+100000)")
  ADMIN=$(python3 -c "import secrets; print(secrets.randbelow(900000)+100000)")
  sed -i "s|^STAFF_PIN=.*|STAFF_PIN=$STAFF|; s|^ADMIN_PIN=.*|ADMIN_PIN=$ADMIN|; s|^PUBLIC_URL=.*|PUBLIC_URL=$PUBLIC_URL|; s|^TRUST_PROXY=.*|TRUST_PROXY=1|" "$APP/.env"
  echo "=============================================="
  echo " Kitchen PIN: $STAFF"
  echo " Owner PIN:   $ADMIN     (write these down)"
  echo "=============================================="
  echo "Now edit $APP/.env: shop name, address, GSTIN, printer."
fi
chown -R karam:karam "$APP"
chmod 600 "$APP/.env"

install -m 644 "$APP/deploy/karam-kitchen.service" /etc/systemd/system/karam-kitchen.service
systemctl daemon-reload
systemctl enable --now karam-kitchen
echo "0 3 * * * karam /opt/karam-kitchen/deploy/backup.sh >> /opt/karam-kitchen/backups/backup.log 2>&1" > /etc/cron.d/karam-kitchen-backup
chmod 644 /etc/cron.d/karam-kitchen-backup
chmod +x "$APP"/deploy/*.sh

sleep 2
curl -fsS http://127.0.0.1:8000/healthz && echo " <- server is running" || echo "Server did not start. Check: journalctl -u karam-kitchen -n 50"
