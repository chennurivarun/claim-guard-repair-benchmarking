"""Add Engineer Assessment evidence, operations, pairings and variances.

Revision ID: 20260815_0006
Revises: 20260730_0005
Create Date: 2026-08-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20260815_0006"
down_revision = "20260730_0005"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    if "document_kind" not in document_columns:
        op.add_column(
            "documents",
            sa.Column("document_kind", sa.String(length=21), nullable=False, server_default="unknown"),
        )
    tables = set(sa.inspect(bind).get_table_names())
    if "engineer_assessments" not in tables:
        op.create_table(
            "engineer_assessments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("paired_invoice_id", sa.String(36), sa.ForeignKey("invoices.id", ondelete="SET NULL")),
            sa.Column("pair_status", sa.String(40), nullable=False),
            sa.Column("pair_confidence", sa.Float()),
            sa.Column("pair_reasons_json", sa.JSON()),
            sa.Column("assessment_number", sa.String(160)),
            sa.Column("claim_reference", sa.String(160)),
            sa.Column("policy_number", sa.String(160)),
            sa.Column("created_date", sa.Date()), sa.Column("incident_date", sa.Date()),
            sa.Column("authorisation_status", sa.String(100)),
            sa.Column("registration", sa.String(32)), sa.Column("vin", sa.String(64)),
            sa.Column("vehicle_make", sa.String(120)), sa.Column("vehicle_model", sa.String(160)),
            sa.Column("vehicle_variant", sa.String(160)), sa.Column("mileage", sa.Integer()),
            sa.Column("pre_accident_condition", sa.String(120)),
            sa.Column("impact_severity", sa.String(120)), sa.Column("roadworthiness", sa.String(120)),
            sa.Column("damage_areas_json", sa.JSON()),
            *[sa.Column(name, sa.String(80)) for name in (
                "labour_rate", "paint_rate", "labour_net", "paint_net", "parts_net",
                "extras_net", "subtotal_net", "vat_rate", "vat_total", "gross_total",
            )],
            sa.Column("extraction_confidence", sa.Float()),
            sa.Column("review_status", sa.String(12), nullable=False),
            sa.Column("extraction_payload_json", sa.JSON()),
            *_timestamps(),
            sa.UniqueConstraint("document_id", name="uq_engineer_assessment_document"),
        )
        op.create_index("ix_engineer_assessment_case_claim", "engineer_assessments", ["case_id", "claim_reference"])
        op.create_index("ix_engineer_assessment_registration", "engineer_assessments", ["registration"])
    if "assessment_operations" not in tables:
        op.create_table(
            "assessment_operations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("assessment_id", sa.String(36), sa.ForeignKey("engineer_assessments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sequence_no", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("operation_code", sa.String(100)), sa.Column("part_number", sa.String(120)),
            sa.Column("raw_description", sa.Text(), nullable=False),
            sa.Column("normalised_description", sa.Text(), nullable=False),
            sa.Column("work_units", sa.String(80)), sa.Column("hours", sa.String(80)),
            sa.Column("quantity", sa.String(80)), sa.Column("unit_price_net", sa.String(80)),
            sa.Column("total_net", sa.String(80)),
            sa.Column("source_page_id", sa.String(36), sa.ForeignKey("document_pages.id", ondelete="SET NULL")),
            sa.Column("source_bbox_json", sa.JSON()), sa.Column("extraction_confidence", sa.Float()),
            *_timestamps(),
            sa.UniqueConstraint("assessment_id", "sequence_no", name="uq_assessment_operation_sequence"),
        )
        op.create_index("ix_assessment_operation_assessment", "assessment_operations", ["assessment_id"])
    if "assessment_invoice_variances" not in tables:
        op.create_table(
            "assessment_invoice_variances",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("assessment_operation_id", sa.String(36), sa.ForeignKey("assessment_operations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("invoice_id", sa.String(36), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
            sa.Column("invoice_line_item_id", sa.String(36), sa.ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("matching_method", sa.String(40), nullable=False),
            sa.Column("match_confidence", sa.Float(), nullable=False),
            sa.Column("engineer_amount", sa.String(80)), sa.Column("invoice_amount", sa.String(80)),
            sa.Column("difference_amount", sa.String(80)), sa.Column("difference_percentage", sa.String(80)),
            sa.Column("threshold_status", sa.String(40), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint("assessment_operation_id", "invoice_line_item_id", name="uq_assessment_invoice_variance_pair"),
        )
        op.create_index("ix_assessment_invoice_variance_invoice", "assessment_invoice_variances", ["invoice_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in ("assessment_invoice_variances", "assessment_operations", "engineer_assessments"):
        if table in tables:
            op.drop_table(table)
    document_columns = {column["name"] for column in sa.inspect(bind).get_columns("documents")}
    if "document_kind" in document_columns:
        op.drop_column("documents", "document_kind")
