#!/bin/bash
#
# Full migration test: drop DB, recreate, run alembic + bootstrap + both migrations.
# Intended for the macOS dev box with PostgreSQL installed locally.
#
set -e

DB_NAME="r2lab"
DB_USER="r2lab"
PLC_URL="postgresql://localhost/planetlab5"

[ -d alembic ] || { echo "Run this from the r2lab-api root directory"; exit 1; }

echo "=== PREREQUISITES ==="
echo " - [ ] PostgreSQL server running locally with a 'planetlab5' database"
echo "       See ./scripts/postgres-catchup-macos.sh if needed"
echo " - [ ] The r2lab database is not in use, i.e."
echo "   - [ ] API server is not running"
echo "   - [ ] No psql sessions are connected to the 'r2lab' database"


echo "=== Dropping and recreating database '${DB_NAME}' ==="
dropdb --if-exists "$DB_NAME"
createdb -O "$DB_USER" "$DB_NAME"
echo "Done."

echo ""
echo "=== Running alembic migrations ==="
alembic upgrade head

echo ""
echo "=== Bootstrapping (resource only — skip admin prompt) ==="
# feed empty email so bootstrap creates the resource but skips the admin user
echo "" | python scripts/bootstrap.py

echo ""
echo "=== Step 1: PLC migration ==="
python scripts/migrate_from_plc.py --plc-url "$PLC_URL"

echo ""
echo "=== Step 2: Historical leases migration ==="
python scripts/migrate_historical_leases.py

echo ""
echo "=== Quick sanity checks ==="
psql "$DB_NAME" <<'SQL'
SELECT 'users'      AS what, count(*) FROM "user"
UNION ALL
SELECT 'slices',           count(*) FROM slice
UNION ALL
SELECT 'leases',           count(*) FROM lease
UNION ALL
SELECT 'slice_members',    count(*) FROM slice_member
ORDER BY what;

-- check for any overlap violations (should return 0)
SELECT count(*) AS overlap_violations
FROM lease a
JOIN lease b ON a.resource_id = b.resource_id
                AND a.id < b.id
                AND a.t_from < b.t_until
                AND b.t_from < a.t_until;
SQL

echo ""
echo "=== All done ==="
