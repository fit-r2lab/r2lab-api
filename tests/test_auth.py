from datetime import datetime, timezone

import jwt

from r2lab_api.config import settings


def _decode(token):
    return jwt.decode(token, settings.jwt_secret,
                      algorithms=[settings.jwt_algorithm])


class TestLoginDuration:
    def test_login_default_duration(self, client, db, regular_user):
        r = client.post("/auth/login", json={
            "email": regular_user.email,
            "password": "password",
        })
        assert r.status_code == 200
        payload = _decode(r.json()["access_token"])
        ttl_minutes = (
            datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            - datetime.now(timezone.utc)
        ).total_seconds() / 60
        assert abs(ttl_minutes - settings.jwt_expire_minutes) < 1

    def test_login_with_short_duration(self, client, db, regular_user):
        r = client.post("/auth/login", json={
            "email": regular_user.email,
            "password": "password",
            "duration_minutes": 5,
        })
        assert r.status_code == 200
        payload = _decode(r.json()["access_token"])
        ttl_minutes = (
            datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            - datetime.now(timezone.utc)
        ).total_seconds() / 60
        assert abs(ttl_minutes - 5) < 1

    def test_login_duration_exceeding_max_rejected(
            self, client, db, regular_user):
        r = client.post("/auth/login", json={
            "email": regular_user.email,
            "password": "password",
            "duration_minutes": settings.jwt_expire_minutes + 1,
        })
        assert r.status_code == 400

    def test_login_duration_zero_rejected(self, client, db, regular_user):
        r = client.post("/auth/login", json={
            "email": regular_user.email,
            "password": "password",
            "duration_minutes": 0,
        })
        assert r.status_code == 422

    def test_login_duration_negative_rejected(
            self, client, db, regular_user):
        r = client.post("/auth/login", json={
            "email": regular_user.email,
            "password": "password",
            "duration_minutes": -5,
        })
        assert r.status_code == 422
