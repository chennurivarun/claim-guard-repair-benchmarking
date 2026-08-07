from __future__ import annotations

from datetime import UTC

from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.enums import AuditActorType, CaseStatus
from app.init_db import initialize_database
from app.models import AuditEvent, Case, ConfigVersion

EXPECTED_TABLES = {
    "audit_events",
    "cases",
    "challenge_results",
    "claim_consistency_findings",
    "claim_contexts",
    "claim_parties",
    "claim_vehicles",
    "config_versions",
    "document_pages",
    "documents",
    "external_evidence",
    "historical_observations",
    "invoice_line_items",
    "invoices",
    "liability_assessments",
    "liability_evidence",
    "mapping_runs",
    "math_findings",
    "ontology_items",
    "ontology_mappings",
    "ontology_synonyms",
    "ontology_versions",
    "price_comparisons",
    "price_observations",
    "processing_runs",
    "research_items",
    "research_tasks",
    "review_decisions",
    "review_tasks",
    "settlements",
}


def make_engine():
    test_engine = create_engine("sqlite:///:memory:")

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return test_engine


def test_schema_initialises_with_expected_core_tables() -> None:
    test_engine = make_engine()
    initialize_database(test_engine, seed_defaults=True)
    assert EXPECTED_TABLES <= set(inspect(test_engine).get_table_names())

    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(ConfigVersion)) == 2


def test_money_columns_are_text_and_timestamps_return_utc() -> None:
    test_engine = make_engine()
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        case = Case(
            case_reference="CG-TEST-001",
            status=CaseStatus.DRAFT,
            created_by="pytest",
        )
        session.add(case)
        session.commit()
        session.refresh(case)
        assert case.created_at.tzinfo == UTC

    with test_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_audit_events_are_hash_chained_per_case() -> None:
    test_engine = make_engine()
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        case = Case(case_reference="CG-AUDIT-001", status=CaseStatus.DRAFT, created_by="pytest")
        session.add(case)
        session.flush()
        first = AuditEvent(
            case_id=case.id,
            actor_type=AuditActorType.USER,
            actor_id="handler@example.test",
            event_type="CASE_CREATED",
            entity_type="case",
            entity_id=case.id,
            event_payload_json={"source": "test"},
        )
        session.add(first)
        session.flush()
        second = AuditEvent(
            case_id=case.id,
            actor_type=AuditActorType.USER,
            actor_id="handler@example.test",
            event_type="CASE_REVIEWED",
            entity_type="case",
            entity_id=case.id,
            before_json={"status": "draft"},
            after_json={"status": "review"},
            event_payload_json={},
        )
        session.add(second)
        session.commit()

        assert first.previous_event_hash is None
        assert first.event_hash is not None and len(first.event_hash) == 64
        assert second.previous_event_hash == first.event_hash
        assert second.event_hash is not None and len(second.event_hash) == 64
