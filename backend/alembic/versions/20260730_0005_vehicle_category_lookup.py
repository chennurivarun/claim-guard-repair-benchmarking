"""Add the static vehicle category lookup and captured insurance group result.

Revision ID: 20260730_0005
Revises: 20260728_0004
Create Date: 2026-07-30
"""

import sqlalchemy as sa

from alembic import op

revision = "20260730_0005"
down_revision = "20260728_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "vehicle_category_lookup" not in inspector.get_table_names():
        op.create_table(
            "vehicle_category_lookup",
            sa.Column("make", sa.String(length=120), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("normalised_make", sa.String(length=120), nullable=False),
            sa.Column("normalised_model", sa.String(length=160), nullable=False),
            sa.Column("group_range", sa.String(length=32), nullable=False),
            sa.Column("group_category", sa.String(length=80), nullable=False),
            sa.Column("body_type", sa.String(length=80), nullable=True),
            sa.Column("fuel_type", sa.String(length=80), nullable=True),
            sa.Column("aliases_json", sa.JSON(), nullable=True),
            sa.Column("source", sa.String(length=240), nullable=False),
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "normalised_make",
                "normalised_model",
                name="uq_vehicle_category_make_model",
            ),
        )
        op.create_index(
            "ix_vehicle_category_lookup_normalised",
            "vehicle_category_lookup",
            ["normalised_make", "normalised_model"],
        )
    vehicle_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("vehicles")
    }
    for name, length in (
        ("insurance_group_range", 32),
        ("insurance_group_category", 80),
        ("insurance_group_source", 240),
        ("insurance_group_match_status", 40),
    ):
        if name not in vehicle_columns:
            op.add_column(
                "vehicles",
                sa.Column(name, sa.String(length=length), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    vehicle_columns = {
        column["name"] for column in inspector.get_columns("vehicles")
    }
    for name in (
        "insurance_group_match_status",
        "insurance_group_source",
        "insurance_group_category",
        "insurance_group_range",
    ):
        if name in vehicle_columns:
            op.drop_column("vehicles", name)
    if "vehicle_category_lookup" in inspector.get_table_names():
        indexes = {
            index["name"]
            for index in sa.inspect(bind).get_indexes("vehicle_category_lookup")
        }
        if "ix_vehicle_category_lookup_normalised" in indexes:
            op.drop_index(
                "ix_vehicle_category_lookup_normalised",
                table_name="vehicle_category_lookup",
            )
        op.drop_table("vehicle_category_lookup")
