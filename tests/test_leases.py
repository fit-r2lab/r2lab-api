"""
Lease API tests — happy paths, validation, authorization, soft-delete.
"""
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import (
    _make_user, _make_slice, _add_member, _make_resource, auth,
)


# aligned to 600s granularity
T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
T2 = T0 + timedelta(minutes=20)
T3 = T0 + timedelta(minutes=30)

# future times for delete tests
F0 = datetime(2099, 1, 1, 10, 0, tzinfo=timezone.utc)
F1 = F0 + timedelta(minutes=10)
F2 = F0 + timedelta(minutes=20)


# ---------- Happy paths ----------

class TestLeaseHappyPaths:

    def test_create_lease(self, client, db, admin_token, resource, slice_obj):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201
        data = r.json()
        assert data["slice_name"] == slice_obj.name
        assert data["resource_id"] == resource.id

    def test_list_leases(self, client, db, admin_token, resource, slice_obj):
        client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        r = client.get("/leases")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_filter_by_resource_id(
        self, client, db, admin_token, resource, slice_obj,
    ):
        client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        r = client.get("/leases", params={"resource_id": resource.id})
        assert len(r.json()) == 1
        r = client.get("/leases", params={"resource_id": 9999})
        assert len(r.json()) == 0

    def test_filter_by_slice_id(
        self, client, db, admin_token, resource, slice_obj,
    ):
        client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        r = client.get("/leases", params={"slice_id": slice_obj.id})
        assert len(r.json()) == 1
        r = client.get("/leases", params={"slice_id": 9999})
        assert len(r.json()) == 0

    def test_filter_alive(
        self, client, db, admin_token, resource, slice_obj,
    ):
        client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        alive_ts = int(T0.timestamp()) + 300  # midpoint
        r = client.get("/leases", params={"alive": alive_ts})
        assert len(r.json()) == 1
        before_ts = int(T0.timestamp()) - 300  # before
        r = client.get("/leases", params={"alive": before_ts})
        assert len(r.json()) == 0

    def test_filter_after_before(
        self, client, db, admin_token, resource, slice_obj,
    ):
        client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        # after=T0 → t_until > T0 → yes
        r = client.get("/leases", params={"after": T0.isoformat()})
        assert len(r.json()) == 1
        # after=T1 → t_until > T1 → no
        r = client.get("/leases", params={"after": T1.isoformat()})
        assert len(r.json()) == 0
        # before=T1 → t_from < T1 → yes
        r = client.get("/leases", params={"before": T1.isoformat()})
        assert len(r.json()) == 1
        # before=T0 → t_from < T0 → no
        r = client.get("/leases", params={"before": T0.isoformat()})
        assert len(r.json()) == 0

    def test_update_lease(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        r = client.patch(f"/leases/{lid}", json={
            "t_until": T2.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 200
        assert r.json()["t_until"] == T2.isoformat().replace("+00:00", "Z")

    def test_delete_future_lease(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """A fully future lease is hard-deleted."""
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": F0.isoformat(),
            "t_until": F1.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        r = client.delete(f"/leases/{lid}", headers=auth(admin_token))
        assert r.status_code == 204
        r = client.get("/leases")
        assert len(r.json()) == 0

    def test_delete_past_lease_refused(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """A fully past lease cannot be deleted."""
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        r = client.delete(f"/leases/{lid}", headers=auth(admin_token))
        assert r.status_code == 409
        # lease is still there
        r = client.get("/leases")
        assert len(r.json()) == 1

    def test_delete_in_progress_shrinks(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """An in-progress lease is shrunk to the latest grain boundary."""
        # lease from F0 to F0+2h; we freeze "now" at F0+37min
        t_from = F0
        t_until = F0 + timedelta(hours=2)
        fake_now = F0 + timedelta(minutes=37)
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": t_from.isoformat(),
            "t_until": t_until.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        with patch("r2lab_api.routers.leases.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromtimestamp = datetime.fromtimestamp
            r = client.delete(f"/leases/{lid}", headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert data["t_from"] == t_from.isoformat().replace("+00:00", "Z")
        # floor(F0+37min, 10min) = F0+30min
        expected_until = F0 + timedelta(minutes=30)
        assert data["t_until"] == expected_until.isoformat().replace(
            "+00:00", "Z")

    def test_delete_in_progress_keeps_one_grain(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """If shrinking would collapse the lease, keep exactly one grain."""
        t_from = F0
        t_until = F0 + timedelta(hours=1)
        # now is 7 minutes after t_from; floor(now) == t_from
        fake_now = F0 + timedelta(minutes=7)
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": t_from.isoformat(),
            "t_until": t_until.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        with patch("r2lab_api.routers.leases.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromtimestamp = datetime.fromtimestamp
            r = client.delete(f"/leases/{lid}", headers=auth(admin_token))
        assert r.status_code == 200
        data = r.json()
        # kept exactly one grain: [F0, F0+10min)
        expected_until = F0 + timedelta(minutes=10)
        assert data["t_until"] == expected_until.isoformat().replace(
            "+00:00", "Z")


# ---------- Validation ----------

class TestLeaseValidation:

    def test_reject_from_after_until(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T1.isoformat(),
            "t_until": T0.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422

    def test_reject_from_equals_until(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T0.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422

    def test_reject_unaligned_times(
        self, client, db, admin_token, resource, slice_obj,
    ):
        unaligned = T0 + timedelta(seconds=123)
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": unaligned.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422

    def test_reject_overlapping_leases(
        self, client, db, admin_token, resource, slice_obj,
    ):
        client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T2.isoformat(),
        }, headers=auth(admin_token))
        # overlapping
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T1.isoformat(),
            "t_until": T3.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 409

    def test_allow_adjacent_leases(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r1 = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r1.status_code == 201
        # adjacent: t_from == previous t_until
        r2 = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T1.isoformat(),
            "t_until": T2.isoformat(),
        }, headers=auth(admin_token))
        assert r2.status_code == 201


# ---------- Authorization ----------

class TestLeaseAuthorization:

    def test_non_member_cannot_create(
        self, client, db, user_token, resource, slice_obj,
    ):
        """regular_user is not a member of slice_obj."""
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(user_token))
        assert r.status_code == 403

    def test_member_can_create(
        self, client, db, user_token, regular_user,
        resource, member_slice,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": member_slice.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(user_token))
        assert r.status_code == 201

    def test_admin_can_create_for_any_slice(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201

    def test_non_member_cannot_update(
        self, client, db, admin_token, user_token,
        resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        r = client.patch(f"/leases/{lid}", json={
            "t_until": T2.isoformat(),
        }, headers=auth(user_token))
        assert r.status_code == 403

    def test_non_member_cannot_delete(
        self, client, db, admin_token, user_token,
        resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        r = client.delete(f"/leases/{lid}", headers=auth(user_token))
        assert r.status_code == 403


# ---------- Soft-delete interaction ----------

class TestLeaseSoftDelete:

    def test_lease_visible_after_slice_soft_delete(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201
        # soft-delete the slice
        r = client.delete(
            f"/slices/{slice_obj.id}", headers=auth(admin_token))
        assert r.status_code == 204
        # lease is still visible
        r = client.get("/leases")
        assert len(r.json()) == 1

    def test_lease_shows_slice_name_after_soft_delete(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        original_name = slice_obj.name
        # soft-delete
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        # lease still shows the slice name
        r = client.get("/leases")
        assert r.json()[0]["slice_name"] == original_name

    def test_cannot_create_lease_for_soft_deleted_slice(
        self, client, db, admin_token, resource, slice_obj,
    ):
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 404


# ---------- Create by name ----------

class TestLeaseCreateByName:

    def test_create_by_resource_and_slice_name(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_name": resource.name,
            "slice_name": slice_obj.name,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201
        assert r.json()["slice_name"] == slice_obj.name

    def test_create_mix_id_and_name(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """resource by id, slice by name — should work."""
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_name": slice_obj.name,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201

    def test_reject_both_id_and_name_for_resource(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "resource_name": resource.name,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422
        assert "not both" in r.json()["detail"]

    def test_reject_both_id_and_name_for_slice(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "slice_name": slice_obj.name,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422
        assert "not both" in r.json()["detail"]

    def test_reject_neither_id_nor_name_for_resource(
        self, client, db, admin_token, slice_obj,
    ):
        r = client.post("/leases", json={
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422

    def test_reject_neither_id_nor_name_for_slice(
        self, client, db, admin_token, resource,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 422

    def test_unknown_resource_name(
        self, client, db, admin_token, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_name": "no-such-resource",
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 404

    def test_unknown_slice_name(
        self, client, db, admin_token, resource,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_name": "no-such-slice",
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 404

    def test_deleted_slice_name_not_resolved(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """A soft-deleted slice should not be found by name."""
        client.delete(
            f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.post("/leases", json={
            "resource_name": resource.name,
            "slice_name": slice_obj.name,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 404


# ---------- after/before shortcuts ----------

class TestAfterBeforeShortcuts:
    """Tests for 'now', 'today', and invalid values in after/before params."""

    def _create_lease(self, client, admin_token, resource, slice_obj,
                      t_from, t_until):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": t_from.isoformat(),
            "t_until": t_until.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201
        return r.json()

    def test_after_today(self, client, db, admin_token, resource, slice_obj):
        """after=today returns leases whose t_until > start of today."""
        # past lease — should be excluded
        self._create_lease(client, admin_token, resource, slice_obj, T0, T1)
        # future lease — should be included
        self._create_lease(client, admin_token, resource, slice_obj, F0, F1)
        r = client.get("/leases", params={"after": "today"})
        assert r.status_code == 200
        leases = r.json()
        assert len(leases) == 1
        assert leases[0]["t_from"] == F0.isoformat().replace("+00:00", "Z")

    def test_after_now(self, client, db, admin_token, resource, slice_obj):
        """after=now returns leases whose t_until > current time."""
        self._create_lease(client, admin_token, resource, slice_obj, T0, T1)
        self._create_lease(client, admin_token, resource, slice_obj, F0, F1)
        r = client.get("/leases", params={"after": "now"})
        assert r.status_code == 200
        leases = r.json()
        assert len(leases) == 1
        assert leases[0]["t_from"] == F0.isoformat().replace("+00:00", "Z")

    def test_before_today(self, client, db, admin_token, resource, slice_obj):
        """before=today returns leases whose t_from < start of today."""
        self._create_lease(client, admin_token, resource, slice_obj, T0, T1)
        self._create_lease(client, admin_token, resource, slice_obj, F0, F1)
        r = client.get("/leases", params={"before": "today"})
        assert r.status_code == 200
        leases = r.json()
        assert len(leases) == 1
        assert leases[0]["t_from"] == T0.isoformat().replace("+00:00", "Z")

    def test_today_and_tomorrow(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """after=today&before=tomorrow shows only leases happening today."""
        from datetime import date as _date
        today = _date.today()
        # lease today (10:00–10:10 today, grain-aligned)
        t_today_from = datetime(
            today.year, today.month, today.day, 10, 0, tzinfo=timezone.utc)
        t_today_until = t_today_from + timedelta(minutes=10)
        self._create_lease(
            client, admin_token, resource, slice_obj,
            t_today_from, t_today_until)
        # lease in the past
        self._create_lease(
            client, admin_token, resource, slice_obj, T0, T1)
        # lease far in the future
        self._create_lease(
            client, admin_token, resource, slice_obj, F0, F1)
        r = client.get("/leases", params={
            "after": "today", "before": "tomorrow"})
        assert r.status_code == 200
        leases = r.json()
        assert len(leases) == 1
        assert leases[0]["t_from"] == t_today_from.isoformat().replace(
            "+00:00", "Z")

    def test_after_invalid(self, client):
        r = client.get("/leases", params={"after": "banana"})
        assert r.status_code == 422

    def test_after_iso_still_works(
        self, client, db, admin_token, resource, slice_obj,
    ):
        """Plain ISO datetimes still work as before."""
        self._create_lease(client, admin_token, resource, slice_obj, T0, T1)
        self._create_lease(client, admin_token, resource, slice_obj, F0, F1)
        r = client.get("/leases", params={"after": T1.isoformat()})
        assert r.status_code == 200
        assert len(r.json()) == 1


# ---------- _local_midnight timezone handling ----------

class TestLocalMidnight:
    """Test that _local_midnight interprets dates in local time."""

    PARIS = ZoneInfo("Europe/Paris")

    def test_winter_dec31(self):
        """FR Dec 31 midnight = UTC Dec 30 23:00 (CET = UTC+1)."""
        from r2lab_api.routers.leases import _local_midnight
        result = _local_midnight(date(2025, 12, 31), tz=self.PARIS)
        assert result == datetime(2025, 12, 30, 23, 0, tzinfo=timezone.utc)

    def test_winter_jan1(self):
        """FR Jan 1 midnight = UTC Dec 31 23:00 (CET = UTC+1)."""
        from r2lab_api.routers.leases import _local_midnight
        result = _local_midnight(date(2026, 1, 1), tz=self.PARIS)
        assert result == datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)

    def test_summer(self):
        """FR Jul 15 midnight = UTC Jul 14 22:00 (CEST = UTC+2)."""
        from r2lab_api.routers.leases import _local_midnight
        result = _local_midnight(date(2026, 7, 15), tz=self.PARIS)
        assert result == datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)
