#!/bin/bash
#
# Restore the r2lab database from a pgdump file.
#
# Usage:
#   deploy/restore-db.sh path/to/r2lab.pgdump

set -euo pipefail

if systemctl is-active --quiet r2lab-api 2>/dev/null; then
  echo "ERROR: r2lab-api service is running — stop it first:"
  echo "  systemctl stop r2lab-api"
  exit 1
fi

DUMP=${1:?Usage: $0 <pgdump-file>}
DB_NAME=r2lab

echo "=== Dropping and recreating database ==="
sudo -u postgres dropdb --if-exists "${DB_NAME}"
sudo -u postgres createdb "${DB_NAME}"

echo "=== Restoring from ${DUMP} ==="
sudo -u postgres pg_restore \
  --no-owner --no-privileges \
  --dbname="${DB_NAME}" \
  "${DUMP}" || true

echo "=== Configuring pg_hba.conf ==="
PG_DATA=$(sudo -u postgres psql -tc "SHOW data_directory" | xargs)
cat > "${PG_DATA}/pg_hba.conf" <<'HBA'
# single-purpose VM — trust all local connections
local   all   all                     trust
host    all   all   127.0.0.1/32      trust
host    all   all   ::1/128           trust
HBA
systemctl reload postgresql

echo "=== Stamping alembic to head ==="
cd /root/r2lab-api
sudo -u postgres .venv/bin/alembic stamp head

echo "=== Done ==="
