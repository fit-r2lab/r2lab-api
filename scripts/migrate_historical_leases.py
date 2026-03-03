#!/usr/bin/env python3

"""
Import historical leases from REBUILT-LEASES.csv into the r2lab-api database.

This script is designed to run AFTER migrate_from_plc.py.  It reads two CSV
files produced from the legacy R2Lab booking logs:

  - former-data/REBUILT-LEASES.csv   (lease_id, name, beg, end)
  - former-data/HAND-SLICE-FAMILY.csv (name, family, country)

For each slice that appears in the lease data but doesn't already exist in
the database, a soft-deleted slice is created with the appropriate family.
Existing slices that already have family=unknown get their family updated
from the CSV mapping.

Overlaps with existing (PLC-migrated) leases are resolved:
  - Same-slice overlaps → the REBUILT lease is skipped (PLC is authoritative).
  - Cross-slice overlaps → both leases are trimmed to meet at the midpoint
    of the overlap window, rounded down to 10-minute granularity.

Usage:
    python scripts/migrate_historical_leases.py          # actual import
    python scripts/migrate_historical_leases.py --dry-run # preview only
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from r2lab_api.database import engine
from r2lab_api.models.lease import Lease
from r2lab_api.models.resource import Resource
from r2lab_api.models.slice import Slice, SliceFamily


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

# SLICES_TO_SKIP = {"inria_r2lab.nightly", "inria_admin"}
SLICES_TO_SKIP = set()  # no more skipping

RESTORE_DATA_DIR = Path(__file__).resolve().parent

# Granularity in seconds (10 minutes) — must match resource.granularity
GRANULARITY = 600

# Extra slice→(family, country) mappings for slices present in REBUILT-LEASES.csv
# but absent from HAND-SLICE-FAMILY.csv
EXTRA_SLICES = {
    "inria_oaici": ("academia/slices", None),
    "inria_tum01": ("academia/slices", "Germany"),
    "inria_ter01": ("academia/diana", None),
    "inria_gitlabrunner": ("academia/diana", None),
    "inria_sopnode": ("academia/slices", None),
    "inria_vt1": ("academia/others", None),
    "inria_lille": ("academia/slices", None),
    "inria_tuvsud": ("industry", "Germany"),
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def utcnow():
    return datetime.now(timezone.utc)


def parse_dt(s: str) -> datetime:
    """Parse a naive datetime string from the CSV as UTC."""
    return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc)


def family_str_to_enum(family: str) -> SliceFamily:
    """Map a CSV family string to the SliceFamily enum."""
    mapping = {
        "academia/diana": SliceFamily.academia_diana,
        "academia/slices": SliceFamily.academia_slices,
        "academia/others": SliceFamily.academia_others,
        "admin": SliceFamily.admin,
        "industry": SliceFamily.industry,
    }
    return mapping.get(family, SliceFamily.unknown)


def round_down_granularity(dt: datetime) -> datetime:
    """Round a datetime down to the nearest GRANULARITY boundary."""
    ts = int(dt.timestamp())
    ts = ts - (ts % GRANULARITY)
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def overlaps(a_from, a_until, b_from, b_until):
    """True if the two time ranges overlap."""
    return a_from < b_until and b_from < a_until


# ---------------------------------------------------------------------------
# read CSV data
# ---------------------------------------------------------------------------

def read_leases_csv(path: Path) -> list[dict]:
    """Read REBUILT-LEASES.csv → list of {name, beg, end}."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            if name in SLICES_TO_SKIP:
                continue
            rows.append({
                "name": name,
                "beg": parse_dt(row["beg"]),
                "end": parse_dt(row["end"]),
            })
    return rows


def read_family_csv(path: Path) -> dict[str, tuple[str, str | None]]:
    """Read HAND-SLICE-FAMILY.csv → {slice_name: (family, country)}."""
    mapping = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = row.get("country", "").strip() or None
            mapping[row["name"].strip()] = (row["family"].strip(), country)
    # merge extra mappings
    mapping.update(EXTRA_SLICES)
    return mapping


# ---------------------------------------------------------------------------
# migration logic
# ---------------------------------------------------------------------------

def migrate(dry_run: bool = False):
    now = utcnow()

    # ---- read CSV data ----
    leases_csv = read_leases_csv(RESTORE_DATA_DIR / "REBUILT-LEASES.csv")
    family_map = read_family_csv(RESTORE_DATA_DIR / "HAND-SLICE-FAMILY.csv")

    print(f"CSV: {len(leases_csv)} leases (after skipping {SLICES_TO_SKIP})")

    # collect unique slice names from the CSV
    csv_slice_names = sorted({r["name"] for r in leases_csv})
    print(f"CSV: {len(csv_slice_names)} distinct slices")

    with Session(engine) as db:
        # ---- resource ----
        resource = db.exec(select(Resource)).first()
        if not resource:
            print("ERROR: no resource found — run bootstrap.py first",
                  file=sys.stderr)
            sys.exit(1)
        resource_id = resource.id
        print(f"Using resource '{resource.name}' (id={resource_id})")

        # ---- ensure slices exist + update families from CSV ----
        existing_slices = {}  # name → id
        for sl in db.exec(select(Slice)).all():
            existing_slices[sl.name] = sl.id

        slices_created = 0
        slices_updated = 0
        for name in csv_slice_names:
            csv_entry = family_map.get(name)
            if csv_entry is None:
                print(f"  WARNING: no family mapping for slice '{name}', "
                      f"using 'unknown'", file=sys.stderr)
                fam_str, country = "unknown", None
            else:
                fam_str, country = csv_entry
            fam_enum = family_str_to_enum(fam_str)

            if name in existing_slices:
                # CSV data is more authoritative than the PLC heuristic
                sl = db.get(Slice, existing_slices[name])
                if sl:
                    changed = False
                    if fam_enum != SliceFamily.unknown and sl.family != fam_enum:
                        sl.family = fam_enum
                        changed = True
                    if country and sl.country != country:
                        sl.country = country
                        changed = True
                    if changed:
                        if not dry_run:
                            db.add(sl)
                        slices_updated += 1
                continue

            sl = Slice(
                name=name,
                family=fam_enum,
                country=country,
                created_at=now,
                updated_at=now,
                deleted_at=now,  # soft-deleted historical slice
            )
            if dry_run:
                print(f"  [dry-run] new slice: {name} ({fam_str})")
                existing_slices[name] = -1
                slices_created += 1
                continue
            db.add(sl)
            db.flush()
            existing_slices[name] = sl.id
            slices_created += 1

        print(f"Slices: {slices_created} created, "
              f"{slices_updated} updated (family/country), "
              f"{len(csv_slice_names) - slices_created - slices_updated}"
              f" unchanged")

        # ---- load existing leases into memory for overlap detection ----
        existing_leases = db.exec(
            select(Lease).where(Lease.resource_id == resource_id)
        ).all()
        lease_by_id = {le.id: le for le in existing_leases}
        print(f"Existing leases in DB: {len(existing_leases)}")

        # ---- phase 1: filter out same-slice overlaps ----
        slice_id_to_name = {v: k for k, v in existing_slices.items()}

        existing_by_slice: dict[str, list[Lease]] = {}
        for le in existing_leases:
            sname = slice_id_to_name.get(le.slice_id, "")
            existing_by_slice.setdefault(sname, []).append(le)

        surviving = []
        same_slice_skipped = 0
        for row in leases_csv:
            name = row["name"]
            beg, end = row["beg"], row["end"]
            skip = False
            for existing in existing_by_slice.get(name, []):
                if overlaps(beg, end, existing.t_from, existing.t_until):
                    skip = True
                    break
            if skip:
                same_slice_skipped += 1
            else:
                surviving.append(row)
        print(f"Same-slice overlaps skipped: {same_slice_skipped}")
        print(f"Leases surviving same-slice filter: {len(surviving)}")

        # ---- phase 2: resolve cross-slice overlaps ----
        existing_adjustments: dict[int, tuple[datetime, datetime]] = {}
        cross_slice_adjustments = 0

        for row in surviving:
            beg, end = row["beg"], row["end"]
            for existing in existing_leases:
                if existing.id in existing_adjustments:
                    e_from, e_until = existing_adjustments[existing.id]
                else:
                    e_from, e_until = existing.t_from, existing.t_until
                if e_from >= e_until:
                    continue
                if not overlaps(beg, end, e_from, e_until):
                    continue
                overlap_start = max(beg, e_from)
                overlap_end = min(end, e_until)
                mid_ts = (overlap_start.timestamp()
                          + overlap_end.timestamp()) / 2
                mid = datetime.fromtimestamp(mid_ts, tz=timezone.utc)
                mid = round_down_granularity(mid)

                if beg <= e_from:
                    end = min(end, mid)
                    new_e_from = max(e_from, mid)
                    existing_adjustments[existing.id] = (
                        new_e_from, e_until)
                else:
                    existing_adjustments[existing.id] = (
                        e_from, min(e_until, mid))
                    beg = max(beg, mid)

                cross_slice_adjustments += 1

            row["beg"] = beg
            row["end"] = end

        print(f"Cross-slice overlap adjustments: {cross_slice_adjustments}")

        # ---- phase 3: apply adjustments to existing leases ----
        existing_trimmed = 0
        existing_dropped = 0
        for lease_id, (new_from, new_until) in existing_adjustments.items():
            le = lease_by_id[lease_id]
            if new_from >= new_until:
                if not dry_run:
                    db.delete(le)
                existing_dropped += 1
                continue
            if new_from != le.t_from or new_until != le.t_until:
                if not dry_run:
                    le.t_from = new_from
                    le.t_until = new_until
                    db.add(le)
                existing_trimmed += 1

        if existing_trimmed or existing_dropped:
            print(f"Existing leases adjusted: {existing_trimmed} trimmed, "
                  f"{existing_dropped} dropped (zero-length)")
            if not dry_run:
                db.flush()

        # ---- phase 4: insert new leases ----
        inserted = 0
        dropped = 0
        for row in surviving:
            beg, end = row["beg"], row["end"]
            if beg >= end:
                dropped += 1
                continue
            name = row["name"]
            slice_id = existing_slices.get(name)
            if slice_id is None or (not dry_run and slice_id < 0):
                print(f"  WARNING: no slice_id for '{name}', skipping",
                      file=sys.stderr)
                continue
            if dry_run:
                inserted += 1
                continue
            db.add(Lease(
                resource_id=resource_id,
                slice_id=slice_id,
                t_from=beg,
                t_until=end,
                created_at=beg,
            ))
            inserted += 1

        print(f"New leases: {inserted} inserted, "
              f"{dropped} dropped (zero-length after trimming)")

        # ---- commit or rollback ----
        if dry_run:
            print("\n[dry-run] No changes written.")
            db.rollback()
        else:
            db.commit()
            print(f"\nMigration committed successfully. "
                  f"Total new leases: {inserted}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Import historical leases from REBUILT-LEASES.csv")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be migrated without writing")
    args = parser.parse_args()

    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
