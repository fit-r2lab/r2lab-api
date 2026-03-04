"""
Resource API tests — by-name lookup.
"""
from tests.conftest import _make_resource


class TestResourceByName:

    def test_get_by_name(self, client, db):
        res = _make_resource(db, name="r2lab")
        r = client.get("/resources/by-name/r2lab")
        assert r.status_code == 200
        assert r.json()["name"] == "r2lab"
        assert r.json()["id"] == res.id

    def test_get_by_name_not_found(self, client, db):
        r = client.get("/resources/by-name/no-such")
        assert r.status_code == 404
