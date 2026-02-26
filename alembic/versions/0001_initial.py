"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- btree_gist extension (needed for EXCLUDE constraint) ---
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # --- user ---
    op.create_table(
        "user",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString,
                  nullable=False, unique=True, index=True),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString,
                  nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False,
                  server_default="false"),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString,
                  nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False),
    )

    # --- ssh_key ---
    op.create_table(
        "ssh_key",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("user.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("comment", sqlmodel.sql.sqltypes.AutoString,
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False),
    )

    # --- slice ---
    op.create_table(
        "slice",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString,
                  nullable=False, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False),
    )

    # --- slice_member ---
    op.create_table(
        "slice_member",
        sa.Column("slice_id", sa.Integer,
                  sa.ForeignKey("slice.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("user.id", ondelete="CASCADE"),
                  primary_key=True),
    )

    # --- resource ---
    op.create_table(
        "resource",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString,
                  nullable=False, unique=True, index=True),
        sa.Column("granularity", sa.Integer, nullable=False,
                  server_default="600"),
    )

    # --- lease ---
    op.create_table(
        "lease",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resource_id", sa.Integer,
                  sa.ForeignKey("resource.id"),
                  nullable=False, index=True),
        sa.Column("slice_id", sa.Integer,
                  sa.ForeignKey("slice.id"),
                  nullable=False, index=True),
        sa.Column("t_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("t_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False),
    )

    # --- EXCLUDE constraint: no overlapping leases per resource ---
    op.execute("""
        ALTER TABLE lease ADD CONSTRAINT no_overlap
        EXCLUDE USING gist (
            resource_id WITH =,
            tstzrange(t_from, t_until) WITH &&
        )
    """)


def downgrade() -> None:
    op.drop_table("lease")
    op.drop_table("resource")
    op.drop_table("slice_member")
    op.drop_table("slice")
    op.drop_table("ssh_key")
    op.drop_table("user")
