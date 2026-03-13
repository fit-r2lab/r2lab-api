#!/bin/bash
#
# Initial setup on a fresh Fedora VM.
#
# Usage:
#   ssh root@r2lab.inria.fr
#   git clone <repo-url> /root/r2lab-api
#   cd /root/r2lab-api
#   deploy/setup.sh path/to/r2lab.pgdump
#

set -euo pipefail

DUMP=${1:?Usage: $0 <pgdump-file>}

echo "=== Installing system packages ==="
dnf install -y postgresql-server python3.12 python3.12-pip

echo "=== Initializing PostgreSQL ==="
postgresql-setup --initdb 2>/dev/null || true
systemctl enable --now postgresql

echo "=== Installing uv ==="
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "=== Setting up Python venv and dependencies ==="
cd /root/r2lab-api
uv venv
uv sync

echo "=== Creating .env ==="
if [[ ! -f .env ]]; then
  cp deploy/.env.example .env
  # generate a random JWT secret
  JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  sed -i "s/change-me-to-a-random-string/${JWT_SECRET}/" .env
  echo "Created .env — review and adjust settings in /root/r2lab-api/.env"
fi

echo "=== Restoring database ==="
deploy/restore-db.sh "${DUMP}"

echo "=== Installing systemd services ==="
ln -sf /root/r2lab-api/deploy/r2lab-api.service /etc/systemd/system/
ln -sf /root/r2lab-api/deploy/r2lab-backup.service /etc/systemd/system/
ln -sf /root/r2lab-api/deploy/r2lab-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now r2lab-api
systemctl enable --now r2lab-backup.timer

echo
echo "=== Setup complete ==="
echo "  Service status:  systemctl status r2lab-api"
echo "  Logs:            journalctl -u r2lab-api -f"
echo "  Config:          /root/r2lab-api/.env"
