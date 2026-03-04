"""
Slice tests — soft-delete, deleted_at via PATCH, by-name lookup, authorization.
"""
from datetime import datetime, timezone, timedelta

from r2lab_api.models.slice import SliceFamily

from tests.conftest import auth, _make_slice, _add_member, _make_resource


T0 = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)


class TestSliceSoftDelete:

    def test_delete_returns_204(self, client, db, admin_token, slice_obj):
        r = client.delete(
            f"/slices/{slice_obj.id}", headers=auth(admin_token))
        assert r.status_code == 204

    def test_get_returns_404_after_delete(
        self, client, db, admin_token, slice_obj,
    ):
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.get(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        assert r.status_code == 404

    def test_list_excludes_deleted(
        self, client, db, admin_token, slice_obj,
    ):
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.get("/slices", headers=auth(admin_token))
        ids = [s["id"] for s in r.json()]
        assert slice_obj.id not in ids

    def test_name_reusable_after_soft_delete(
        self, client, db, admin_token, slice_obj,
    ):
        name = slice_obj.name
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.post(
            "/slices", json={"name": name}, headers=auth(admin_token))
        assert r.status_code == 201
        assert r.json()["name"] == name

    def test_update_returns_404_after_delete(
        self, client, db, admin_token, slice_obj,
    ):
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.patch(
            f"/slices/{slice_obj.id}",
            json={"name": "new-name"},
            headers=auth(admin_token),
        )
        assert r.status_code == 404

    def test_add_member_returns_404_after_delete(
        self, client, db, admin_token, admin_user, slice_obj,
    ):
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        r = client.put(
            f"/slices/{slice_obj.id}/members/{admin_user.id}",
            headers=auth(admin_token),
        )
        assert r.status_code == 404

    def test_leases_survive_slice_soft_delete(
        self, client, db, admin_token, slice_obj,
    ):
        resource = _make_resource(db)
        r = client.post("/leases", json={
            "resource_id": resource.id,
            "slice_id": slice_obj.id,
            "t_from": T0.isoformat(),
            "t_until": T1.isoformat(),
        }, headers=auth(admin_token))
        assert r.status_code == 201
        lease_id = r.json()["id"]
        # soft-delete the slice
        client.delete(f"/slices/{slice_obj.id}", headers=auth(admin_token))
        # leases still exist
        r = client.get("/leases")
        lease_ids = [l["id"] for l in r.json()]
        assert lease_id in lease_ids


# ---------- PATCH deleted_at ----------

class TestSlicePatchDeletedAt:

    def test_admin_can_set_deleted_at(
        self, client, db, admin_token, slice_obj,
    ):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        r = client.patch(
            f"/slices/{slice_obj.id}",
            json={"deleted_at": future},
            headers=auth(admin_token),
        )
        assert r.status_code == 200
        assert r.json()["deleted_at"] is not None

    def test_admin_can_set_deleted_at_far_future(
        self, client, db, admin_token, slice_obj,
    ):
        """Admins have no 61-day restriction."""
        far = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        r = client.patch(
            f"/slices/{slice_obj.id}",
            json={"deleted_at": far},
            headers=auth(admin_token),
        )
        assert r.status_code == 200

    def test_member_can_set_deleted_at_within_61_days(
        self, client, db, user_token, regular_user, member_slice,
    ):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        r = client.patch(
            f"/slices/{member_slice.id}",
            json={"deleted_at": future},
            headers=auth(user_token),
        )
        assert r.status_code == 200
        assert r.json()["deleted_at"] is not None

    def test_member_rejected_deleted_at_beyond_61_days(
        self, client, db, user_token, regular_user, member_slice,
    ):
        too_far = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        r = client.patch(
            f"/slices/{member_slice.id}",
            json={"deleted_at": too_far},
            headers=auth(user_token),
        )
        assert r.status_code == 422
        assert "61 days" in r.json()["detail"]

    def test_member_rejected_deleted_at_in_past(
        self, client, db, user_token, regular_user, member_slice,
    ):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        r = client.patch(
            f"/slices/{member_slice.id}",
            json={"deleted_at": past},
            headers=auth(user_token),
        )
        assert r.status_code == 422
        assert "future" in r.json()["detail"]

    def test_member_cannot_change_name(
        self, client, db, user_token, regular_user, member_slice,
    ):
        r = client.patch(
            f"/slices/{member_slice.id}",
            json={"name": "hacked"},
            headers=auth(user_token),
        )
        assert r.status_code == 403

    def test_member_cannot_change_family(
        self, client, db, user_token, regular_user, member_slice,
    ):
        r = client.patch(
            f"/slices/{member_slice.id}",
            json={"family": "industry"},
            headers=auth(user_token),
        )
        assert r.status_code == 403

    def test_non_member_cannot_patch(
        self, client, db, user_token, slice_obj,
    ):
        """regular_user is not a member of slice_obj."""
        future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        r = client.patch(
            f"/slices/{slice_obj.id}",
            json={"deleted_at": future},
            headers=auth(user_token),
        )
        assert r.status_code == 403


# ---------- By-name lookup ----------

class TestSliceByName:

    def test_get_by_name(self, client, db, admin_token):
        sl = _make_slice(db, name="lookup-me", family=SliceFamily.industry)
        r = client.get(
            "/slices/by-name/lookup-me", headers=auth(admin_token))
        assert r.status_code == 200
        assert r.json()["name"] == "lookup-me"
        assert r.json()["family"] == "industry"

    def test_get_by_name_not_found(self, client, db, admin_token):
        r = client.get(
            "/slices/by-name/no-such-slice", headers=auth(admin_token))
        assert r.status_code == 404

    def test_get_by_name_ignores_deleted(self, client, db, admin_token):
        sl = _make_slice(db, name="gone-slice")
        client.delete(f"/slices/{sl.id}", headers=auth(admin_token))
        r = client.get(
            "/slices/by-name/gone-slice", headers=auth(admin_token))
        assert r.status_code == 404


# ---------- PATCH by name ----------

class TestSlicePatchByName:

    def test_admin_patch_by_name(self, client, db, admin_token):
        _make_slice(db, name="named-slice")
        r = client.patch(
            "/slices/by-name/named-slice",
            json={"family": "industry"},
            headers=auth(admin_token),
        )
        assert r.status_code == 200
        assert r.json()["family"] == "industry"

    def test_member_renew_by_name(
        self, client, db, user_token, regular_user,
    ):
        sl = _make_slice(db, name="renew-me")
        _add_member(db, sl.id, regular_user.id)
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        r = client.patch(
            "/slices/by-name/renew-me",
            json={"deleted_at": future},
            headers=auth(user_token),
        )
        assert r.status_code == 200
        assert r.json()["deleted_at"] is not None

    def test_member_renew_by_name_rejected_too_far(
        self, client, db, user_token, regular_user,
    ):
        sl = _make_slice(db, name="too-far")
        _add_member(db, sl.id, regular_user.id)
        too_far = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        r = client.patch(
            "/slices/by-name/too-far",
            json={"deleted_at": too_far},
            headers=auth(user_token),
        )
        assert r.status_code == 422

    def test_patch_by_name_not_found(self, client, db, admin_token):
        r = client.patch(
            "/slices/by-name/nope",
            json={"family": "industry"},
            headers=auth(admin_token),
        )
        assert r.status_code == 404
