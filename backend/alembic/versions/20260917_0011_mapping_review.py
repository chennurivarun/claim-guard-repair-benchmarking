"""Add the handler's mapping override and the case's mapping approval.

Revision ID: 20260917_0011
Revises: 20260915_0010
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "20260917_0011"
down_revision = "20260915_0010"
branch_labels = None
depends_on = None


# The override lives beside, not inside, ``paired_invoice_id``: that column is
# the outcome and is rewritten from scratch by every pairing pass, so a manual
# decision written there would be lost on the next upload.
#
# ``(table, column, type, server_default)``.  Everything except ``pair_source``
# is nullable with no default -- "the handler has said nothing" is the honest
# state of every existing row.
_ADDED_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine, str | None], ...] = (
    ("engineer_assessments", "pair_source", sa.String(length=20), "automatic"),
    ("engineer_assessments", "manual_pair_state", sa.String(length=20), None),
    ("engineer_assessments", "manual_pair_invoice_id", sa.String(length=36), None),
    ("engineer_assessments", "manual_pair_actor", sa.String(length=160), None),
    ("engineer_assessments", "manual_pair_at", sa.DateTime(timezone=True), None),
    ("engineer_assessments", "manual_pair_reason", sa.Text(), None),
    ("cases", "mapping_approved_at", sa.DateTime(timezone=True), None),
    ("cases", "mapping_approved_by", sa.String(length=160), None),
    ("cases", "mapping_approved_pairs_json", sa.JSON(), None),
)


def upgrade() -> None:
    # Clean databases are built straight from SQLAlchemy metadata by
    # init_db.initialize_database, so every step inspects before it acts and is
    # a no-op on a database that already has the column.
    inspector = sa.inspect(op.get_bind())
    for table, name, column_type, server_default in _ADDED_COLUMNS:
        if name in {column["name"] for column in inspector.get_columns(table)}:
            continue
        op.add_column(
            table,
            sa.Column(
                name,
                column_type,
                nullable=server_default is None,
                server_default=None if server_default is None else sa.text(f"'{server_default}'"),
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, name, _column_type, _server_default in reversed(_ADDED_COLUMNS):
        if name not in {column["name"] for column in inspector.get_columns(table)}:
            continue
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(name)
