"""init

Revision ID: 0001_init
Revises: 
Create Date: 2025-02-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("place_name", sa.String(length=120), nullable=False),
        sa.Column("area_m2", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("plot_number", sa.String(length=32), nullable=False),
        sa.Column(
            "is_sold",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "place_name", "plot_number", name="uq_plots_place_plot_number"
        ),
    )
    op.create_index("ix_plots_place_name", "plots", ["place_name"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "remember_login",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=False)
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_plots_place_name", table_name="plots")
    op.drop_table("plots")
