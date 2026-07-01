#!/usr/bin/env python3

"""
Warn slice members that their slice is about to expire.

A slice expires at its `deleted_at` date (NULL means never-expire).
This script is meant to run once a day (see deploy/r2lab-slice-warning.timer):
every active slice whose expiry is in the future but within WARNING_DAYS days
qualifies, and each of its members is mailed a reminder to renew.

Since the job runs once a day and the window is a rolling one, each member
receives one reminder per day over the slice's final WARNING_DAYS days. No
per-slice "last warned" state is needed.

Usage:
    cd /root/r2lab-api
    .venv/bin/python scripts/warn-expiring-slices.py [--dry-run]
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# make sure r2lab_api is importable when run as a plain script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select

from r2lab_api.config import settings
from r2lab_api.database import engine
from r2lab_api.mail import send_mail
from r2lab_api.models.slice import Slice
from r2lab_api.models.user import User, UserStatus

# warn members when a slice expires within this many days
WARNING_DAYS = 4


def days_until(expiry: datetime, now: datetime) -> int:
    """Whole days between now and expiry (floored)."""
    return (expiry - now).days


def member_emails(db: Session, sl: Slice) -> list[str]:
    """Distinct emails of the slice's non-disabled members."""
    emails = []
    for m in sl.memberships:
        user = db.get(User, m.user_id)
        if user is None or user.status == UserStatus.disabled:
            continue
        if user.email not in emails:
            emails.append(user.email)
    return emails


def warning_mail(sl: Slice, days_left: int) -> tuple[str, str]:
    """Build (subject, body) for a slice that expires in `days_left` days."""
    when = "today" if days_left == 0 else (
        "tomorrow" if days_left == 1 else f"in {days_left} days")
    subject = f"[R2Lab] slice '{sl.name}' expires {when}"
    body = f"""\
Hello,

Your R2Lab slice '{sl.name}' is scheduled to expire {when}
(on {sl.deleted_at:%Y-%m-%d %H:%M} UTC).

When a slice expires it is cleaned up and its resources are released.
If you still need it, please renew it from the R2Lab portal:

    {settings.base_url}

If you no longer need this slice, you can ignore this message.

-- the R2Lab team
"""
    return subject, body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print what would be sent, without sending any mail")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=WARNING_DAYS)
    sent = 0
    warned_slices = 0

    with Session(engine) as db:
        # active slices expiring in the future but within the warning window
        slices = db.exec(
            select(Slice).where(
                Slice.deleted_at != None,  # noqa: E711
                Slice.deleted_at > now,
                Slice.deleted_at <= cutoff,
            )
        ).all()

        for sl in slices:
            days_left = days_until(sl.deleted_at, now)
            emails = member_emails(db, sl)
            if not emails:
                print(f"slice '{sl.name}' expires in {days_left}d "
                      f"but has no member to warn")
                continue

            subject, body = warning_mail(sl, days_left)
            warned_slices += 1
            for email in emails:
                if args.dry_run:
                    print(f"[dry-run] would warn {email} "
                          f"about '{sl.name}' ({days_left}d)")
                else:
                    send_mail(to=email, subject=subject, body=body)
                    print(f"warned {email} about '{sl.name}' ({days_left}d)")
                sent += 1

    verb = "would send" if args.dry_run else "sent"
    print(f"done: {verb} {sent} mail(s) for {warned_slices} slice(s)")


if __name__ == "__main__":
    main()
