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


def create_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes)
    payload = {"sub": email, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret,
                      algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> str | None:
    """Returns the email (sub) or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret,
                             algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
