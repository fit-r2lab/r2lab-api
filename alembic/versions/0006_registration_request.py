"""add registration_request table

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registration_request",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("first_name", sa.String, nullable=False),
        sa.Column("last_name", sa.String, nullable=False),
        sa.Column("affiliation", sa.String, nullable=False),
        sa.Column("slice_name", sa.String, nullable=True),
        sa.Column("purpose", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False,
                  server_default="pending_email"),
        sa.Column("email_token", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_comment", sa.String, nullable=True),
    )
    op.create_index("ix_registration_request_email",
                    "registration_request", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_registration_request_email",
                  table_name="registration_request")
    op.drop_table("registration_request")
