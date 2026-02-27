#!/bin/bash
#
# Setup PostgreSQL for r2lab-api on Fedora
# Run as root (or with sudo)
#

set -e

DB_NAME="r2lab"
DB_USER="r2lab"
DB_PASS="r2lab"

# --- Install and start PostgreSQL ---
dnf install -y postgresql-server postgresql-contrib
postgresql-setup --initdb 2>/dev/null || true
systemctl enable --now postgresql

# --- Create user and database ---
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
    END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec
\c ${DB_NAME}
CREATE EXTENSION IF NOT EXISTS btree_gist;
SQL

# --- Allow password auth for local connections ---
PG_HBA=$(sudo -u postgres psql -t -c "SHOW hba_file" | xargs)
if grep -q "^local.*all.*all.*peer" "$PG_HBA"; then
    sed -i 's/^local\s\+all\s\+all\s\+peer/local   all             all                                     md5/' "$PG_HBA"
    systemctl reload postgresql
fi

echo ""
echo "PostgreSQL ready: database '${DB_NAME}', user '${DB_USER}'"
echo ""
echo "Next steps:"
echo "  cd /path/to/r2lab-api"
echo "  cp .env.example .env   # edit JWT_SECRET"
echo "  pip install -e ."
echo "  alembic upgrade head"
echo "  python scripts/bootstrap.py"
