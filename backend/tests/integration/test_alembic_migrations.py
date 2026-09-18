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


def test_benchmark_source_schema_round_trips_through_20260918_0012(
    alembic_config: Config,
) -> None:
    """Per-source mapping approval and the AI vehicle-category cache.

    Pinned to the named revision before it, like the tests above, so adding a
    later migration does not silently change what this one exercises.
    """

    database_url = alembic_config.get_main_option("sqlalchemy.url")

    def schema() -> tuple[set[str], set[str]]:
        engine = sa.create_engine(database_url)
        try:
            inspector = sa.inspect(engine)
            return (
                {column["name"] for column in inspector.get_columns("cases")},
                set(inspector.get_table_names()),
            )
        finally:
            engine.dispose()

    try:
        command.upgrade(alembic_config, "head")
        cases, tables = schema()
        assert "mapping_group_approvals_json" in cases
        assert "vehicle_category_inferences" in tables

        command.downgrade(alembic_config, "20260917_0011")
        cases, tables = schema()
        assert "mapping_group_approvals_json" not in cases
        assert "vehicle_category_inferences" not in tables
        # The previous revision's columns are left exactly as they were.
        assert "mapping_approved_pairs_json" in cases

        command.upgrade(alembic_config, "head")
        cases, tables = schema()
        assert "mapping_group_approvals_json" in cases
        assert "vehicle_category_inferences" in tables
    finally:
        get_settings.cache_clear()


def test_document_intake_group_round_trips_through_20260918_0013(
    alembic_config: Config,
) -> None:
    """A byte-identical file may exist once per upload source.

    The column is backfilled from ``metadata_json``; the old one-per-case
    constraint is replaced; and the downgrade refuses, rather than deleting
    rows, once copies exist that the old constraint cannot hold.
    """

    database_url = alembic_config.get_main_option("sqlalchemy.url")
    engine = sa.create_engine(database_url)
    digest = "b" * 64

    def insert(document_id: str, metadata: str | None, *, with_group: bool) -> None:
        columns = (
            "id, case_id, document_role, document_kind, original_filename, storage_path, "
            "sha256, mime_type, file_size, upload_status, metadata_json, created_at"
        )
        values = (
            ":id, 'case-1', 'historical', 'unknown', 'copy.pdf', '/nowhere', :sha, "
            "'application/pdf', 1, 'stored', :metadata, '2026-09-18 00:00:00'"
        )
        params = {"id": document_id, "sha": digest, "metadata": metadata}
        if with_group:
            columns += ", intake_group"
            values += ", :group"
            params["group"] = "in_house"
        with engine.begin() as connection:
            connection.execute(sa.text(f"INSERT INTO documents ({columns}) VALUES ({values})"), params)

    def schema() -> tuple[set[str], set[str], set[str]]:
        inspector = sa.inspect(engine)
        return (
            {column["name"] for column in inspector.get_columns("documents")},
            {row["name"] for row in inspector.get_unique_constraints("documents")},
            {row["name"] for row in inspector.get_indexes("documents")},
        )

    try:
        command.upgrade(alembic_config, "head")
        command.downgrade(alembic_config, "20260918_0012")
        columns, uniques, _ = schema()
        assert "intake_group" not in columns
        assert "uq_documents_case_sha256" in uniques

        # A document written before the column existed.
        insert("doc-historical", '{"intake_group": "historical_claim"}', with_group=False)
        command.upgrade(alembic_config, "head")
        columns, uniques, indexes = schema()
        assert "intake_group" in columns
        assert "uq_documents_case_sha256" not in uniques
        assert "uq_documents_case_sha256_group" in uniques
        assert "uq_documents_case_sha256_ungrouped" in indexes
        with engine.connect() as connection:
            backfilled = connection.execute(
                sa.text("SELECT intake_group FROM documents WHERE id = 'doc-historical'")
            ).scalar_one()
        assert backfilled == "historical_claim"

        # The same bytes in the other reference source: allowed at head...
        insert("doc-aviva", '{"intake_group": "in_house"}', with_group=True)
        # ...so the old constraint cannot come back, and the downgrade says so.
        with pytest.raises(RuntimeError, match="same file in more than one upload source"):
            command.downgrade(alembic_config, "20260918_0012")
        with engine.connect() as connection:
            count = connection.execute(sa.text("SELECT COUNT(*) FROM documents")).scalar_one()
        assert count == 2
        columns, _, _ = schema()
        assert "intake_group" in columns

        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM documents WHERE id = 'doc-aviva'"))
        command.downgrade(alembic_config, "20260918_0012")
        columns, uniques, indexes = schema()
        assert "intake_group" not in columns
        assert "uq_documents_case_sha256" in uniques
        assert "uq_documents_case_sha256_ungrouped" not in indexes
    finally:
        engine.dispose()
        get_settings.cache_clear()
