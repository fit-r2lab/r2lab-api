# R2Lab API — Deployment

The API runs on a Fedora VM as a systemd service.
The code lives in `/root/r2lab-api/` (git clone, no RPM).

## First-time setup

```bash
ssh root@r2lab.inria.fr
git clone <repo-url> /root/r2lab-api
cd /root/r2lab-api
deploy/setup.sh path/to/r2lab.pgdump
```

This installs PostgreSQL, Python, creates the venv, restores the
database, and enables the systemd services.

After setup, review and adjust `/root/r2lab-api/.env` (see `.env.example` for reference).

## Day-to-day operations

```bash
# Service status
systemctl status r2lab-api

# Follow logs
journalctl -u r2lab-api -f

# Restart after a config change
systemctl restart r2lab-api
```

## Deploying code updates

```bash
cd /root/r2lab-api
git pull
.venv/bin/alembic upgrade head   # only if there are new migrations
systemctl restart r2lab-api
```

## Backups

A systemd timer runs `pg_dump` every hour. Dumps are saved in
`/root/r2lab-backups/r2lab.<timestamp>.pgdump`.

```bash
# Check backup timer status
systemctl status r2lab-backup.timer

# Manually trigger a backup
systemctl start r2lab-backup.service

# Restore from a backup
deploy/restore-db.sh /root/r2lab-backups/r2lab.2026-03-13-14-00-00.pgdump
systemctl restart r2lab-api
```

## Fedora / PostgreSQL major upgrade

Fedora upgrades often bump the PostgreSQL major version, which makes
the old data directory unreadable. Run these **on the VM**:

```bash
# BEFORE the Fedora upgrade — dumps the database
deploy/pg-upgrade.sh dump

# Do the Fedora upgrade (dnf system-upgrade, reboot, etc.)

# AFTER the Fedora upgrade — restores into the new PostgreSQL
deploy/pg-upgrade.sh restore
```

## Files

| File | What it does |
|---|---|
| `r2lab-api.service` | Systemd unit for the API (uvicorn on port 80) |
| `r2lab-backup.service` | Oneshot that runs pg_dump |
| `r2lab-backup.timer` | Triggers the backup every hour |
| `.env.example` | Template for production configuration |
| `setup.sh` | First-time setup script |
| `restore-db.sh` | Restore database from a pgdump file |
| `pg-upgrade.sh` | Dump/restore helper for PostgreSQL major upgrades |
