#!/bin/bash
#
# Restore the r2lab database from a pgdump file.
#
# Usage:
#   deploy/restore-db.sh path/to/r2lab.pgdump
#
# This creates the r2lab role and database if they don't exist,
# restores the dump, and stamps alembic to the current head
# (since the dump already contains all migrated tables).

set -euo pipefail

DUMP=${1:?Usage: $0 <pgdump-file>}
DB_NAME=r2lab
DB_USER=r2lab

echo "=== Creating role and database (if needed) ==="
sudo -u postgres psql -c "
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
      CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_USER}';
    END IF;
  END
  \$\$;
" 2>/dev/null

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" \
  | grep -q 1 \
  || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"

echo "=== Restoring from ${DUMP} ==="
sudo -u postgres pg_restore \
  --no-owner --no-privileges \
  --dbname="${DB_NAME}" \
  --clean --if-exists \
  "${DUMP}"

echo "=== Stamping alembic to head ==="
cd /root/r2lab-api
.venv/bin/alembic stamp head

echo "=== Done ==="
