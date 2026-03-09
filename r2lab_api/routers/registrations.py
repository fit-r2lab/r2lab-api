import hashlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..database import get_db
from ..dependencies import require_admin
from ..mail import send_mail
from ..models.registration import RegistrationRequest, RegistrationStatus
from ..models.user import User
from ..schemas import RegistrationRead, RegistrationSubmit

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

    # notify admins
    admin_emails = db.exec(
        select(User.email).where(User.is_admin == True)  # noqa: E712
    ).all()
    for admin_email in admin_emails:
        send_mail(
            to=admin_email,
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
