"""Add AI-generated review briefing storage to documents.

Revision ID: 20260823_0009
Revises: 20260822_0008
Create Date: 2026-08-23
"""

import sqlalchemy as sa

from alembic import op

revision = "20260823_0009"
down_revision = "20260822_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial migration builds from current SQLAlchemy metadata in this
    # pilot, so a clean database can already contain this column. Preserve the
    # migration for databases created before the field existed, without making
    # clean installs fail on a duplicate-column error.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "review_briefing_json" not in columns:
        op.add_column(
            "documents",
            sa.Column("review_briefing_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "review_briefing_json" in columns:
        op.drop_column("documents", "review_briefing_json")
