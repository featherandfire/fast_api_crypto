#!/usr/bin/env bash
# deploy.sh — one-shot VPS deployment script
# Run as root on a fresh Ubuntu/Debian VPS
# Usage: bash deploy.sh yourdomain.com

set -euo pipefail

DOMAIN="${1:?Usage: $0 yourdomain.com}"
APP_DIR=/srv/crypto-portfolio
APP_USER=www-data

echo "==> Installing system deps"
apt-get update -qq
apt-get install -y python3.11 python3.11-venv python3-pip caddy curl

echo "==> Creating app directory"
mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Copying app files (run from repo root)"
rsync -a --exclude='.env' --exclude='*.db' --exclude='__pycache__' \
      --exclude='venv' --exclude='.git' \
      ./ "$APP_DIR/"

echo "==> Creating virtualenv and installing deps"
sudo -u "$APP_USER" python3.11 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "==> Writing .env (edit this file with your real SECRET_KEY)"
if [[ ! -f "$APP_DIR/.env" ]]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$SECRET
DATABASE_URL=sqlite+aiosqlite:///./crypto_portfolio.db
ACCESS_TOKEN_EXPIRE_MINUTES=60
COINGECKO_BASE_URL=https://api.coingecko.com/api/v3
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

echo "==> Installing systemd service"
sed "s|yourdomain.com|$DOMAIN|g" "$APP_DIR/crypto-portfolio.service" \
  > /etc/systemd/system/crypto-portfolio.service
systemctl daemon-reload
systemctl enable --now crypto-portfolio

echo "==> Configuring Caddy"
mkdir -p /var/log/caddy
sed "s|yourdomain.com|$DOMAIN|g" "$APP_DIR/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy

echo ""
echo "✓ Deployed to https://$DOMAIN"
echo "  - Service: systemctl status crypto-portfolio"
echo "  - Logs:    journalctl -u crypto-portfolio -f"
