"""
Test infrastructure — SQLite in-memory, no PostgreSQL needed.

The EXCLUDE constraint (overlap prevention) is PostgreSQL-specific and
won't exist in SQLite. The app-level _check_overlap() is still tested.
"""
import os

# override settings BEFORE any app import
os.environ["R2LAB_DATABASE_URL"] = "sqlite://"
os.environ["R2LAB_JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes!"

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from r2lab_api.app import create_app
from r2lab_api.auth import create_token, hash_password
from r2lab_api.database import get_db
from r2lab_api.models.lease import Lease          # noqa: F401 — registers table
from r2lab_api.models.resource import Resource
from r2lab_api.models.slice import Slice, SliceMember
from r2lab_api.models.user import User, UserStatus, UserFamily


def _stamp_utc(instance, *_args):
    """After a row is loaded from SQLite, tag all naive datetimes as UTC."""
    for attr in vars(instance):
        if attr.startswith("_"):
            continue
        val = getattr(instance, attr, None)
        if isinstance(val, datetime) and val.tzinfo is None:
            object.__setattr__(instance, attr, val.replace(tzinfo=timezone.utc))


_utc_listeners_registered = False


@pytest.fixture(name="engine")
def engine_fixture():
    global _utc_listeners_registered
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    # patch naive datetimes from SQLite to be tz-aware (UTC)
    if not _utc_listeners_registered:
        for cls in (Lease, Slice, User, Resource, SliceMember):
            event.listen(cls, "load", _stamp_utc)
            event.listen(cls, "refresh", _stamp_utc)
        _utc_listeners_registered = True
    yield engine


@pytest.fixture(name="db")
def db_fixture(engine):
    with Session(engine) as session:
        yield session
        session.rollback()


@pytest.fixture(name="client")
def client_fixture(engine):
    app = create_app()

    def _override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------- factory helpers ----------

def _make_user(db, *, email, is_admin=False, status=UserStatus.approved):
    user = User(
        email=email,
        password_hash=hash_password("password"),
        is_admin=is_admin,
        status=status,
        family=UserFamily.admin if is_admin else UserFamily.academia_diana,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_slice(db, *, name="test-slice"):
    sl = Slice(name=name)
    db.add(sl)
    db.commit()
    db.refresh(sl)
    return sl


def _add_member(db, slice_id, user_id):
    db.add(SliceMember(slice_id=slice_id, user_id=user_id))
    db.commit()


def _make_resource(db, *, name="r2lab", granularity=600):
    r = Resource(name=name, granularity=granularity)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ---------- convenience fixtures ----------

@pytest.fixture()
def admin_user(db):
    return _make_user(db, email="admin@test.com", is_admin=True)


@pytest.fixture()
def admin_token(admin_user):
    return create_token(admin_user.email)


@pytest.fixture()
def regular_user(db):
    return _make_user(db, email="user@test.com")


@pytest.fixture()
def user_token(regular_user):
    return create_token(regular_user.email)


@pytest.fixture()
def resource(db):
    return _make_resource(db)


@pytest.fixture()
def slice_obj(db):
    return _make_slice(db)


@pytest.fixture()
def member_slice(db, slice_obj, regular_user):
    """A slice with regular_user as member."""
    _add_member(db, slice_obj.id, regular_user.id)
    return slice_obj


def auth(token):
    """Return Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}
