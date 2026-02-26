from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models.slice import Slice, SliceMember
from ..models.user import User
from ..schemas import SliceCreate, SliceRead, SliceUpdate

router = APIRouter(prefix="/slices", tags=["slices"])


def _slice_to_read(sl: Slice, db: Session) -> SliceRead:
    member_ids = [
        m.user_id
        for m in db.exec(
            select(SliceMember).where(SliceMember.slice_id == sl.id)
        ).all()
    ]
    return SliceRead(
        id=sl.id, name=sl.name,
        created_at=sl.created_at, member_ids=member_ids,
    )


@router.get("", response_model=list[SliceRead])
def list_slices(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.is_admin:
        slices = db.exec(select(Slice)).all()
    else:
        # regular users see only slices they belong to
        slices = db.exec(
            select(Slice)
            .join(SliceMember)
            .where(SliceMember.user_id == current.id)
        ).all()
    return [_slice_to_read(s, db) for s in slices]


@router.post("", response_model=SliceRead,
             status_code=status.HTTP_201_CREATED)
def create_slice(
    body: SliceCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    existing = db.exec(select(Slice).where(Slice.name == body.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail="Slice name already taken")
    sl = Slice(name=body.name)
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
    sl = db.get(Slice, slice_id)
    if not sl:
        raise HTTPException(status_code=404, detail="Slice not found")
    return _slice_to_read(sl, db)


@router.patch("/{slice_id}", response_model=SliceRead)
def update_slice(
    slice_id: int,
    body: SliceUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    sl = db.get(Slice, slice_id)
    if not sl:
        raise HTTPException(status_code=404, detail="Slice not found")
    if body.name is not None:
        sl.name = body.name
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
    sl = db.get(Slice, slice_id)
    if not sl:
        raise HTTPException(status_code=404, detail="Slice not found")
    db.delete(sl)
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
    if not db.get(Slice, slice_id):
        raise HTTPException(status_code=404, detail="Slice not found")
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
    member = db.exec(
        select(SliceMember)
        .where(SliceMember.slice_id == slice_id,
               SliceMember.user_id == user_id)
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Membership not found")
    db.delete(member)
    db.commit()
