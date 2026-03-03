from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from .models.slice import SliceFamily
from .models.user import UserStatus


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
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool
    status: UserStatus
    created_at: datetime

class UserUpdate(BaseModel):
    password: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: Optional[bool] = None


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
    family: SliceFamily
    country: Optional[str] = None
    created_at: datetime
    member_ids: list[int] = []
    deleted_at: Optional[datetime] = None

class SliceCreate(BaseModel):
    name: str
    family: SliceFamily = SliceFamily.unknown
    country: Optional[str] = None

class SliceUpdate(BaseModel):
    name: Optional[str] = None
    family: Optional[SliceFamily] = None
    country: Optional[str] = None
    deleted_at: Optional[datetime] = None


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


# ---------- Stats ----------

class UsageBySlice(BaseModel):
    family: str
    slice_name: str
    hours: int

class UsageByPeriod(BaseModel):
    family: str
    slice_name: str
    period: datetime
    hours: int
