"""Prevent ambiguous handler-learned exact synonyms.

Revision ID: 20260822_0008
Revises: 20260815_0007
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa

revision = "20260822_0008"
down_revision = "20260815_0007"
branch_labels = None
depends_on = None

_INDEX = "uq_ontology_synonyms_learned_normalised"
_LEARNED_SOURCE = "handler_approved_invoice_mapping"


def upgrade() -> None:
    bind = op.get_bind()
    indexes = {row["name"] for row in sa.inspect(bind).get_indexes("ontology_synonyms")}
    if _INDEX in indexes:
        return
    # Existing ambiguous learned aliases are unsafe to reuse for either item.
    # Remove only those learned rows; supplied ontology synonyms stay untouched.
    op.execute(
        sa.text(
            "DELETE FROM ontology_synonyms "
            "WHERE source_type = :source_type "
            "AND normalised_synonym IN ("
            "SELECT normalised_synonym FROM ontology_synonyms "
            "WHERE source_type = :source_type "
            "GROUP BY normalised_synonym HAVING COUNT(*) > 1"
            ")"
        ).bindparams(source_type=_LEARNED_SOURCE)
    )
    op.create_index(
        _INDEX,
        "ontology_synonyms",
        ["normalised_synonym"],
        unique=True,
        sqlite_where=sa.text("source_type = 'handler_approved_invoice_mapping'"),
        postgresql_where=sa.text("source_type = 'handler_approved_invoice_mapping'"),
    )


def downgrade() -> None:
    indexes = {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_indexes("ontology_synonyms")
    }
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name="ontology_synonyms")
