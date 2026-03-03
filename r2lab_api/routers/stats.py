from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import extract, func
from sqlmodel import Session, select

from ..database import get_db
from ..models.lease import Lease
from ..models.slice import Slice
from ..schemas import UsageByPeriod, UsageBySlice

router = APIRouter(prefix="/stats", tags=["stats"])

ALLOWED_PERIODS = {"day", "week", "month", "quarter", "year"}


@router.get("/usage")
def usage(
    db: Session = Depends(get_db),
    t_from: datetime = Query(..., alias="from"),
    t_until: datetime = Query(..., alias="until"),
    period: str | None = Query(None),
) -> list[UsageBySlice] | list[UsageByPeriod]:
    if period is not None and period not in ALLOWED_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"period must be one of {sorted(ALLOWED_PERIODS)}",
        )

    seconds = extract("epoch", Lease.t_until) - extract("epoch", Lease.t_from)
    hours_expr = func.sum(func.ceil(seconds / 3600))

    base = (
        select(
            Slice.family,
            Slice.name.label("slice_name"),
        )
        .join(Slice, Lease.slice_id == Slice.id)
        .where(Lease.t_from >= t_from, Lease.t_until <= t_until)
    )

    if period is None:
        stmt = base.add_columns(hours_expr.label("hours")).group_by(
            Slice.family, Slice.name
        )
    else:
        period_col = func.date_trunc(period, Lease.t_from).label("period")
        stmt = base.add_columns(period_col, hours_expr.label("hours")).group_by(
            Slice.family, Slice.name, period_col
        )

    stmt = stmt.having(hours_expr > 0)
    rows = db.exec(stmt).all()

    if period is None:
        return [
            UsageBySlice(family=r.family, slice_name=r.slice_name, hours=int(r.hours))
            for r in rows
        ]
    return [
        UsageByPeriod(
            family=r.family,
            slice_name=r.slice_name,
            period=r.period,
            hours=int(r.hours),
        )
        for r in rows
    ]
