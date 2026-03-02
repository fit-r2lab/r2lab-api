#!/usr/bin/env python3

"""
Migrate data from a PlanetLab Central (PLC) PostgreSQL database
into the r2lab-api database.

Usage:
    # target DB is configured via R2LAB_DATABASE_URL (or .env)
    python scripts/migrate_from_plc.py --plc-url postgresql://pgsqluser:...@host/planetlab5

    # dry-run: print what would be migrated without writing
    python scripts/migrate_from_plc.py --plc-url ... --dry-run

Requires the r2lab-api target DB to already have its schema
(run `alembic upgrade head` first) and the default resource
(run `python scripts/bootstrap.py` first — only the resource part).

Mapping summary:
    PLC persons         → user  (passwords are NOT migrated — users must reset)
    PLC person_role     → user.is_admin  (admin/pi → True)
    PLC keys+person_key → ssh_key
    PLC slices          → slice  (is_deleted → deleted_at)
    PLC slice_person    → slice_member
    PLC leases          → lease  (all on the single r2lab resource)
"""

import argparse
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from sqlmodel import Session, select

from r2lab_api.auth import hash_password
from r2lab_api.database import engine
from r2lab_api.models.lease import Lease
from r2lab_api.models.resource import Resource
from r2lab_api.models.slice import Slice, SliceFamily, SliceMember
from r2lab_api.models.user import SSHKey, User, UserStatus


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def utcnow():
    return datetime.now(timezone.utc)


def to_utc(dt):
    """Ensure a datetime is tz-aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# read PLC data
# ---------------------------------------------------------------------------

def read_plc(plc_url: str) -> dict:
    """Read all relevant tables from the PLC database."""
    conn = psycopg2.connect(plc_url)
    conn.set_client_encoding("UTF8")
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT person_id, email, first_name, last_name,
               enabled, deleted, password,
               date_created, last_updated
        FROM persons
    """)
    persons = cur.fetchall()

    # roles per person: {person_id: set of role names}
    cur.execute("""
        SELECT pr.person_id, r.name
        FROM person_role pr
        JOIN roles r USING (role_id)
    """)
    person_roles = {}
    for row in cur.fetchall():
        person_roles.setdefault(row["person_id"], set()).add(row["name"])

    # site affiliation: {person_id: login_base of primary site}
    cur.execute("""
        SELECT ps.person_id, s.login_base
        FROM person_site ps
        JOIN sites s USING (site_id)
        WHERE ps.is_primary = true
    """)
    person_site = {row["person_id"]: row["login_base"] for row in cur.fetchall()}

    # SSH keys
    cur.execute("""
        SELECT pk.person_id, k.key_id, k.key, k.key_type
        FROM person_key pk
        JOIN keys k USING (key_id)
        WHERE k.is_blacklisted = false
          AND k.key_type = 'ssh'
    """)
    keys = cur.fetchall()

    # slices
    cur.execute("""
        SELECT slice_id, name, created, expires, is_deleted
        FROM slices
    """)
    slices = cur.fetchall()

    # slice memberships
    cur.execute("SELECT slice_id, person_id FROM slice_person")
    slice_persons = cur.fetchall()

    # leases
    cur.execute("""
        SELECT lease_id, t_from, t_until, node_id, slice_id
        FROM leases
        ORDER BY t_from
    """)
    leases = cur.fetchall()

    conn.close()

    return dict(
        persons=persons,
        person_roles=person_roles,
        person_site=person_site,
        keys=keys,
        slices=slices,
        slice_persons=slice_persons,
        leases=leases,
    )


# ---------------------------------------------------------------------------
# migration logic
# ---------------------------------------------------------------------------

def derive_status(person: dict) -> UserStatus:
    if person["deleted"]:
        return UserStatus.disabled
    if person["enabled"]:
        return UserStatus.approved
    return UserStatus.pending


def derive_family(slice_name: str) -> SliceFamily:
    """Best-effort family guess from the PLC slice name prefix."""
    name = slice_name.lower()
    if name.startswith("inria_"):
        return SliceFamily.academia_diana
    # heuristic: most PLC slices are academic
    return SliceFamily.academia_others


DISABLED_PASSWORD = hash_password("plc-migration-must-reset")


def migrate(plc_data: dict, dry_run: bool = False):
    now = utcnow()

    with Session(engine) as db:
        # --- resource ---
        resource = db.exec(select(Resource)).first()
        if not resource:
            print("ERROR: no resource found — run bootstrap.py first",
                  file=sys.stderr)
            sys.exit(1)
        print(f"Using resource '{resource.name}' (id={resource.id})")

        # --- persons → users ---
        person_id_to_user_id = {}  # PLC person_id → new user.id
        skipped_persons = 0
        for p in plc_data["persons"]:
            pid = p["person_id"]
            email = p["email"].strip().lower()
            if not email:
                skipped_persons += 1
                continue
            # check for duplicates (PLC may have multiple rows for same email)
            existing = db.exec(
                select(User).where(User.email == email)
            ).first()
            if existing:
                person_id_to_user_id[pid] = existing.id
                continue

            roles = plc_data["person_roles"].get(pid, set())
            is_admin = bool(roles & {"admin", "pi"})

            # carry over the PLC $1$ hash as-is;
            # it will be verified by passlib and transparently
            # upgraded to bcrypt on first login
            plc_pw = p["password"]
            pw_hash = plc_pw if plc_pw.startswith("$1$") else DISABLED_PASSWORD

            user = User(
                email=email,
                password_hash=pw_hash,
                is_admin=is_admin,
                status=derive_status(p),
                created_at=to_utc(p["date_created"]),
                updated_at=to_utc(p["last_updated"]),
            )
            if dry_run:
                print(f"  [dry-run] user: {email} "
                      f"admin={is_admin} status={user.status.value}")
                # use negative placeholder IDs for dry-run FK mapping
                person_id_to_user_id[pid] = -pid
                continue
            db.add(user)
            db.flush()  # get user.id without committing
            person_id_to_user_id[pid] = user.id

        print(f"Users: {len(person_id_to_user_id)} mapped, "
              f"{skipped_persons} skipped (empty email)")

        # --- SSH keys ---
        key_count = 0
        for k in plc_data["keys"]:
            uid = person_id_to_user_id.get(k["person_id"])
            if uid is None:
                continue
            if dry_run:
                key_count += 1
                continue
            # extract comment from key (last field of "ssh-rsa AAAA... comment")
            parts = k["key"].strip().split(None, 2)
            comment = parts[2] if len(parts) > 2 else None
            ssh_key = SSHKey(
                user_id=uid,
                key=k["key"].strip(),
                comment=comment,
            )
            db.add(ssh_key)
            key_count += 1
        print(f"SSH keys: {key_count}")

        # --- slices ---
        slice_id_to_new_id = {}  # PLC slice_id → new slice.id
        name_to_new_id = {}     # dedup: PLC may have several IDs per name
        for s in plc_data["slices"]:
            sid = s["slice_id"]
            name = s["name"].strip()

            # PLC can have duplicate names — reuse the first insert
            if name in name_to_new_id:
                slice_id_to_new_id[sid] = name_to_new_id[name]
                continue

            deleted_at = None
            if s["is_deleted"]:
                expires = to_utc(s["expires"])
                if expires and expires < now:
                    deleted_at = expires
                else:
                    deleted_at = now

            sl = Slice(
                name=name,
                family=derive_family(name),
                created_at=to_utc(s["created"]),
                updated_at=to_utc(s["created"]),
                deleted_at=deleted_at,
            )
            if dry_run:
                status = "DELETED" if deleted_at else "active"
                print(f"  [dry-run] slice: {name} ({status})")
                slice_id_to_new_id[sid] = -sid
                name_to_new_id[name] = -sid
                continue
            db.add(sl)
            db.flush()
            slice_id_to_new_id[sid] = sl.id
            name_to_new_id[name] = sl.id

        # catch-all slice for leases with NULL slice_id
        unknown_slice = db.exec(
            select(Slice).where(Slice.name == "unknown-slice")
        ).first()
        if not unknown_slice and not dry_run:
            unknown_slice = Slice(name="unknown-slice")
            db.add(unknown_slice)
            db.flush()
        unknown_slice_id = (
            unknown_slice.id if unknown_slice else -1
        )

        print(f"Slices: {len(slice_id_to_new_id)}")

        # --- slice memberships ---
        member_count = 0
        for sp in plc_data["slice_persons"]:
            new_sid = slice_id_to_new_id.get(sp["slice_id"])
            new_uid = person_id_to_user_id.get(sp["person_id"])
            if new_sid is None or new_uid is None:
                continue
            if dry_run:
                member_count += 1
                continue
            db.add(SliceMember(slice_id=new_sid, user_id=new_uid))
            member_count += 1
        print(f"Slice memberships: {member_count}")

        # --- leases ---
        # Collect, dedup, and resolve overlaps before inserting.
        # PLC had 37 nodes so different slices legitimately overlapped;
        # the new single-resource model forbids that (EXCLUDE constraint).
        raw_leases = []
        null_slice_count = 0
        orphan_count = 0
        for l in plc_data["leases"]:
            plc_sid = l["slice_id"]
            if plc_sid is None:
                new_sid = unknown_slice_id
                null_slice_count += 1
            else:
                new_sid = slice_id_to_new_id.get(plc_sid)
                if new_sid is None:
                    orphan_count += 1
                    continue

            t_from = to_utc(l["t_from"])
            t_until = to_utc(l["t_until"])
            if t_from >= t_until:
                continue
            raw_leases.append((new_sid, t_from, t_until))

        # 1) dedup exact duplicates (same slice + same time range)
        seen = set()
        deduped = []
        for entry in raw_leases:
            if entry not in seen:
                seen.add(entry)
                deduped.append(entry)
        dup_count = len(raw_leases) - len(deduped)

        # 2) sort by t_from so overlap resolution is deterministic
        deduped.sort(key=lambda e: e[1])

        # 3) resolve cross-slice overlaps by trimming at midpoint
        #    (rounded down to 10-min granularity)
        granularity = resource.granularity  # seconds
        adjusted = []
        overlap_count = 0
        for sid, t_from, t_until in deduped:
            for i, (a_sid, a_from, a_until) in enumerate(adjusted):
                if a_from >= a_until:
                    continue  # already zeroed out
                if t_from >= a_until or a_from >= t_until:
                    continue  # no overlap
                # overlap — trim at midpoint
                overlap_start = max(t_from, a_from)
                overlap_end = min(t_until, a_until)
                mid_ts = (overlap_start.timestamp()
                          + overlap_end.timestamp()) / 2
                mid_ts = mid_ts - (mid_ts % granularity)
                mid = datetime.fromtimestamp(mid_ts, tz=timezone.utc)
                # earlier lease gets the first half
                if a_from <= t_from:
                    adjusted[i] = (a_sid, a_from, min(a_until, mid))
                    t_from = max(t_from, mid)
                else:
                    adjusted[i] = (a_sid, max(a_from, mid), a_until)
                    t_until = min(t_until, mid)
                overlap_count += 1
            if t_from < t_until:
                adjusted.append((sid, t_from, t_until))

        # 4) insert
        lease_count = 0
        dropped = 0
        for sid, t_from, t_until in adjusted:
            if t_from >= t_until:
                dropped += 1
                continue
            if dry_run:
                lease_count += 1
                continue
            db.add(Lease(
                resource_id=resource.id,
                slice_id=sid,
                t_from=t_from,
                t_until=t_until,
                created_at=t_from,
            ))
            lease_count += 1

        print(f"Leases: {lease_count} inserted "
              f"({dup_count} exact dups removed, "
              f"{overlap_count} overlaps trimmed, "
              f"{dropped} zeroed out, "
              f"{null_slice_count} NULL→'unknown-slice', "
              f"{orphan_count} orphaned)")

        # --- commit ---
        if dry_run:
            print("\n[dry-run] No changes written.")
            db.rollback()
        else:
            db.commit()
            print("\nMigration committed successfully.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Migrate PLC database to r2lab-api")
    parser.add_argument(
        "--plc-url",
        default="postgresql://localhost/planetlab5",  # sanity check for missing URL
        help="PostgreSQL connection URL for the PLC database")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be migrated without writing")
    args = parser.parse_args()

    print("Reading PLC database...")
    plc_data = read_plc(args.plc_url)
    print(f"  {len(plc_data['persons'])} persons, "
          f"{len(plc_data['keys'])} keys, "
          f"{len(plc_data['slices'])} slices, "
          f"{len(plc_data['leases'])} leases")

    print("\nMigrating...")
    migrate(plc_data, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
