from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel


class Lease(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id", index=True)
    slice_id: int = Field(foreign_key="slice.id", index=True)
    t_from: datetime
    t_until: datetime
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc))

    resource: "Resource" = Relationship(back_populates="leases")
    slice: "Slice" = Relationship(back_populates="leases")

    # The EXCLUDE constraint for overlap prevention is added via Alembic
    # migration (requires btree_gist extension), not declaratively here.
