#!/bin/bash
#
# PostgreSQL major-version upgrade helper for Fedora.
#
# Fedora upgrades often bump PostgreSQL (e.g. 15 → 16), leaving the
# old data directory unreadable. Since our dataset is small, we use
# the simple dump/restore approach rather than pg_upgrade.
#
# Run BEFORE the Fedora upgrade:
#   deploy/pg-upgrade.sh dump
#
# Run AFTER the Fedora upgrade:
#   deploy/pg-upgrade.sh restore
#

set -euo pipefail

DUMP_DIR=/root
DUMP_FILE="${DUMP_DIR}/r2lab-pre-upgrade.pgdump"
DB_NAME=r2lab

case "${1:-}" in
  dump)
    echo "=== Dumping ${DB_NAME} before upgrade ==="
    sudo -u postgres pg_dump \
      --format=custom \
      --file="${DUMP_FILE}" \
      "${DB_NAME}"
    echo "Dump saved to ${DUMP_FILE}"
    echo
    echo "You can now proceed with the Fedora upgrade."
    echo "After the upgrade, run: $0 restore"
    ;;

  restore)
    if [[ ! -f "${DUMP_FILE}" ]]; then
      echo "ERROR: ${DUMP_FILE} not found — did you run '$0 dump' first?"
      exit 1
    fi
    echo "=== Initializing new PostgreSQL data directory ==="
    sudo postgresql-setup --initdb 2>/dev/null || true
    sudo systemctl start postgresql

    echo "=== Restoring from ${DUMP_FILE} ==="
    deploy/restore-db.sh "${DUMP_FILE}"

    echo "=== Restarting r2lab-api ==="
    sudo systemctl restart r2lab-api

    echo
    echo "Done. You may delete ${DUMP_FILE} once verified."
    ;;

  *)
    echo "Usage: $0 {dump|restore}"
    echo
    echo "  dump     — run BEFORE Fedora upgrade"
    echo "  restore  — run AFTER Fedora upgrade"
    exit 1
    ;;
esac
