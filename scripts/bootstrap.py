#!/usr/bin/env python3

"""
Bootstrap the r2lab-api database with:
- the default resource (r2lab.inria.fr)
- an initial admin user (prompted interactively)
"""

import getpass
import sys

from sqlmodel import Session, select

from r2lab_api.auth import hash_password
from r2lab_api.database import engine
from r2lab_api.models.resource import Resource
from r2lab_api.models.user import User, UserStatus


def create_default_resource(db: Session):
    name = "r2lab.inria.fr"
    existing = db.exec(select(Resource).where(Resource.name == name)).first()
    if existing:
        print(f"Resource '{name}' already exists (id={existing.id})")
        return
    resource = Resource(name=name, granularity=600)
    db.add(resource)
    db.commit()
    db.refresh(resource)
    print(f"Created resource '{name}' (id={resource.id}, granularity=600s)")


def create_admin_user(db: Session):
    email = input("Admin email: ").strip()
    if not email:
        print("Empty email — skipping admin creation")
        return

    existing = db.exec(select(User).where(User.email == email)).first()
    if existing:
        print(f"User '{email}' already exists (id={existing.id}, "
              f"admin={existing.is_admin})")
        return

    password = getpass.getpass("Admin password: ")
    if not password:
        print("Empty password — aborting")
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match — aborting")
        sys.exit(1)

    user = User(
        email=email,
        password_hash=hash_password(password),
        is_admin=True,
        status=UserStatus.approved,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created admin user '{email}' (id={user.id})")


def main():
    with Session(engine) as db:
        create_default_resource(db)
        create_admin_user(db)


if __name__ == "__main__":
    main()
