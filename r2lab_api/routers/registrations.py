import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import hash_password
from ..config import settings
from ..database import get_db
from ..dependencies import require_admin
from ..mail import send_mail
from ..models.registration import RegistrationRequest, RegistrationStatus
from ..models.slice import Slice, SliceMember
from ..models.user import User, UserStatus
from ..schemas import (
    RegistrationDecision, RegistrationRead, RegistrationSubmit, UserRead,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/registrations", tags=["registrations"])


class VerifyRequest(BaseModel):
    token: str


# ---- public endpoints ----

@router.post("", status_code=status.HTTP_201_CREATED)
def submit_registration(body: RegistrationSubmit,
                        db: Session = Depends(get_db)):
    # reject if email already has a pending request
    existing = db.exec(
        select(RegistrationRequest).where(
            RegistrationRequest.email == body.email,
            RegistrationRequest.status.in_([
                RegistrationStatus.pending_email,
                RegistrationStatus.pending_admin,
            ]),
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A registration request for this email is already pending",
        )
    # reject if email already has a user account
    existing_user = db.exec(
        select(User).where(User.email == body.email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    reg = RegistrationRequest(
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        affiliation=body.affiliation,
        slice_name=body.slice_name,
        purpose=body.purpose,
        status=RegistrationStatus.pending_email,
        email_token=token_hash,
    )
    db.add(reg)
    db.commit()
    db.refresh(reg)

    link = f"{settings.base_url}/verify-email?token={raw_token}"
    send_mail(
        to=body.email,
        subject="R2Lab — verify your email",
        body=(
            f"Hello {body.first_name},\n\n"
            f"Please verify your email by clicking the link below:\n\n"
            f"  {link}\n\n"
            f"If you did not request this, you can ignore this email.\n"
        ),
    )
    return {"detail": "Registration submitted — check your email to verify"}


@router.post("/verify")
def verify_email(body: VerifyRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    reg = db.exec(
        select(RegistrationRequest).where(
            RegistrationRequest.email_token == token_hash,
            RegistrationRequest.status == RegistrationStatus.pending_email,
        )
    ).first()
    if not reg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already used token",
        )
    reg.status = RegistrationStatus.pending_admin
    reg.verified_at = datetime.now(timezone.utc)
    reg.email_token = None
    db.add(reg)
    db.commit()

    # notify admin mailing list
    send_mail(
        to=settings.admin_email,
        subject="R2Lab — new registration pending review",
        body=(
            f"A new registration request from "
            f"{reg.first_name} {reg.last_name} ({reg.email}) "
            f"is awaiting admin review.\n\n"
            f"Affiliation: {reg.affiliation}\n"
            f"Purpose: {reg.purpose}\n"
        ),
    )
    return {"detail": "Email verified — your request is now pending admin review"}


# ---- admin endpoints ----

@router.get("", response_model=list[RegistrationRead])
def list_registrations(
    status_filter: RegistrationStatus | None = Query(
        None, alias="status"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    stmt = select(RegistrationRequest)
    if status_filter:
        stmt = stmt.where(RegistrationRequest.status == status_filter)
    return db.exec(stmt).all()


@router.get("/{reg_id}", response_model=RegistrationRead)
def get_registration(
    reg_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    reg = db.get(RegistrationRequest, reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    return reg


@router.delete("/{reg_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_registration(
    reg_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    reg = db.get(RegistrationRequest, reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    db.delete(reg)
    db.commit()


@router.post("/{reg_id}/approve", response_model=UserRead)
def approve_registration(
    reg_id: int,
    body: RegistrationDecision,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    reg = db.get(RegistrationRequest, reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    if reg.status != RegistrationStatus.pending_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve request with status {reg.status.value}",
        )

    now = datetime.now(timezone.utc)

    # create user with placeholder password hash (must set via token)
    user = User(
        email=reg.email,
        password_hash="!needs-setup",
        first_name=reg.first_name,
        last_name=reg.last_name,
        status=UserStatus.approved,
    )
    db.add(user)
    db.flush()  # get user.id

    # create slice + membership if slice_name provided
    slice_name = body.slice_name or reg.slice_name
    if slice_name:
        sl = Slice(name=slice_name)
        db.add(sl)
        db.flush()
        membership = SliceMember(slice_id=sl.id, user_id=user.id)
        db.add(membership)

    # generate password setup token
    raw_token = secrets.token_urlsafe(32)
    user.password_reset_token = hashlib.sha256(
        raw_token.encode()).hexdigest()
    user.token_expires_at = now + timedelta(hours=48)

    # update registration status
    reg.status = RegistrationStatus.approved
    reg.decided_at = now
    if body.comment:
        reg.admin_comment = body.comment
    db.add(reg)
    db.add(user)
    db.commit()
    db.refresh(user)

    # send password setup email
    link = f"{settings.base_url}/set-password?token={raw_token}"
    send_mail(
        to=user.email,
        subject="R2Lab — your account has been approved",
        body=(
            f"Hello {user.first_name},\n\n"
            f"Your R2Lab account has been approved! "
            f"Please set your password by clicking the link below:\n\n"
            f"  {link}\n\n"
            f"This link expires in 48 hours.\n"
        ),
    )
    return user


@router.post("/{reg_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_registration(
    reg_id: int,
    body: RegistrationDecision,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    reg = db.get(RegistrationRequest, reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    if reg.status != RegistrationStatus.pending_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject request with status {reg.status.value}",
        )

    reg.status = RegistrationStatus.rejected
    reg.decided_at = datetime.now(timezone.utc)
    if body.comment:
        reg.admin_comment = body.comment
    db.add(reg)
    db.commit()

    send_mail(
        to=reg.email,
        subject="R2Lab — registration update",
        body=(
            f"Hello {reg.first_name},\n\n"
            f"Unfortunately, your registration request for R2Lab "
            f"has not been approved.\n"
            + (f"\nReason: {body.comment}\n" if body.comment else "")
            + f"\nIf you have questions, please contact the R2Lab team.\n"
        ),
    )
