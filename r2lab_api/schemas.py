from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from .models.user import UserStatus, UserFamily


# ---------- Auth ----------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


# ---------- Users ----------

class UserRead(BaseModel):
    id: int
    email: str
    is_admin: bool
    status: UserStatus
    family: UserFamily
    created_at: datetime

class UserUpdate(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    family: Optional[UserFamily] = None


# ---------- SSH Keys ----------

class SSHKeyRead(BaseModel):
    id: int
    key: str
    comment: Optional[str]
    created_at: datetime

class SSHKeyCreate(BaseModel):
    key: str
    comment: Optional[str] = None


# ---------- Slices ----------

class SliceRead(BaseModel):
    id: int
    name: str
    created_at: datetime
    member_ids: list[int] = []

class SliceCreate(BaseModel):
    name: str

class SliceUpdate(BaseModel):
    name: Optional[str] = None


# ---------- Resources ----------

class ResourceRead(BaseModel):
    id: int
    name: str
    granularity: int


# ---------- Leases ----------

class LeaseRead(BaseModel):
    id: int
    resource_id: int
    slice_id: int
    t_from: datetime
    t_until: datetime
    created_at: datetime
    slice_name: Optional[str] = None

class LeaseCreate(BaseModel):
    resource_id: int
    slice_id: int
    t_from: datetime
    t_until: datetime

class LeaseUpdate(BaseModel):
    t_from: Optional[datetime] = None
    t_until: Optional[datetime] = None
