"""add forget column to registration_request

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("registration_request", sa.Column(
        "forget", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("registration_request", "forget")
