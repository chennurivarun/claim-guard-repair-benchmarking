"""Let one file exist once per upload source.

The client loads copies of the same invoices under third party *and* Aviva
DLG.  A copied Word file is byte-identical, and ``uq_documents_case_sha256``
allowed one document per ``(case_id, sha256)``, so the second copy could not
be stored.  ``intake_group`` moves out of ``metadata_json`` into a column
(the metadata key stays, and is still what readers use) so the rule can be
enforced: unique on ``(case_id, sha256, intake_group)``, plus a partial unique
index on ``(case_id, sha256) WHERE intake_group IS NULL`` because NULLs are
distinct under a plain unique constraint.

Revision ID: 20260918_0013
Revises: 20260918_0012
Create Date: 2026-09-18
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "20260918_0013"
down_revision = "20260918_0012"
branch_labels = None
depends_on = None

_TABLE = "documents"
_OLD_UNIQUE = "uq_documents_case_sha256"
_NEW_UNIQUE = "uq_documents_case_sha256_group"
_UNGROUPED_INDEX = "uq_documents_case_sha256_ungrouped"


def _state() -> tuple[set[str], set[str], set[str]]:
    inspector = sa.inspect(op.get_bind())
    return (
        {column["name"] for column in inspector.get_columns(_TABLE)},
        {row["name"] for row in inspector.get_unique_constraints(_TABLE)},
        {row["name"] for row in inspector.get_indexes(_TABLE)},
    )


def _backfill() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT id, metadata_json FROM {_TABLE} WHERE intake_group IS NULL")
    ).all()
    for document_id, metadata in rows:
        if isinstance(metadata, str):
            metadata = json.loads(metadata) if metadata else None
        group = (metadata or {}).get("intake_group") if isinstance(metadata, dict) else None
        if group is not None:
            bind.execute(
                sa.text(f"UPDATE {_TABLE} SET intake_group = :group WHERE id = :id"),
                {"group": group, "id": document_id},
            )


def upgrade() -> None:
    # Clean databases are built straight from SQLAlchemy metadata by the
    # initial migration, so every step inspects before it acts.
    columns, uniques, indexes = _state()
    if "intake_group" not in columns:
        op.add_column(_TABLE, sa.Column("intake_group", sa.String(length=40), nullable=True))
    # Every run, not only when the column was just added: SQLite DDL here is
    # not transactional, so an upgrade interrupted after ``add_column`` must
    # still backfill when it is re-run.  Only NULL rows are touched.
    _backfill()
    if _OLD_UNIQUE in uniques or _NEW_UNIQUE not in uniques:
        with op.batch_alter_table(_TABLE) as batch_op:
            if _OLD_UNIQUE in uniques:
                batch_op.drop_constraint(_OLD_UNIQUE, type_="unique")
            if _NEW_UNIQUE not in uniques:
                batch_op.create_unique_constraint(
                    _NEW_UNIQUE, ["case_id", "sha256", "intake_group"]
                )
    # Outside the batch: a table rebuild does not reliably carry a partial
    # index's WHERE clause across on SQLite.
    _, _, indexes = _state()
    if _UNGROUPED_INDEX not in indexes:
        op.create_index(
            _UNGROUPED_INDEX,
            _TABLE,
            ["case_id", "sha256"],
            unique=True,
            sqlite_where=sa.text("intake_group IS NULL"),
            postgresql_where=sa.text("intake_group IS NULL"),
        )


def downgrade() -> None:
    columns, uniques, indexes = _state()
    if "intake_group" in columns:
        copies = op.get_bind().execute(
            sa.text(
                f"SELECT case_id, sha256, COUNT(*) FROM {_TABLE} "
                "GROUP BY case_id, sha256 HAVING COUNT(*) > 1"
            )
        ).all()
        if copies:
            # Never delete a document to make a constraint fit: each copy has
            # its own pages, extraction and pairing.
            raise RuntimeError(
                f"Cannot downgrade below 20260918_0013: {len(copies)} file(s) are stored as "
                "the same file in more than one upload source, which the old one-document-"
                "per-file rule (uq_documents_case_sha256) cannot hold. Remove the extra "
                "copies first, then run the downgrade again. Nothing has been changed."
            )
    if _UNGROUPED_INDEX in indexes:
        op.drop_index(_UNGROUPED_INDEX, table_name=_TABLE)
    if "intake_group" in columns or _NEW_UNIQUE in uniques or _OLD_UNIQUE not in uniques:
        with op.batch_alter_table(_TABLE) as batch_op:
            if _NEW_UNIQUE in uniques:
                batch_op.drop_constraint(_NEW_UNIQUE, type_="unique")
            if "intake_group" in columns:
                batch_op.drop_column("intake_group")
            if _OLD_UNIQUE not in uniques:
                batch_op.create_unique_constraint(_OLD_UNIQUE, ["case_id", "sha256"])
