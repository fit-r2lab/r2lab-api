from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from passlib.hash import md5_crypt

from .config import settings


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (used for all new passwords)."""
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a stored hash.

    Supports both bcrypt ($2b$) and legacy MD5-crypt ($1$) hashes.
    Returns a tuple-like bool — callers should also call
    needs_rehash() to transparently upgrade legacy hashes.
    """
    if hashed.startswith("$2b$") or hashed.startswith("$2a$"):
        return bcrypt.checkpw(
            plain.encode("utf-8"), hashed.encode("ascii")
        )
    if hashed.startswith("$1$"):
        return md5_crypt.verify(plain, hashed)
    return False


def needs_rehash(hashed: str) -> bool:
    """True if the hash is a legacy format that should be upgraded."""
    return hashed.startswith("$1$")


def create_token(user_id: int, email: str, duration_minutes: int | None = None,
                 audience: str | None = None) -> str:
    minutes = (
        duration_minutes if duration_minutes is not None
        else settings.jwt_expire_minutes
    )
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        "sub": email,
        "id": user_id,
        "aud": audience or settings.jwt_audience,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret,
                      algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    """Returns the decoded payload, or None if the signature/expiry is
    invalid. Does NOT enforce `aud` — callers that only trust tokens
    scoped to this API (e.g. get_current_user) must check the `aud`
    claim themselves, since third parties can request tokens carrying
    a different audience via /auth/login."""
    try:
        return jwt.decode(token, settings.jwt_secret,
                          algorithms=[settings.jwt_algorithm],
                          options={"verify_aud": False})
    except jwt.PyJWTError:
        return None
