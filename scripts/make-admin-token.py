#!/usr/bin/env python3
"""
Generate a long-lived JWT for an admin account.

Usage:
    .venv/bin/python scripts/make-admin-token.py admin@example.com
    .venv/bin/python scripts/make-admin-token.py admin@example.com --days 3650
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jwt
from sqlmodel import Session, select

from r2lab_api.config import settings
from r2lab_api.database import engine
from r2lab_api.models.user import User

parser = argparse.ArgumentParser(description="Generate a long-lived admin JWT")
parser.add_argument("email", help="Admin email (must exist in DB)")
parser.add_argument("--days", type=int, default=3650, help="Token lifetime in days (default: 3650 ≈ 10 years)")
args = parser.parse_args()

with Session(engine) as db:
    user = db.exec(select(User).where(User.email == args.email)).first()
    if user is None:
        print(f"No such user: {args.email}", file=sys.stderr)
        sys.exit(1)
    user_id = user.id

expire = datetime.now(timezone.utc) + timedelta(days=args.days)
token = jwt.encode(
    {"sub": args.email, "id": user_id, "aud": settings.jwt_audience, "exp": expire},
    settings.jwt_secret,
    algorithm=settings.jwt_algorithm,
)

print(f"email:   {args.email}")
print(f"id:      {user_id}")
print(f"expires: {expire:%Y-%m-%d %H:%M} UTC")
print(f"token:   {token}")
