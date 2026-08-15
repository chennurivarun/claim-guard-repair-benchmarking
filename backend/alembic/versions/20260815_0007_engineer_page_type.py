"""Allow Engineer Assessment pages in databases upgraded from the legacy schema.

Revision ID: 20260815_0007
Revises: 20260815_0006
Create Date: 2026-08-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20260815_0007"
down_revision = "20260815_0006"
branch_labels = None
depends_on = None


_LEGACY_PAGE_TYPES = (
    "invoice",
    "estimate_or_order",
    "credit_note",
    "vehicle_document",
    "service_history",
    "mot",
    "photo",
    "blank",
    "other",
)
_PAGE_TYPES = ("engineer_assessment", *_LEGACY_PAGE_TYPES)


def _constraint_sql(values: tuple[str, ...]) -> str:
    choices = ", ".join(f"'{value}'" for value in values)
    return f"page_type IN ({choices})"


def _page_type_constraint() -> dict[str, object] | None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_check_constraints("document_pages"):
        sqltext = str(constraint.get("sqltext") or "")
        if "page_type" in sqltext:
            return constraint
    return None


def _replace_page_type_constraint(values: tuple[str, ...]) -> None:
    current = _page_type_constraint()
    current_name = str((current or {}).get("name") or "ck_document_pages_page_type")
    recreate = "always" if op.get_bind().dialect.name == "sqlite" else "auto"
    with op.batch_alter_table("document_pages", recreate=recreate) as batch_op:
        if current:
            batch_op.drop_constraint(op.f(current_name), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_document_pages_page_type"),
            _constraint_sql(values),
        )


def upgrade() -> None:
    current = _page_type_constraint()
    if current and "engineer_assessment" in str(current.get("sqltext") or ""):
        return
    _replace_page_type_constraint(_PAGE_TYPES)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE document_pages SET page_type = 'other' "
            "WHERE page_type = 'engineer_assessment'"
        )
    )
    _replace_page_type_constraint(_LEGACY_PAGE_TYPES)
