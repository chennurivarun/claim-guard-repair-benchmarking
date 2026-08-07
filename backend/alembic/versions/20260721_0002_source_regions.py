"""Add field-level source regions for invoice lines.

Revision ID: 20260721_0002
Revises: 20260717_0001
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

revision = "20260721_0002"
down_revision = "20260717_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration builds from current SQLAlchemy metadata in this
    # pilot, so a clean database can already contain this column.  Preserve the
    # migration for databases created before the field existed, without making
    # clean installs fail on a duplicate-column error.
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("invoice_line_items")
    }
    if "source_regions_json" not in columns:
        op.add_column(
            "invoice_line_items",
            sa.Column("source_regions_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("invoice_line_items")
    }
    if "source_regions_json" in columns:
        op.drop_column("invoice_line_items", "source_regions_json")
