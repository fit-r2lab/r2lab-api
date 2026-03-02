from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models.slice import Slice, SliceMember
from ..models.user import User
from ..schemas import SliceCreate, SliceRead, SliceUpdate

router = APIRouter(prefix="/slices", tags=["slices"])


def _get_active_slice(db: Session, slice_id: int) -> Slice:
    """Return the slice if it exists and is not soft-deleted, else 404."""
    sl = db.get(Slice, slice_id)
    if not sl or sl.deleted_at is not None:
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
        created_at=sl.created_at, member_ids=member_ids,
    )


@router.get("", response_model=list[SliceRead])
def list_slices(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.is_admin:
        slices = db.exec(
            select(Slice).where(Slice.deleted_at == None)  # noqa: E711
        ).all()
    else:
        slices = db.exec(
            select(Slice)
            .join(SliceMember)
            .where(SliceMember.user_id == current.id,
                   Slice.deleted_at == None)  # noqa: E711
        ).all()
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
            Slice.deleted_at == None,  # noqa: E711
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Slice name already taken")
    sl = Slice(name=body.name, family=body.family)
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


@router.patch("/{slice_id}", response_model=SliceRead)
def update_slice(
    slice_id: int,
    body: SliceUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    sl = _get_active_slice(db, slice_id)
    if body.name is not None:
        sl.name = body.name
    if body.family is not None:
        sl.family = body.family
    sl.updated_at = datetime.now(timezone.utc)
    db.add(sl)
    db.commit()
    db.refresh(sl)
    return _slice_to_read(sl, db)


@router.delete("/{slice_id}", status_code=status.HTTP_204_NO_CONTENT)
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
