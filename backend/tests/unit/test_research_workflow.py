from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.enums import (
    ApprovalStatus,
    CaseStatus,
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    MappingDecision,
    MappingStatus,
    OntologyItemStatus,
    OntologyVersionStatus,
    PriceObservationKind,
    PriceScope,
    PriceVatBasis,
    ResearchStatus,
    ReviewStatus,
    RunStatus,
    RunType,
    UploadStatus,
)
from app.init_db import initialize_database
from app.models import (
    AuditEvent,
    Case,
    Document,
    ExternalEvidence,
    Invoice,
    InvoiceLineItem,
    MappingRun,
    OntologyItem,
    OntologyMapping,
    OntologyVersion,
    PriceComparison,
    PriceObservation,
    ProcessingRun,
    ResearchItem,
    ResearchTask,
)
from app.services.comparison_workflow import run_case_comparison
from app.services.research_workflow import (
    ManualEvidenceInput,
    ResearchSuggestionInput,
    ResearchWorkflowError,
    approve_research_item,
    trigger_manual_research,
)


@pytest.fixture()
def research_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    with Session(engine, expire_on_commit=False) as session:
        case = Case(
            case_reference="CG-RESEARCH-001",
            status=CaseStatus.COMPARISON_REVIEW,
            created_by="test-handler",
        )
        session.add(case)
        session.flush()
        document = Document(
            case_id=case.id,
            document_role=DocumentRole.CURRENT,
            original_filename="invoice.pdf",
            storage_path="/tmp/invoice.pdf",
            sha256="a" * 64,
            mime_type="application/pdf",
            file_size=100,
            upload_status=UploadStatus.READY,
        )
        session.add(document)
        session.flush()
        invoice = Invoice(
            case_id=case.id,
            document_id=document.id,
            document_group_id="invoice-1",
            document_role=InvoiceDocumentRole.INVOICE,
            invoice_number="INV-001",
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            review_status=ReviewStatus.APPROVED,
        )
        session.add(invoice)
        session.flush()
        line = InvoiceLineItem(
            invoice_id=invoice.id,
            sequence_no=1,
            raw_description="Front bumper reinforcement",
            normalised_description="front bumper reinforcement",
            item_kind=LineItemKind.PART,
            quantity="1",
            unit="each",
            price_scope=PriceScope.LINE_TOTAL,
            unit_price_net="185.00",
            line_total_net="185.00",
            extraction_method=ExtractionMethod.NATIVE_TABLE,
            status=ReviewStatus.NEEDS_REVIEW,
        )
        session.add(line)
        session.commit()
        yield session, case.id, line.id
    engine.dispose()


def _settings(*, two_step_approval: bool) -> Settings:
    return Settings(
        _env_file=None,
        auto_research=False,
        two_step_approval=two_step_approval,
        research_source_allowlists={
            "pilot-manual-sources-v1": ["*.example.test"],
            "insurer-pilot-v3": [
                "parts.example.test",
                "second.example.test",
            ],
        },
    )


def _suggestion() -> ResearchSuggestionInput:
    return ResearchSuggestionInput(
        canonical_name="Front bumper reinforcement bar",
        item_type=LineItemKind.PART,
        category="Body",
        unit="each",
        price_net="124.99",
        date_checked=date(2026, 7, 17),
        rationale="Matched by exact manufacturer part number and vehicle fitment.",
        vat_basis=PriceVatBasis.NET,
        price_scope=PriceScope.UNIT,
        part_number="BR-2048",
        vehicle_compatibility={"make": "Ford", "model": "Focus"},
        confidence=0.91,
        quality_tier="OEM-equivalent",
    )


def _evidence() -> list[ManualEvidenceInput]:
    return [
        ManualEvidenceInput(
            source_uri="https://parts.example.test/catalogue/BR-2048",
            title="BR-2048 front bumper reinforcement",
            captured_at=datetime(2026, 7, 17, 9, 30, tzinfo=UTC),
            minimal_excerpt="New OEM-equivalent part, net price excluding delivery.",
            source_record_id="BR-2048",
            price_net="124.99",
            currency="GBP",
            vat_basis=PriceVatBasis.NET,
            unit="each",
            part_number="BR-2048",
            fitment={"make": "Ford", "model": "Focus"},
            quality_tier="OEM-equivalent",
            condition="new",
            shipping="0.00",
            stock_status="in_stock",
            validation_flags={"allow_list_match": True},
        ),
        ManualEvidenceInput(
            source_uri="https://second.example.test/parts/BR-2048",
            title="Independent BR-2048 listing",
            captured_at=datetime(2026, 7, 17, 9, 45, tzinfo=UTC),
            price_net="126.50",
            currency="GBP",
            unit="each",
            part_number="BR-2048",
            condition="new",
        ),
    ]


def _trigger(
    session: Session,
    case_id: str,
    line_id: str,
    *,
    two_step_approval: bool,
):
    return trigger_manual_research(
        session,
        case_id=case_id,
        invoice_line_item_id=line_id,
        requested_by="reviewer@example.test",
        query_text="Research the missing bumper reinforcement item",
        suggestion=_suggestion(),
        evidence=_evidence(),
        source_allow_list_version="insurer-pilot-v3",
        settings=_settings(two_step_approval=two_step_approval),
    )


def _add_second_line(session: Session, source_line_id: str) -> InvoiceLineItem:
    source_line = session.get(InvoiceLineItem, source_line_id)
    assert source_line is not None
    line = InvoiceLineItem(
        invoice_id=source_line.invoice_id,
        sequence_no=2,
        raw_description="Additional researched part",
        normalised_description="additional researched part",
        item_kind=LineItemKind.PART,
        quantity="1",
        unit="each",
        price_scope=PriceScope.LINE_TOTAL,
        unit_price_net="90.00",
        line_total_net="90.00",
        extraction_method=ExtractionMethod.NATIVE_TABLE,
        status=ReviewStatus.NEEDS_REVIEW,
    )
    session.add(line)
    session.commit()
    return line


def test_reviewer_trigger_creates_governed_provisional_lineage(
    research_session,
) -> None:
    session, case_id, line_id = research_session

    result = _trigger(session, case_id, line_id, two_step_approval=False)

    assert result["status"] == "provisional"
    assert result["next_action"] == "handler_approval"
    assert result["second_review_required"] is False
    assert result["source_urls"] == [
        "https://parts.example.test/catalogue/BR-2048",
        "https://second.example.test/parts/BR-2048",
    ]
    assert result["date_checked"] == "2026-07-17"
    assert result["confidence"] == pytest.approx(0.91)
    assert result["comparison_refresh"]["status"] == "not_requested"
    assert len(result["evidence_ids"]) == 2
    assert len(result["price_observation_ids"]) == 2

    task = session.get(ResearchTask, result["task_id"])
    item = session.get(ResearchItem, result["research_item_id"])
    ontology_item = session.get(OntologyItem, result["ontology_item_id"])
    version = session.get(OntologyVersion, result["ontology_version_id"])
    assert task is not None
    assert task.initiated_automatically is False
    assert task.source_allow_list_version == "insurer-pilot-v3"
    assert task.status == ResearchStatus.PROVISIONAL
    assert item is not None and item.status == ResearchStatus.PROVISIONAL
    assert ontology_item is not None
    assert ontology_item.status == OntologyItemStatus.PROVISIONAL
    assert ontology_item.approval_status == ApprovalStatus.PROVISIONAL
    assert ontology_item.reference_price_net == "124.99"
    assert version is not None and version.status == OntologyVersionStatus.DRAFT

    persisted_evidence = list(
        session.scalars(
            select(ExternalEvidence)
            .where(ExternalEvidence.research_task_id == task.id)
            .order_by(ExternalEvidence.captured_at)
        ).all()
    )
    assert persisted_evidence[0].source_uri == result["source_urls"][0]
    assert persisted_evidence[0].captured_at == datetime(2026, 7, 17, 9, 30, tzinfo=UTC)
    assert persisted_evidence[0].content_hash
    assert len(persisted_evidence[0].content_hash) == 64
    assert persisted_evidence[0].approval_status == ApprovalStatus.PROVISIONAL
    assert persisted_evidence[0].validation_flags_json["allow_list_match"] is True
    assert persisted_evidence[0].validation_flags_json["allow_list_version"] == "insurer-pilot-v3"
    assert persisted_evidence[0].validation_flags_json["validated_host"] == "parts.example.test"

    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "RESEARCH_TRIGGERED_BY_REVIEWER")
    )
    assert audit is not None
    assert audit.case_id == case_id
    assert audit.event_payload_json["initiated_automatically"] is False
    assert audit.event_payload_json["source_allow_list_version"] == "insurer-pilot-v3"
    assert audit.after_json["source_urls"] == result["source_urls"]


def test_default_handler_approval_promotes_item_and_evidence_to_bank(
    research_session,
) -> None:
    session, case_id, line_id = research_session
    created = _trigger(session, case_id, line_id, two_step_approval=False)

    approved = approve_research_item(
        session,
        research_item_id=created["research_item_id"],
        approved_by="handler@example.test",
        reviewer_note="Yes — source and fitment checked.",
        settings=_settings(two_step_approval=False),
    )

    assert approved["status"] == "approved"
    assert approved["next_action"] == "none"
    assert approved["second_review_required"] is False
    assert approved["comparison_refresh"]["status"] == "skipped_no_completed_run"
    item = session.get(ResearchItem, approved["research_item_id"])
    ontology_item = session.get(OntologyItem, approved["ontology_item_id"])
    version = session.get(OntologyVersion, approved["ontology_version_id"])
    assert item is not None and item.status == ResearchStatus.APPROVED
    assert item.reviewer == "handler@example.test"
    assert item.research_task.status == ResearchStatus.APPROVED
    assert ontology_item is not None
    assert ontology_item.status == OntologyItemStatus.APPROVED
    assert ontology_item.approval_status == ApprovalStatus.APPROVED
    assert version is not None and version.status == OntologyVersionStatus.PUBLISHED
    assert version.published_at is not None

    evidence_statuses = set(
        session.scalars(
            select(ExternalEvidence.approval_status).where(
                ExternalEvidence.research_task_id == created["task_id"]
            )
        ).all()
    )
    assert evidence_statuses == {ApprovalStatus.APPROVED}
    observations = list(
        session.scalars(
            select(PriceObservation).where(
                PriceObservation.ontology_item_id == approved["ontology_item_id"]
            )
        ).all()
    )
    assert {row.approval_status for row in observations} == {ApprovalStatus.APPROVED}
    assert {row.observation_kind for row in observations} == {PriceObservationKind.MARKET}
    assert all(row.evidence_id in created["evidence_ids"] for row in observations)

    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "RESEARCH_ITEM_APPROVED_TO_BANK")
    )
    assert audit is not None
    assert audit.actor_id == "handler@example.test"
    assert audit.event_payload_json["two_step_approval"] is False
    assert audit.event_payload_json["source_urls"] == created["source_urls"]
    assert audit.event_payload_json["date_checked"] == "2026-07-17"
    assert audit.event_payload_json["confidence"] == pytest.approx(0.91)


def test_two_step_flag_keeps_first_approval_provisional_until_new_checker(
    research_session,
) -> None:
    session, case_id, line_id = research_session
    created = _trigger(session, case_id, line_id, two_step_approval=True)

    first = approve_research_item(
        session,
        research_item_id=created["research_item_id"],
        approved_by="handler@example.test",
        reviewer_note="Maker approval.",
        settings=_settings(two_step_approval=True),
    )

    assert first["status"] == "awaiting_second_review"
    assert first["second_review_required"] is True
    assert first["next_action"] == "second_review"
    item = session.get(ResearchItem, first["research_item_id"])
    ontology_item = session.get(OntologyItem, first["ontology_item_id"])
    assert item is not None and item.status == ResearchStatus.PROVISIONAL
    assert ontology_item is not None
    assert ontology_item.status == OntologyItemStatus.PROVISIONAL
    assert ontology_item.approval_status == ApprovalStatus.PROVISIONAL

    with pytest.raises(ResearchWorkflowError) as exc_info:
        approve_research_item(
            session,
            research_item_id=created["research_item_id"],
            approved_by="handler@example.test",
            settings=_settings(two_step_approval=True),
        )
    assert exc_info.value.code == "SECOND_REVIEWER_MUST_DIFFER"

    final = approve_research_item(
        session,
        research_item_id=created["research_item_id"],
        approved_by="checker@example.test",
        reviewer_note="Checker approval.",
        settings=_settings(two_step_approval=True),
    )
    assert final["status"] == "approved"
    assert final["next_action"] == "none"
    session.refresh(item)
    session.refresh(ontology_item)
    assert item.status == ResearchStatus.APPROVED
    assert item.reviewer == "checker@example.test"
    assert item.raw_suggestion_json["approval_workflow"]["first_approved_by"] == (
        "handler@example.test"
    )
    assert item.raw_suggestion_json["approval_workflow"]["final_approved_by"] == (
        "checker@example.test"
    )
    assert ontology_item.status == OntologyItemStatus.APPROVED

    events = list(
        session.scalars(
            select(AuditEvent.event_type).where(AuditEvent.correlation_id == created["task_id"])
        ).all()
    )
    assert events == [
        "RESEARCH_TRIGGERED_BY_REVIEWER",
        "RESEARCH_FIRST_APPROVAL_RECORDED",
        "RESEARCH_ITEM_APPROVED_TO_BANK",
    ]


def test_trigger_rejects_non_url_evidence_and_wrong_case_line(
    research_session,
) -> None:
    session, case_id, line_id = research_session
    invalid_evidence = [
        ManualEvidenceInput(
            source_uri="parts.example.test/no-scheme",
            title="Missing URL scheme",
            price_net="10.00",
        )
    ]
    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id=case_id,
            invoice_line_item_id=line_id,
            requested_by="reviewer@example.test",
            query_text="research",
            suggestion=_suggestion(),
            evidence=invalid_evidence,
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "INVALID_RESEARCH_INPUT"

    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id="not-this-case",
            invoice_line_item_id=line_id,
            requested_by="reviewer@example.test",
            query_text="research",
            suggestion=_suggestion(),
            evidence=_evidence(),
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "INVOICE_LINE_NOT_FOUND"


def test_source_host_must_match_the_versioned_allow_list(research_session) -> None:
    session, case_id, line_id = research_session
    unlisted = [
        ManualEvidenceInput(
            source_uri="https://untrusted.example.org/BR-2048",
            title="Unlisted source",
            price_net="124.99",
        )
    ]
    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id=case_id,
            invoice_line_item_id=line_id,
            requested_by="reviewer@example.test",
            query_text="research",
            suggestion=_suggestion(),
            evidence=unlisted,
            source_allow_list_version="insurer-pilot-v3",
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "SOURCE_HOST_NOT_ALLOWED"

    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id=case_id,
            invoice_line_item_id=line_id,
            requested_by="reviewer@example.test",
            query_text="research",
            suggestion=_suggestion(),
            evidence=_evidence(),
            source_allow_list_version="unknown-version",
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "SOURCE_ALLOW_LIST_NOT_CONFIGURED"


def test_identity_and_evidence_content_prevent_duplicate_research(
    research_session,
) -> None:
    session, case_id, line_id = research_session
    created = _trigger(session, case_id, line_id, two_step_approval=False)
    second_line = _add_second_line(session, line_id)

    different_identity = replace(
        _suggestion(),
        canonical_name="Different researched part",
        part_number="DIFFERENT-001",
    )
    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id=case_id,
            invoice_line_item_id=second_line.id,
            requested_by="reviewer@example.test",
            query_text="same evidence, different proposed identity",
            suggestion=different_identity,
            evidence=_evidence(),
            source_allow_list_version="insurer-pilot-v3",
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "EVIDENCE_CONTENT_ALREADY_RESEARCHED"

    approve_research_item(
        session,
        research_item_id=created["research_item_id"],
        approved_by="handler@example.test",
        settings=_settings(two_step_approval=False),
    )
    fresh_evidence = [
        ManualEvidenceInput(
            source_uri="https://parts.example.test/catalogue/BR-2048-new-capture",
            title="Fresh capture of the same canonical item",
            price_net="123.50",
            part_number="BR-2048",
        )
    ]
    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id=case_id,
            invoice_line_item_id=second_line.id,
            requested_by="reviewer@example.test",
            query_text="duplicate approved canonical identity",
            suggestion=_suggestion(),
            evidence=fresh_evidence,
            source_allow_list_version="insurer-pilot-v3",
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "ONTOLOGY_ITEM_ALREADY_APPROVED"

    with pytest.raises(ResearchWorkflowError) as exc_info:
        trigger_manual_research(
            session,
            case_id=case_id,
            invoice_line_item_id=line_id,
            requested_by="reviewer@example.test",
            query_text="retry approved line",
            suggestion=different_identity,
            evidence=fresh_evidence,
            source_allow_list_version="insurer-pilot-v3",
            settings=_settings(two_step_approval=False),
        )
    assert exc_info.value.code == "RESEARCH_ALREADY_APPROVED_FOR_LINE"


def test_approval_remaps_line_and_recomputes_into_new_immutable_run(
    research_session,
) -> None:
    session, case_id, line_id = research_session
    case = session.get(Case, case_id)
    line = session.get(InvoiceLineItem, line_id)
    assert case is not None and line is not None
    invoice = session.get(Invoice, line.invoice_id)
    assert invoice is not None
    invoice.invoice_date = date(2026, 7, 10)
    source_run = ProcessingRun(
        case_id=case.id,
        run_type=RunType.FULL,
        application_version="pytest",
        configuration_hash="b" * 64,
        benchmark_policy_version="claimguard-v1.4",
        extraction_version="pytest-extraction-v1",
        status=RunStatus.SUCCEEDED,
        started_at=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 17, 8, 1, tzinfo=UTC),
        metrics_json={"invoice_units": 1, "extracted_lines": 1},
    )
    session.add(source_run)
    session.flush()
    case.current_processing_run_id = source_run.id
    initial = run_case_comparison(session, case)
    assert initial["line_count"] == 1
    session.commit()

    old_mapping = session.scalar(
        select(OntologyMapping).where(
            OntologyMapping.mapping_run_id == initial["mapping_run_id"],
            OntologyMapping.invoice_line_item_id == line_id,
        )
    )
    assert old_mapping is not None
    assert old_mapping.selected_ontology_item_id is None

    created = _trigger(session, case_id, line_id, two_step_approval=False)
    approved = approve_research_item(
        session,
        research_item_id=created["research_item_id"],
        approved_by="handler@example.test",
        reviewer_note="Approved and recompute.",
        settings=_settings(two_step_approval=False),
    )

    refresh = approved["comparison_refresh"]
    assert refresh["status"] == "recomputed"
    assert refresh["previous_processing_run_id"] == source_run.id
    assert refresh["processing_run_id"] != source_run.id
    session.refresh(case)
    assert case.current_processing_run_id == refresh["processing_run_id"]
    assert session.get(ProcessingRun, source_run.id) is not None

    new_mapping = session.get(OntologyMapping, refresh["ontology_mapping_id"])
    assert new_mapping is not None
    assert new_mapping.mapping_run_id == refresh["mapping_run_id"]
    assert new_mapping.invoice_line_item_id == line_id
    assert new_mapping.selected_ontology_item_id == approved["ontology_item_id"]
    assert new_mapping.decision == MappingDecision.MANUAL
    assert new_mapping.final_status == MappingStatus.APPROVED
    assert new_mapping.reviewed_by == "handler@example.test"
    assert new_mapping.flags_json["manual_research_override"] is True

    runs = list(session.scalars(select(ProcessingRun)).all())
    mappings = list(session.scalars(select(MappingRun)).all())
    comparisons = list(session.scalars(select(PriceComparison)).all())
    assert len(runs) == 2
    assert len(mappings) == 2
    assert len(comparisons) == 2
    assert {row.processing_run_id for row in comparisons} == {
        source_run.id,
        refresh["processing_run_id"],
    }
    refreshed_comparison = next(
        row for row in comparisons if row.processing_run_id == refresh["processing_run_id"]
    )
    assert refreshed_comparison.ontology_mapping_id == new_mapping.id
    assert refreshed_comparison.ontology_version_id == approved["ontology_version_id"]

    audit = session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "RESEARCH_COMPARISON_REFRESHED")
    )
    assert audit is not None
    assert audit.processing_run_id == refresh["processing_run_id"]
    assert audit.after_json["ontology_mapping_id"] == new_mapping.id
