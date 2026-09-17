from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("CLAIM_GUARD_DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_upgrade_head_creates_review_briefing_column(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    database_url = alembic_config.get_main_option("sqlalchemy.url")
    engine = sa.create_engine(database_url)
    try:
        columns = {column["name"] for column in sa.inspect(engine).get_columns("documents")}
        assert "review_briefing_json" in columns
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_extract_columns_round_trip_through_20260915_0010(alembic_config: Config) -> None:
    database_url = alembic_config.get_main_option("sqlalchemy.url")

    def extract_schema() -> tuple[set[str], set[str], set[str], set[str], set[str]]:
        engine = sa.create_engine(database_url)
        try:
            inspector = sa.inspect(engine)
            return (
                {column["name"] for column in inspector.get_columns("invoices")},
                {column["name"] for column in inspector.get_columns("invoice_line_items")},
                {column["name"] for column in inspector.get_columns("assessment_operations")},
                {index["name"] for index in inspector.get_indexes("invoices")},
                {index["name"] for index in inspector.get_indexes("engineer_assessments")},
            )
        finally:
            engine.dispose()

    try:
        command.upgrade(alembic_config, "head")
        invoices, lines, operations, invoice_indexes, assessment_indexes = extract_schema()
        assert {"policy_number", "paint_net"} <= invoices
        assert {"line_item_type", "is_section_total"} <= lines
        assert "raw_category" in operations
        assert "ix_invoices_claim_policy" in invoice_indexes
        assert "ix_engineer_assessment_claim_policy" in assessment_indexes

        # Pinned to the revision *before* 20260915_0010 rather than a relative
        # "-1": this test is about one named revision, and a relative step
        # silently starts testing a different one the moment a migration is
        # added on top of it.
        command.downgrade(alembic_config, "20260823_0009")
        invoices, lines, operations, invoice_indexes, assessment_indexes = extract_schema()
        assert not {"policy_number", "paint_net"} & invoices
        assert not {"line_item_type", "is_section_total"} & lines
        assert "raw_category" not in operations
        assert "ix_invoices_claim_policy" not in invoice_indexes
        assert "ix_engineer_assessment_claim_policy" not in assessment_indexes

        command.upgrade(alembic_config, "head")
        invoices, lines, operations, _, _ = extract_schema()
        assert {"policy_number", "paint_net"} <= invoices
        assert {"line_item_type", "is_section_total"} <= lines
        assert "raw_category" in operations
    finally:
        get_settings.cache_clear()


def test_mapping_review_columns_round_trip_through_20260917_0011(
    alembic_config: Config,
) -> None:
    """The handler's override and the case's approval survive a down/up cycle.

    The override columns are the load-bearing half: they are what makes a
    manual link survive the next upload, so a migration that silently failed
    to create them would leave the pairing pass overwriting every handler
    decision with no error anywhere.
    """

    database_url = alembic_config.get_main_option("sqlalchemy.url")
    assessment_columns = {
        "pair_source",
        "manual_pair_state",
        "manual_pair_invoice_id",
        "manual_pair_actor",
        "manual_pair_at",
        "manual_pair_reason",
    }
    case_columns = {
        "mapping_approved_at",
        "mapping_approved_by",
        "mapping_approved_pairs_json",
    }

    def schema() -> tuple[set[str], set[str]]:
        engine = sa.create_engine(database_url)
        try:
            inspector = sa.inspect(engine)
            return (
                {column["name"] for column in inspector.get_columns("engineer_assessments")},
                {column["name"] for column in inspector.get_columns("cases")},
            )
        finally:
            engine.dispose()

    try:
        command.upgrade(alembic_config, "head")
        assessments, cases = schema()
        assert assessment_columns <= assessments
        assert case_columns <= cases

        command.downgrade(alembic_config, "20260915_0010")
        assessments, cases = schema()
        assert not assessment_columns & assessments
        assert not case_columns & cases

        command.upgrade(alembic_config, "head")
        assessments, cases = schema()
        assert assessment_columns <= assessments
        assert case_columns <= cases
    finally:
        get_settings.cache_clear()
