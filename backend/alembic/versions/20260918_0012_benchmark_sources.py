"""Add per-source mapping approval and the AI vehicle-category cache.

Revision ID: 20260918_0012
Revises: 20260917_0011
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "20260918_0012"
down_revision = "20260917_0011"
branch_labels = None
depends_on = None

_TABLE = "vehicle_category_inferences"


def upgrade() -> None:
    # Clean databases are built straight from SQLAlchemy metadata by
    # init_db.initialize_database, so every step inspects before it acts and is
    # a no-op on a database that already has the column or table.
    inspector = sa.inspect(op.get_bind())
    if "mapping_group_approvals_json" not in {
        column["name"] for column in inspector.get_columns("cases")
    }:
        # Nullable, no default: "no source has been approved" is the honest
        # state of every existing case.  The case-level approval columns from
        # 20260917_0011 are left exactly as they are.
        op.add_column("cases", sa.Column("mapping_group_approvals_json", sa.JSON(), nullable=True))
    if _TABLE not in inspector.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("make", sa.String(length=120), nullable=False),
            sa.Column("model", sa.String(length=160), nullable=False),
            sa.Column("normalised_make", sa.String(length=120), nullable=False),
            sa.Column("normalised_model", sa.String(length=160), nullable=False),
            sa.Column("category", sa.String(length=80), nullable=True),
            sa.Column("provider", sa.String(length=80), nullable=False),
            sa.Column("model_id", sa.String(length=160), nullable=False),
            sa.Column("prompt_version", sa.String(length=80), nullable=False),
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "normalised_make",
                "normalised_model",
                name="uq_vehicle_category_inference_make_model",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)
    if "mapping_group_approvals_json" in {
        column["name"] for column in inspector.get_columns("cases")
    }:
        with op.batch_alter_table("cases") as batch_op:
            batch_op.drop_column("mapping_group_approvals_json")
