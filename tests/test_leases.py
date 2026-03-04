"""
Lease API tests — happy paths, validation, authorization, soft-delete.
"""
from datetime import datetime, timezone, timedelta

import pytest

from tests.conftest import (
    _make_user, _make_slice, _add_member, _make_resource, auth,
)


# aligned to 600s granularity
T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
T2 = T0 + timedelta(minutes=20)
T3 = T0 + timedelta(minutes=30)


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

    def test_delete_lease(
        self, client, db, admin_token, resource, slice_obj,
    ):
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        lid = r.json()["id"]
        r = client.delete(f"/leases/{lid}", headers=auth(admin_token))
        assert r.status_code == 204
        r = client.get("/leases")
        assert len(r.json()) == 0


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
