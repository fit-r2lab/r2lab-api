"""
Stats usage endpoint tests.
"""
from datetime import datetime, timedelta, timezone

from r2lab_api.models.lease import Lease
from r2lab_api.models.slice import SliceFamily

from tests.conftest import _make_resource, _make_slice


# ---------- Helpers ----------

def _add_lease(db, resource_id, slice_id, t_from, t_until):
    lease = Lease(
        resource_id=resource_id,
        slice_id=slice_id,
        t_from=t_from,
        t_until=t_until,
    )
    db.add(lease)
    db.commit()
    return lease


# ---------- Time constants ----------

JAN = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
FEB = datetime(2025, 2, 15, 10, 0, tzinfo=timezone.utc)
MAR = datetime(2025, 3, 15, 10, 0, tzinfo=timezone.utc)
WIDE_FROM = datetime(2024, 1, 1, tzinfo=timezone.utc)
WIDE_UNTIL = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------- Per-slice totals (no period) ----------

class TestUsageBySlice:

    def test_empty(self, client, db):
        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
        })
        assert r.status_code == 200
        assert r.json() == []

    def test_single_lease(self, client, db):
        res = _make_resource(db)
        sl = _make_slice(db, name="sl-one", family=SliceFamily.industry)
        # 2-hour lease
        _add_lease(db, res.id, sl.id, JAN, JAN + timedelta(hours=2))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["family"] == "industry"
        assert data[0]["slice_name"] == "sl-one"
        assert data[0]["hours"] == 2

    def test_aggregates_multiple_leases(self, client, db):
        """Two leases from the same slice sum their hours."""
        res = _make_resource(db)
        sl = _make_slice(db, name="multi", family=SliceFamily.academia_diana)
        _add_lease(db, res.id, sl.id, JAN, JAN + timedelta(hours=3))
        _add_lease(db, res.id, sl.id, FEB, FEB + timedelta(hours=5))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
        })
        data = r.json()
        assert len(data) == 1
        assert data[0]["hours"] == 8

    def test_multiple_slices_and_families(self, client, db):
        res = _make_resource(db)
        sl_a = _make_slice(db, name="alpha", family=SliceFamily.industry)
        sl_b = _make_slice(db, name="beta", family=SliceFamily.academia_diana)
        _add_lease(db, res.id, sl_a.id, JAN, JAN + timedelta(hours=4))
        _add_lease(db, res.id, sl_b.id, FEB, FEB + timedelta(hours=6))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
        })
        data = sorted(r.json(), key=lambda d: d["slice_name"])
        assert len(data) == 2
        assert data[0]["slice_name"] == "alpha"
        assert data[0]["family"] == "industry"
        assert data[0]["hours"] == 4
        assert data[1]["slice_name"] == "beta"
        assert data[1]["family"] == "academia/diana"
        assert data[1]["hours"] == 6

    def test_date_range_filters(self, client, db):
        """Only leases fully within [from, until) are counted."""
        res = _make_resource(db)
        sl = _make_slice(db, name="filtered")
        # Lease in January
        _add_lease(db, res.id, sl.id, JAN, JAN + timedelta(hours=1))
        # Lease in March
        _add_lease(db, res.id, sl.id, MAR, MAR + timedelta(hours=1))

        # Query only February → neither lease matches
        r = client.get("/stats/usage", params={
            "from": datetime(2025, 2, 1, tzinfo=timezone.utc).isoformat(),
            "until": datetime(2025, 3, 1, tzinfo=timezone.utc).isoformat(),
        })
        assert r.json() == []

        # Query Jan–Feb → only January lease
        r = client.get("/stats/usage", params={
            "from": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
            "until": datetime(2025, 2, 1, tzinfo=timezone.utc).isoformat(),
        })
        data = r.json()
        assert len(data) == 1
        assert data[0]["hours"] == 1

    def test_ceil_rounds_up(self, client, db):
        """A 10-min lease → ceil(600/3600) = ceil(0.167) = 1 hour."""
        res = _make_resource(db)
        sl = _make_slice(db, name="short")
        _add_lease(db, res.id, sl.id, JAN, JAN + timedelta(minutes=10))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
        })
        data = r.json()
        assert len(data) == 1
        assert data[0]["hours"] == 1


# ---------- Per-period breakdown ----------

class TestUsageByPeriod:

    def test_monthly_breakdown(self, client, db):
        res = _make_resource(db)
        sl = _make_slice(db, name="monthly", family=SliceFamily.industry)
        _add_lease(db, res.id, sl.id, JAN, JAN + timedelta(hours=2))
        _add_lease(db, res.id, sl.id, FEB, FEB + timedelta(hours=3))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
            "period": "month",
        })
        data = sorted(r.json(), key=lambda d: d["period"])
        assert len(data) == 2
        assert data[0]["hours"] == 2
        assert data[1]["hours"] == 3
        # Each row should have a period field
        assert "period" in data[0]
        assert "period" in data[1]

    def test_yearly_breakdown(self, client, db):
        res = _make_resource(db)
        sl = _make_slice(db, name="yearly", family=SliceFamily.admin)
        t_2024 = datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)
        t_2025 = datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)
        _add_lease(db, res.id, sl.id, t_2024, t_2024 + timedelta(hours=10))
        _add_lease(db, res.id, sl.id, t_2025, t_2025 + timedelta(hours=20))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
            "period": "year",
        })
        data = sorted(r.json(), key=lambda d: d["period"])
        assert len(data) == 2
        assert data[0]["hours"] == 10
        assert data[1]["hours"] == 20

    def test_same_month_leases_grouped(self, client, db):
        """Two leases in the same month produce one row."""
        res = _make_resource(db)
        sl = _make_slice(db, name="grouped")
        t1 = datetime(2025, 1, 5, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 20, 10, 0, tzinfo=timezone.utc)
        _add_lease(db, res.id, sl.id, t1, t1 + timedelta(hours=3))
        _add_lease(db, res.id, sl.id, t2, t2 + timedelta(hours=4))

        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
            "period": "month",
        })
        data = r.json()
        assert len(data) == 1
        assert data[0]["hours"] == 7


# ---------- Validation ----------

class TestUsageValidation:

    def test_invalid_period(self, client, db):
        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
            "period": "century",
        })
        assert r.status_code == 422

    def test_missing_from(self, client, db):
        r = client.get("/stats/usage", params={
            "until": WIDE_UNTIL.isoformat(),
        })
        assert r.status_code == 422

    def test_missing_until(self, client, db):
        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
        })
        assert r.status_code == 422

    def test_no_auth_required(self, client, db):
        """Endpoint works without authentication."""
        r = client.get("/stats/usage", params={
            "from": WIDE_FROM.isoformat(),
            "until": WIDE_UNTIL.isoformat(),
        })
        assert r.status_code == 200
