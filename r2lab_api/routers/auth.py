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
    """Exchange credentials for a bearer token.

    The returned `access_token` is a JWT (`sub`=email, `id`=internal
    user id, `aud`=audience, `exp`=expiry), signed with a server-side
    secret (HS256). It is not encrypted: any client can decode the
    payload locally without the secret — only *verifying* the
    signature requires it, which is why clients should treat the
    decoded claims as informational, not a trust boundary check.

    To inspect the claims without a JWT library:

        import base64, json
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # pad
        json.loads(base64.urlsafe_b64decode(payload_b64))
        # => {"sub": "user@example.com", "id": 42,
        #     "aud": "r2lab.inria.fr", "exp": 1234567890}

    By default the token is valid for `settings.jwt_expire_minutes`
    (1 week). Pass `duration_minutes` in the request body to request
    a shorter-lived token instead — useful for one-off checks where a
    week-long credential would needlessly outlive its purpose. Values
    above `jwt_expire_minutes` are rejected (400); the setting is a
    ceiling, not a default to raise.

    By default the token's `aud` claim is `settings.jwt_audience`
    (`"r2lab.inria.fr"`), and only tokens carrying that audience are
    accepted by this API's protected endpoints. Pass `audience` in
    the request body to mint a token scoped to a different audience
    instead — the signature (and thus the identity/claims) is still
    backed by this server, but such a token will be rejected by this
    API's own endpoints; it's meant for third-party tools that want
    to reuse R2Lab login to hand out their own scoped tokens.
    """
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
    if (body.duration_minutes is not None
            and body.duration_minutes > settings.jwt_expire_minutes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"duration_minutes cannot exceed "
                f"{settings.jwt_expire_minutes}"
            ),
        )
    # transparently upgrade legacy MD5-crypt hashes to bcrypt
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.add(user)
        db.commit()
    token = create_token(user.id, user.email, body.duration_minutes,
                         body.audience)
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
