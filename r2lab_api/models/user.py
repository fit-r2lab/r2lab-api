import enum
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class UserStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    disabled = "disabled"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)
    is_admin: bool = Field(default=False)
    status: UserStatus = Field(default=UserStatus.pending)
    password_reset_token: Optional[str] = Field(default=None)
    token_expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    ssh_keys: list["SSHKey"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    slice_memberships: list["SliceMember"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )


class SSHKey(SQLModel, table=True):
    __tablename__ = "ssh_key"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    key: str
    comment: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    user: User = Relationship(back_populates="ssh_keys")
