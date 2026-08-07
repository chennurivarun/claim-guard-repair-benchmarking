"""Capture governed vehicle classification on claim and invoice vehicles.

Revision ID: 20260728_0004
Revises: 20260728_0003
Create Date: 2026-07-28
"""

import sqlalchemy as sa

from alembic import op

revision = "20260728_0004"
down_revision = "20260728_0003"
branch_labels = None
depends_on = None


FIELDS = (
    ("official_vehicle_class", sa.String(length=120)),
    ("bodywork_code", sa.String(length=24)),
    ("market_segment", sa.String(length=120)),
    ("classification_source", sa.String(length=240)),
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in ("claim_vehicles", "vehicles"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        for name, column_type in FIELDS:
            if name not in columns:
                op.add_column(table_name, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("claim_vehicles", "vehicles"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table_name)}
        for name, _ in reversed(FIELDS):
            if name in columns:
                op.drop_column(table_name, name)
