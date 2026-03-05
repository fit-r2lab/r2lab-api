from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from ..database import get_db
from ..dependencies import get_current_user
from ..models.lease import Lease
from ..models.resource import Resource
from ..models.slice import Slice, SliceMember
from ..models.user import User
from ..schemas import LeaseCreate, LeaseRead, LeaseUpdate
from .slices import _slice_is_active, _slice_is_active_filter

router = APIRouter(prefix="/leases", tags=["leases"])


def _lease_to_read(lease: Lease, db: Session) -> LeaseRead:
    sl = db.get(Slice, lease.slice_id)
    return LeaseRead(
        id=lease.id,
        resource_id=lease.resource_id,
        slice_id=lease.slice_id,
        t_from=lease.t_from,
        t_until=lease.t_until,
        created_at=lease.created_at,
        slice_name=sl.name if sl else None,
    )


def _user_in_slice(db: Session, user: User, slice_id: int) -> bool:
    if user.is_admin:
        return True
    return db.exec(
        select(SliceMember)
        .where(SliceMember.slice_id == slice_id,
               SliceMember.user_id == user.id)
    ).first() is not None


def _validate_granularity(resource: Resource, t_from: datetime,
                          t_until: datetime):
    g = resource.granularity
    from_ts = int(t_from.timestamp())
    until_ts = int(t_until.timestamp())
    if from_ts % g != 0 or until_ts % g != 0:
        raise HTTPException(
            status_code=422,
            detail=f"Lease times must be aligned to {g}s granularity",
        )


def _check_overlap(db: Session, resource_id: int,
                    t_from: datetime, t_until: datetime,
                    exclude_id: int | None = None):
    """Application-level overlap check for better error messages.
    The DB EXCLUDE constraint is the real safety net."""
    stmt = (
        select(Lease)
        .where(
            Lease.resource_id == resource_id,
            Lease.t_from < t_until,
            Lease.t_until > t_from,
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(Lease.id != exclude_id)
    conflict = db.exec(stmt).first()
    if conflict:
        sl = db.get(Slice, conflict.slice_id)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Overlaps with lease {conflict.id}"
                f" ({sl.name if sl else '?'},"
                f" {conflict.t_from} — {conflict.t_until})"
            ),
        )


@router.get("", response_model=list[LeaseRead],
            summary="List leases (public)",
            description="No authentication required. All filters are optional and combinable.")
def list_leases(
    db: Session = Depends(get_db),
    resource_id: Optional[int] = Query(None),
    slice_id: Optional[int] = Query(None),
    alive: Optional[int] = Query(
        None, description="Unix epoch — return leases active at this time"),
    after: Optional[datetime] = Query(
        None, description="Only leases ending after this time (t_until > after)"),
    before: Optional[datetime] = Query(
        None, description="Only leases starting before this time (t_from < before)"),
):
    stmt = select(Lease)
    if resource_id is not None:
        stmt = stmt.where(Lease.resource_id == resource_id)
    if slice_id is not None:
        stmt = stmt.where(Lease.slice_id == slice_id)
    if alive is not None:
        at = datetime.fromtimestamp(alive, tz=timezone.utc)
        stmt = stmt.where(Lease.t_from <= at, Lease.t_until > at)
    if after is not None:
        stmt = stmt.where(Lease.t_until > after)
    if before is not None:
        stmt = stmt.where(Lease.t_from < before)
    stmt = stmt.order_by(Lease.t_from)
    leases = db.exec(stmt).all()
    return [_lease_to_read(l, db) for l in leases]


@router.get("/current", response_model=LeaseRead | None,
            summary="Get the currently active lease (public)",
            description="Returns `null` if no lease is active right now on the given resource.")
def get_current_lease(
    db: Session = Depends(get_db),
    resource_id: int = Query(...),
):
    now = datetime.now(timezone.utc)
    lease = db.exec(
        select(Lease)
        .where(
            Lease.resource_id == resource_id,
            Lease.t_from <= now,
            Lease.t_until > now,
        )
    ).first()
    if not lease:
        return None
    return _lease_to_read(lease, db)


@router.post("", response_model=LeaseRead,
             status_code=status.HTTP_201_CREATED,
             summary="Create a lease",
             description=(
                 "Caller must be a member of the target slice (or admin). "
                 "Times must be aligned to the resource's granularity. "
                 "Returns **409** if the new lease would overlap an existing one. "
                 "Resource and slice can be specified by id or by name."
             ))
def create_lease(
    body: LeaseCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # resolve resource by id or name
    if body.resource_id is not None and body.resource_name is not None:
        raise HTTPException(
            status_code=422,
            detail="Provide resource_id or resource_name, not both")
    if body.resource_id is not None:
        resource = db.get(Resource, body.resource_id)
    elif body.resource_name is not None:
        resource = db.exec(
            select(Resource).where(Resource.name == body.resource_name)
        ).first()
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide resource_id or resource_name")
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # resolve slice by id or name
    if body.slice_id is not None and body.slice_name is not None:
        raise HTTPException(
            status_code=422,
            detail="Provide slice_id or slice_name, not both")
    if body.slice_id is not None:
        sl = db.get(Slice, body.slice_id)
    elif body.slice_name is not None:
        sl = db.exec(
            select(Slice).where(
                Slice.name == body.slice_name,
                _slice_is_active_filter(),
            )
        ).first()
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide slice_id or slice_name")
    if not sl or not _slice_is_active(sl):
        raise HTTPException(status_code=404, detail="Slice not found")

    if not _user_in_slice(db, current, sl.id):
        raise HTTPException(status_code=403,
                            detail="You are not a member of this slice")
    if body.t_from >= body.t_until:
        raise HTTPException(status_code=422,
                            detail="t_from must be before t_until")
    _validate_granularity(resource, body.t_from, body.t_until)
    _check_overlap(db, resource.id, body.t_from, body.t_until)

    lease = Lease(
        resource_id=resource.id,
        slice_id=sl.id,
        t_from=body.t_from,
        t_until=body.t_until,
    )
    db.add(lease)
    db.commit()
    db.refresh(lease)
    return _lease_to_read(lease, db)


@router.patch("/{lease_id}", response_model=LeaseRead)
def update_lease(
    lease_id: int,
    body: LeaseUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    lease = db.get(Lease, lease_id)
    if not lease:
        raise HTTPException(status_code=404, detail="Lease not found")
    if not _user_in_slice(db, current, lease.slice_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    t_from = body.t_from if body.t_from is not None else lease.t_from
    t_until = body.t_until if body.t_until is not None else lease.t_until
    if t_from >= t_until:
        raise HTTPException(status_code=422,
                            detail="t_from must be before t_until")

    resource = db.get(Resource, lease.resource_id)
    _validate_granularity(resource, t_from, t_until)
    _check_overlap(db, lease.resource_id, t_from, t_until,
                   exclude_id=lease.id)

    lease.t_from = t_from
    lease.t_until = t_until
    db.add(lease)
    db.commit()
    db.refresh(lease)
    return _lease_to_read(lease, db)


@router.delete("/{lease_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lease(
    lease_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    lease = db.get(Lease, lease_id)
    if not lease:
        raise HTTPException(status_code=404, detail="Lease not found")
    if not _user_in_slice(db, current, lease.slice_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    db.delete(lease)
    db.commit()
