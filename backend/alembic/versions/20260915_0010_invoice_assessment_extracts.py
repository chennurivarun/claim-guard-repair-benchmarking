"""Add the invoice/assessment extract columns and the claim+policy indexes.

Revision ID: 20260915_0010
Revises: 20260823_0009
Create Date: 2026-09-15
"""

import sqlalchemy as sa

from alembic import op

revision = "20260915_0010"
down_revision = "20260823_0009"
branch_labels = None
depends_on = None


# Money is text in this schema (see app.db_types.DecimalString); migrations
# declare it as a plain string column, as the earlier revisions do.
_ADDED_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine, bool], ...] = (
    ("invoices", "policy_number", sa.String(length=160), True),
    ("invoices", "paint_net", sa.String(length=80), True),
    ("invoice_line_items", "line_item_type", sa.String(length=40), True),
    ("invoice_line_items", "is_section_total", sa.Boolean(), False),
    ("assessment_operations", "raw_category", sa.String(length=160), True),
)

_ADDED_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_invoices_claim_policy", "invoices", ["claim_reference", "policy_number"]),
    (
        "ix_engineer_assessment_claim_policy",
        "engineer_assessments",
        ["claim_reference", "policy_number"],
    ),
)


def upgrade() -> None:
    # Clean databases are built straight from SQLAlchemy metadata by
    # init_db.initialize_database, so every step inspects before it acts and is
    # a no-op on a database that already has the column or index.
    inspector = sa.inspect(op.get_bind())
    for table, name, column_type, nullable in _ADDED_COLUMNS:
        if name in {column["name"] for column in inspector.get_columns(table)}:
            continue
        op.add_column(
            table,
            sa.Column(
                name,
                column_type,
                nullable=nullable,
                server_default=None if nullable else sa.false(),
            ),
        )
    for name, table, columns in _ADDED_INDEXES:
        if name in {index["name"] for index in inspector.get_indexes(table)}:
            continue
        op.create_index(name, table, columns)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for name, table, _columns in _ADDED_INDEXES:
        if name in {index["name"] for index in inspector.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    for table, name, _column_type, _nullable in reversed(_ADDED_COLUMNS):
        if name not in {column["name"] for column in inspector.get_columns(table)}:
            continue
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(name)
