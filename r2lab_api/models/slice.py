import enum
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class SliceFamily(str, enum.Enum):
    unknown = "unknown"
    admin = "admin"
    academia_diana = "academia/diana"
    academia_slices = "academia/slices"
    academia_others = "academia/others"
    industry = "industry"


class SliceMember(SQLModel, table=True):
    __tablename__ = "slice_member"

    slice_id: int = Field(foreign_key="slice.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)

    slice: "Slice" = Relationship(back_populates="memberships")
    user: "User" = Relationship(back_populates="slice_memberships")


class Slice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    family: SliceFamily = Field(default=SliceFamily.unknown)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: Optional[datetime] = Field(default=None)

    memberships: list[SliceMember] = Relationship(
        back_populates="slice",
        cascade_delete=True,
    )
    leases: list["Lease"] = Relationship(back_populates="slice")
