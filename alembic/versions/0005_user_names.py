"""add first_name and last_name to user

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("first_name", sa.String, nullable=True))
    op.add_column("user", sa.Column("last_name", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("user", "last_name")
    op.drop_column("user", "first_name")
