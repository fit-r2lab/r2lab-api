from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from sqlalchemy import func

from ..auth import hash_password
from ..database import get_db
from ..dependencies import get_current_user, require_admin
from ..models.user import SSHKey, User, UserStatus
from ..schemas import SSHKeyCreate, SSHKeyRead, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _user_to_read(user: User, db: Session) -> UserRead:
    count = db.exec(
        select(func.count()).where(SSHKey.user_id == user.id)
    ).one()
    return UserRead(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_admin=user.is_admin,
        status=user.status,
        created_at=user.created_at,
        key_count=count,
    )


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    users = db.exec(select(User)).all()
    return [_user_to_read(u, db) for u in users]


@router.get("/me", response_model=UserRead)
def get_me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _user_to_read(user, db)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_read(user, db)


@router.patch("/{user_id}", response_model=UserRead,
              summary="Update a user",
              description=(
                  "Regular users can update their own profile "
                  "(password, first/last name). "
                  "Admins can update any user and change the `is_admin` flag."
              ))
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # admin can update anyone; regular user can only update self
    if not current.is_admin and current.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.first_name is not None:
        user.first_name = body.first_name
    if body.last_name is not None:
        user.last_name = body.last_name
    if body.is_admin is not None:
        if not current.is_admin:
            raise HTTPException(status_code=403,
                                detail="Only admins can change admin status")
        user.is_admin = body.is_admin
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_read(user, db)


@router.patch("/{user_id}/approve", response_model=UserRead)
def approve_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = UserStatus.approved
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_read(user, db)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()


# ---------- SSH Keys ----------

@router.get("/{user_id}/keys", response_model=list[SSHKeyRead])
def list_keys(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not current.is_admin and current.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return db.exec(select(SSHKey).where(SSHKey.user_id == user_id)).all()


@router.post("/{user_id}/keys", response_model=SSHKeyRead,
             status_code=status.HTTP_201_CREATED)
def add_key(
    user_id: int,
    body: SSHKeyCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not current.is_admin and current.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    key = SSHKey(user_id=user_id, key=body.key, comment=body.comment)
    db.add(key)
    db.commit()
    db.refresh(key)
    return key


@router.delete("/{user_id}/keys/{key_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_key(
    user_id: int,
    key_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not current.is_admin and current.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    key = db.exec(
        select(SSHKey)
        .where(SSHKey.id == key_id, SSHKey.user_id == user_id)
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    db.delete(key)
    db.commit()
