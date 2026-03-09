import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from ..auth import (
    create_token, hash_password, needs_rehash, verify_password,
)
from ..config import settings
from ..database import get_db
from ..mail import send_mail
from ..models.user import User, UserStatus
from ..schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


class SetPasswordRequest(BaseModel):
    token: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if user.status != UserStatus.approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account is {user.status.value}",
        )
    # transparently upgrade legacy MD5-crypt hashes to bcrypt
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.add(user)
        db.commit()
    token = create_token(user.email)
    return TokenResponse(access_token=token)


@router.post("/set-password")
def set_password(body: SetPasswordRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    user = db.exec(
        select(User).where(
            User.password_reset_token == token_hash,
            User.token_expires_at > now,
        )
    ).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    user.password_hash = hash_password(body.password)
    user.password_reset_token = None
    user.token_expires_at = None
    user.updated_at = now
    db.add(user)
    db.commit()
    return {"detail": "Password set successfully"}


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest,
                    db: Session = Depends(get_db)):
    user = db.exec(
        select(User).where(
            User.email == body.email,
            User.status == UserStatus.approved,
        )
    ).first()
    if user:
        raw_token = secrets.token_urlsafe(32)
        user.password_reset_token = hashlib.sha256(
            raw_token.encode()).hexdigest()
        user.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=48)
        db.add(user)
        db.commit()
        link = f"{settings.base_url}/set-password?token={raw_token}"
        send_mail(
            to=user.email,
            subject="R2Lab — reset your password",
            body=(
                f"Hello {user.first_name or user.email},\n\n"
                f"Click the link below to reset your password:\n\n"
                f"  {link}\n\n"
                f"This link expires in 48 hours.\n"
            ),
        )
    # always return 200 to prevent email enumeration
    return {"detail": "If that email exists, a reset link has been sent"}
