import enum
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class RegistrationStatus(str, enum.Enum):
    pending_email = "pending_email"
    pending_admin = "pending_admin"
    approved = "approved"
    rejected = "rejected"


class RegistrationRequest(SQLModel, table=True):
    __tablename__ = "registration_request"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    first_name: str
    last_name: str
    affiliation: str
    slice_name: Optional[str] = Field(default=None)
    purpose: str
    status: RegistrationStatus = Field(
        default=RegistrationStatus.pending_email)
    email_token: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    verified_at: Optional[datetime] = Field(default=None)
    decided_at: Optional[datetime] = Field(default=None)
    admin_comment: Optional[str] = Field(default=None)
