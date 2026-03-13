from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlmodel import Session, select

from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models.slice import Slice, SliceMember
from ..models.user import SSHKey, User
from ..schemas import SliceCreate, SliceRead, SliceUpdate, SSHKeyRead

router = APIRouter(prefix="/slices", tags=["slices"])


def _slice_is_active_filter():
    """SQL filter: deleted_at is NULL or in the future."""
    now = datetime.now(timezone.utc)
    return or_(Slice.deleted_at == None, Slice.deleted_at > now)  # noqa: E711


def _slice_is_active(sl: Slice) -> bool:
    """Python check: slice is active (not expired)."""
    if sl.deleted_at is None:
        return True
    now = datetime.now(timezone.utc)
    return sl.deleted_at > now


def _get_active_slice(db: Session, slice_id: int) -> Slice:
    """Return the slice if it exists and is active, else 404."""
    sl = db.get(Slice, slice_id)
    if not sl or not _slice_is_active(sl):
        raise HTTPException(status_code=404, detail="Slice not found")
    return sl


def _slice_to_read(sl: Slice, db: Session) -> SliceRead:
    member_ids = [
        m.user_id
        for m in db.exec(
            select(SliceMember).where(SliceMember.slice_id == sl.id)
        ).all()
    ]
    return SliceRead(
        id=sl.id, name=sl.name, family=sl.family,
        country=sl.country,
        created_at=sl.created_at, member_ids=member_ids,
        deleted_at=sl.deleted_at,
    )


@router.get("", response_model=list[SliceRead],
            summary="List slices visible to the current user",
            description=(
                "**Admins** see all active slices by default "
                "(pass `include_deleted=true` to also see soft-deleted ones). "
                "**Regular users** see only the active slices they are a member of. "
                "Pass `mine=true` to restrict results to the caller's own slices "
                "(useful for admins who are also slice members)."
            ))
def list_slices(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
    include_deleted: bool = Query(
        False, description="Admin only — include soft-deleted slices"),
    mine: bool = Query(
        False, description="Only return slices the caller is a member of"),
):
    if current.is_admin and not mine:
        stmt = select(Slice)
        if not include_deleted:
            stmt = stmt.where(_slice_is_active_filter())
    else:
        stmt = (
            select(Slice)
            .join(SliceMember)
            .where(SliceMember.user_id == current.id,
                   _slice_is_active_filter())
        )
    slices = db.exec(stmt).all()
    return [_slice_to_read(s, db) for s in slices]


@router.post("", response_model=SliceRead,
             status_code=status.HTTP_201_CREATED)
def create_slice(
    body: SliceCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    existing = db.exec(
        select(Slice).where(
            Slice.name == body.name,
            _slice_is_active_filter(),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Slice name already taken")
    sl = Slice(name=body.name, family=body.family, country=body.country)
    db.add(sl)
    db.commit()
    db.refresh(sl)
    return _slice_to_read(sl, db)


@router.get("/{slice_id}", response_model=SliceRead)
def get_slice(
    slice_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    sl = _get_active_slice(db, slice_id)
    return _slice_to_read(sl, db)


@router.get("/by-name/{name}", response_model=SliceRead,
            summary="Look up a slice by name (including deleted)")
def get_slice_by_name(
    name: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    sl = db.exec(
        select(Slice).where(Slice.name == name)
    ).first()
    if not sl:
        raise HTTPException(status_code=404, detail="Slice not found")
    return _slice_to_read(sl, db)


def _apply_slice_update(
    sl: Slice, body: SliceUpdate, db: Session, current: User,
) -> SliceRead:
    """Shared logic for PATCH by id and by name."""
    if not current.is_admin:
        # non-admin: must be a member
        is_member = db.exec(
            select(SliceMember)
            .where(SliceMember.slice_id == sl.id,
                   SliceMember.user_id == current.id)
        ).first() is not None
        if not is_member:
            raise HTTPException(status_code=403, detail="Forbidden")
        # non-admin can only touch deleted_at
        if body.name is not None or body.family is not None or body.country is not None:
            raise HTTPException(
                status_code=403,
                detail="Only admins can change name, family, or country")
        # deleted_at must be within the next 61 days
        if body.deleted_at is not None:
            now = datetime.now(timezone.utc)
            limit = now + timedelta(days=61)
            if body.deleted_at < now:
                raise HTTPException(
                    status_code=422,
                    detail="deleted_at must be in the future")
            if body.deleted_at > limit:
                raise HTTPException(
                    status_code=422,
                    detail="deleted_at must be within the next 61 days")

    if body.name is not None:
        sl.name = body.name
    if body.family is not None:
        sl.family = body.family
    if body.country is not None:
        sl.country = body.country
    if body.deleted_at is not None:
        sl.deleted_at = body.deleted_at
    sl.updated_at = datetime.now(timezone.utc)
    db.add(sl)
    db.commit()
    db.refresh(sl)
    return _slice_to_read(sl, db)


_PATCH_DESC = (
    "Admins can update any field. "
    "Slice members can only set `deleted_at` (expiry), "
    "and only to a date within the next 61 days."
)


@router.patch("/{slice_id}", response_model=SliceRead,
              summary="Update a slice by id", description=_PATCH_DESC)
def update_slice(
    slice_id: int,
    body: SliceUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    sl = _get_active_slice(db, slice_id)
    return _apply_slice_update(sl, body, db, current)


@router.patch("/by-name/{name}", response_model=SliceRead,
              summary="Update a slice by name", description=_PATCH_DESC)
def update_slice_by_name(
    name: str,
    body: SliceUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    sl = db.exec(
        select(Slice).where(Slice.name == name)
    ).first()
    if not sl:
        raise HTTPException(status_code=404, detail="Slice not found")
    return _apply_slice_update(sl, body, db, current)


@router.get("/by-name/{name}/keys", response_model=list[SSHKeyRead],
            summary="List all SSH keys for all members of a slice")
def list_slice_keys(
    name: str,
    db: Session = Depends(get_db),
):
    sl = db.exec(select(Slice).where(Slice.name == name)).first()
    if not sl:
        raise HTTPException(status_code=404, detail="Slice not found")
    keys = db.exec(
        select(SSHKey)
        .join(SliceMember, SliceMember.user_id == SSHKey.user_id)
        .where(SliceMember.slice_id == sl.id)
    ).all()
    return keys


@router.delete("/{slice_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Soft-delete a slice",
               description=(
                   "Marks the slice as deleted (sets `deleted_at`). "
                   "Existing leases are preserved for historical stats; "
                   "memberships are cleared."
               ))
def delete_slice(
    slice_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    sl = _get_active_slice(db, slice_id)
    # clear memberships (they serve no purpose on a deleted slice)
    for m in db.exec(
        select(SliceMember).where(SliceMember.slice_id == sl.id)
    ).all():
        db.delete(m)
    sl.deleted_at = datetime.now(timezone.utc)
    db.add(sl)
    db.commit()


# ---------- Membership ----------

@router.put("/{slice_id}/members/{user_id}",
            status_code=status.HTTP_204_NO_CONTENT)
def add_member(
    slice_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    _get_active_slice(db, slice_id)
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.exec(
        select(SliceMember)
        .where(SliceMember.slice_id == slice_id,
               SliceMember.user_id == user_id)
    ).first()
    if existing:
        return  # idempotent
    db.add(SliceMember(slice_id=slice_id, user_id=user_id))
    db.commit()


@router.delete("/{slice_id}/members/{user_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    slice_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    _get_active_slice(db, slice_id)
    member = db.exec(
        select(SliceMember)
        .where(SliceMember.slice_id == slice_id,
               SliceMember.user_id == user_id)
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Membership not found")
    db.delete(member)
    db.commit()
