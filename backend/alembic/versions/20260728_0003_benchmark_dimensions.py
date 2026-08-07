"""Add governed vehicle dimensions for repair-cost benchmarking.

Revision ID: 20260728_0003
Revises: 20260721_0002
Create Date: 2026-07-28
"""

import sqlalchemy as sa

from alembic import op

revision = "20260728_0003"
down_revision = "20260721_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("historical_observations")
    }
    additions = (
        ("official_vehicle_class", sa.String(length=120)),
        ("bodywork_code", sa.String(length=24)),
        ("market_segment", sa.String(length=120)),
        ("classification_source", sa.String(length=240)),
    )
    for name, column_type in additions:
        if name not in columns:
            op.add_column("historical_observations", sa.Column(name, column_type, nullable=True))
    indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("historical_observations")
    }
    if "ix_historical_observations_vehicle_class" not in indexes:
        op.create_index(
            "ix_historical_observations_vehicle_class",
            "historical_observations",
            ["official_vehicle_class"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("historical_observations")}
    if "ix_historical_observations_vehicle_class" in indexes:
        op.drop_index(
            "ix_historical_observations_vehicle_class", table_name="historical_observations"
        )
    columns = {column["name"] for column in sa.inspect(bind).get_columns("historical_observations")}
    for name in (
        "classification_source",
        "market_segment",
        "bodywork_code",
        "official_vehicle_class",
    ):
        if name in columns:
            op.drop_column("historical_observations", name)
