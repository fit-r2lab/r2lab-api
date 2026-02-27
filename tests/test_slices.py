"""
Slice soft-delete tests.
"""
from datetime import datetime, timezone, timedelta

from tests.conftest import auth, _make_slice, _make_resource


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
