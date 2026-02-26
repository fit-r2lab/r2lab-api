from sqlmodel import Field, Relationship, SQLModel


class Resource(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    granularity: int = Field(default=600)  # seconds (10 min)

    leases: list["Lease"] = Relationship(back_populates="resource")
