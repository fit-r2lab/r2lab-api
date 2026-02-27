"""add family column to user

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("family", sqlmodel.sql.sqltypes.AutoString,
                  nullable=False, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_column("user", "family")
