"""add password_reset_token and token_expires_at to user

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column(
        "password_reset_token", sa.String, nullable=True))
    op.add_column("user", sa.Column(
        "token_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "token_expires_at")
    op.drop_column("user", "password_reset_token")
