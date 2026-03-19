from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator

from .models.registration import RegistrationStatus
from .models.slice import SliceFamily
from .models.user import UserStatus


# ---------- Auth ----------

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Users ----------

class UserRead(BaseModel):
    id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool
    status: UserStatus
    created_at: datetime
    key_count: int = 0

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

    @field_validator("name")
    @classmethod
    def name_must_contain_separator(cls, v: str) -> str:
        if "-" not in v and "_" not in v:
            raise ValueError("Slice name must contain a '-' or '_'")
        return v

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
    resource_id: Optional[int] = None
    resource_name: Optional[str] = None
    slice_id: Optional[int] = None
    slice_name: Optional[str] = None
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


# ---------- Registrations ----------

class RegistrationSubmit(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    affiliation: str
    slice_name: Optional[str] = None
    purpose: str

class RegistrationRead(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    affiliation: str
    slice_name: Optional[str] = None
    purpose: str
    status: RegistrationStatus
    created_at: datetime
    verified_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    admin_comment: Optional[str] = None

class RegistrationDecision(BaseModel):
    slice_name: Optional[str] = None
    comment: Optional[str] = None
