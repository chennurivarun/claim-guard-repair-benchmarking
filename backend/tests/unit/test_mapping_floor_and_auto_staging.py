"""Tests for Task B1 (mapping acceptance floor) and Task B2 (auto-staged proposals).

B1: below the acceptance floor, retrieval may still surface a weak fuzzy candidate,
but the deterministic path must not auto-assign it; the line resolves to the
existing no-match outcome with a BELOW_MATCH_FLOOR flag.

B2: a priced invoice line with no accepted mapping auto-stages a provisional
"new ontology item" research proposal via the existing research machinery, is
idempotent per (case, normalised description, part number), and never
contributes price evidence until a handler approves it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.enums import (
    ApprovalStatus,
    CaseStatus,
    ConfidenceLevel,
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    MappingDecision,
    MappingStatus,
    OntologyItemStatus,
    OntologyVersionStatus,
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
    OntologyItem,
    OntologyMapping,
    OntologySynonym,
    OntologyVersion,
    PriceComparison,
    PriceObservation,
    ProcessingRun,
    ResearchItem,
    ResearchTask,
)
from app.services.comparison_workflow import MAPPING_ACCEPTANCE_FLOOR, run_case_comparison
from app.services.research_workflow import approve_research_item, stage_unmatched_line_proposal


@pytest.fixture()
def staging_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    with Session(engine, expire_on_commit=False) as session:
        case = Case(
            case_reference="CG-FLOOR-001",
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
            sha256="b" * 64,
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
            invoice_number="INV-9001",
            invoice_date=date(2026, 6, 1),
            currency="GBP",
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            review_status=ReviewStatus.APPROVED,
        )
        session.add(invoice)
        session.flush()
        yield session, case, invoice
    engine.dispose()


def _bootstrap_version(session: Session) -> OntologyVersion:
    version = session.scalar(
        select(OntologyVersion).where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
    )
    assert version is not None
    return version


def _add_line(
    invoice: Invoice,
    session: Session,
    *,
    sequence_no: int,
    description: str,
    price_net: str = "250.00",
    part_number: str | None = None,
    item_kind: LineItemKind = LineItemKind.PART,
) -> InvoiceLineItem:
    line = InvoiceLineItem(
        invoice_id=invoice.id,
        sequence_no=sequence_no,
        raw_description=description,
        item_kind=item_kind,
        part_number=part_number,
        quantity="1",
        unit="each",
        price_scope=PriceScope.LINE_TOTAL,
        unit_price_net=price_net,
        line_total_net=price_net,
        extraction_method=ExtractionMethod.NATIVE_TABLE,
        status=ReviewStatus.NEEDS_REVIEW,
    )
    session.add(line)
    session.flush()
    return line


def _add_ontology_item(
    session: Session,
    version: OntologyVersion,
    *,
    code: str,
    canonical_name: str,
    price_net: str = "120.00",
    item_type: LineItemKind = LineItemKind.PART,
    synonym: str | None = None,
) -> OntologyItem:
    item = OntologyItem(
        canonical_code=code,
        canonical_name=canonical_name,
        item_type=item_type,
        category="Body",
        unit="each",
        region="UK",
        reference_price_net=price_net,
        price_vat_basis=PriceVatBasis.NET,
        currency="GBP",
        status=OntologyItemStatus.APPROVED,
        approval_status=ApprovalStatus.APPROVED,
        confidence_level=ConfidenceLevel.HIGH,
        created_by="pytest",
        created_in_version_id=version.id,
    )
    session.add(item)
    session.flush()
    if synonym is not None:
        session.add(
            OntologySynonym(
                ontology_item_id=item.id,
                synonym=synonym,
                normalised_synonym=synonym.lower(),
                source_type="seed",
                source_reference="pytest",
                approval_status=ApprovalStatus.APPROVED,
                created_in_version_id=version.id,
            )
        )
    session.flush()
    return item


def _add_processing_run(session: Session, case: Case, *, suffix: str) -> ProcessingRun:
    run = ProcessingRun(
        case_id=case.id,
        run_type=RunType.FULL if suffix == "run1" else RunType.REPROCESS,
        application_version="pytest",
        configuration_hash=f"{suffix}".ljust(64, "0"),
        benchmark_policy_version="claimguard-v1.4",
        extraction_version="pytest-extraction-v1",
        status=RunStatus.SUCCEEDED,
        metrics_json={"invoice_units": 1, "extracted_lines": 1},
    )
    session.add(run)
    session.flush()
    case.current_processing_run_id = run.id
    session.flush()
    return run


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# ---------------------------------------------------------------------------
# (a) A fuzzy candidate around 0.6 similarity is not auto-assigned.
# ---------------------------------------------------------------------------


def test_fuzzy_candidate_below_floor_is_not_auto_assigned(staging_session) -> None:
    session, case, invoice = staging_session
    version = _bootstrap_version(session)
    # Deliberately unrelated to the invoice line: retrieval will still surface
    # it (its score clears the 0.45 retrieval fuzzy_min), but it must not be
    # auto-assigned because it does not clear the 0.80 acceptance floor.
    unrelated_item = _add_ontology_item(
        session,
        version,
        code="TEST-RADIATOR-HOSE",
        canonical_name="Radiator hose upper",
    )
    line = _add_line(
        invoice,
        session,
        sequence_no=1,
        description="Radiator grille remove and refit",
    )
    session.commit()
    _add_processing_run(session, case, suffix="run1")

    result = run_case_comparison(session, case)
    session.commit()

    assert result["status"] == "succeeded"
    assert result["mapped_count"] == 0

    mapping = session.scalar(
        select(OntologyMapping).where(OntologyMapping.invoice_line_item_id == line.id)
    )
    assert mapping is not None
    assert mapping.selected_ontology_item_id is None
    assert mapping.decision == MappingDecision.NO_MATCH
    assert mapping.final_status == MappingStatus.REVIEW
    assert mapping.flags_json["below_match_floor"] is True

    # Retrieval still surfaced the weak candidate for visibility (LLM/human).
    alternatives = mapping.alternative_candidates_json
    assert any(row["ontology_item_id"] == unrelated_item.id for row in alternatives)
    weak_candidate = next(
        row for row in alternatives if row["ontology_item_id"] == unrelated_item.id
    )
    assert Decimal("0.45") <= Decimal(weak_candidate["confidence"]) < MAPPING_ACCEPTANCE_FLOOR

    comparison = session.scalar(
        select(PriceComparison).where(PriceComparison.invoice_line_item_id == line.id)
    )
    assert comparison is not None
    assert "BELOW_MATCH_FLOOR" in comparison.eligibility_flags_json["flags"]


# ---------------------------------------------------------------------------
# (b) An exact synonym match is unaffected by the floor and still auto-assigns.
# ---------------------------------------------------------------------------


def test_exact_synonym_match_still_auto_assigns(staging_session) -> None:
    session, case, invoice = staging_session
    version = _bootstrap_version(session)
    item = _add_ontology_item(
        session,
        version,
        code="TEST-DOOR-MIRROR",
        canonical_name="Door mirror assembly",
        synonym="wing mirror",
    )
    line = _add_line(invoice, session, sequence_no=1, description="Wing Mirror")
    session.commit()
    _add_processing_run(session, case, suffix="run1")

    result = run_case_comparison(session, case)
    session.commit()

    assert result["mapped_count"] == 1
    mapping = session.scalar(
        select(OntologyMapping).where(OntologyMapping.invoice_line_item_id == line.id)
    )
    assert mapping is not None
    assert mapping.selected_ontology_item_id == item.id
    assert mapping.decision == MappingDecision.SYNONYM
    assert mapping.final_status == MappingStatus.AUTO_ACCEPTED
    assert mapping.flags_json["below_match_floor"] is False

    # No unmatched-line staging fires for an accepted mapping.
    assert _count(session, ResearchTask) == 0


# ---------------------------------------------------------------------------
# (c) An unmatched priced line stages exactly one proposal; reruns stage none.
# ---------------------------------------------------------------------------


def test_unmatched_line_stages_one_proposal_and_reruns_do_not_duplicate(
    staging_session,
) -> None:
    session, case, invoice = staging_session
    line = _add_line(
        invoice,
        session,
        sequence_no=1,
        description="Bespoke aftermarket splitter kit",
        price_net="315.50",
        part_number="XK-990Z",
    )
    session.commit()
    _add_processing_run(session, case, suffix="run1")

    result = run_case_comparison(session, case)
    session.commit()
    assert result["mapped_count"] == 0

    assert _count(session, ResearchTask) == 1
    assert _count(session, ResearchItem) == 1
    task = session.scalar(select(ResearchTask))
    assert task is not None
    assert task.invoice_line_item_id == line.id
    assert task.initiated_automatically is True
    assert task.status == ResearchStatus.PROVISIONAL

    item = session.scalar(select(ResearchItem))
    assert item is not None
    assert item.status == ResearchStatus.PROVISIONAL
    assert item.suggested_canonical_name == "Bespoke aftermarket splitter kit"
    assert item.suggested_part_number == "XK-990Z"
    assert item.suggested_price_net == "315.50"
    assert item.suggested_unit == "each"
    assert item.suggested_item_type == LineItemKind.PART

    workflow = item.raw_suggestion_json["workflow"]
    assert workflow["source_type"] == "auto_unmatched_invoice_line"
    assert workflow["initiated_automatically"] is True
    assert workflow["reviewer_initiated"] is False

    provenance = item.raw_suggestion_json["provenance"]
    assert provenance["invoice_id"] == invoice.id
    assert provenance["invoice_line_item_id"] == line.id
    assert provenance["invoice_number"] == "INV-9001"
    assert provenance["part_number"] == "XK-990Z"
    assert provenance["unit"] == "each"
    assert provenance["quantity"] == "1"
    assert provenance["line_total_net"] == "315.50"

    ontology_item = session.get(OntologyItem, item.provisional_ontology_item_id)
    assert ontology_item is not None
    assert ontology_item.approval_status == ApprovalStatus.PROVISIONAL
    assert ontology_item.status == OntologyItemStatus.PROVISIONAL
    assert ontology_item.price_source == "auto_unmatched_invoice_line"

    evidence = session.scalar(select(ExternalEvidence))
    assert evidence is not None
    assert evidence.source_uri.startswith("invoice-line://")
    assert evidence.approval_status == ApprovalStatus.PROVISIONAL

    observation = session.scalar(select(PriceObservation))
    assert observation is not None
    assert observation.approval_status == ApprovalStatus.PROVISIONAL
    assert observation.source_type == "auto_unmatched_invoice_line"

    audit_events = session.scalars(
        select(AuditEvent).where(AuditEvent.event_type == "RESEARCH_AUTO_STAGED_FROM_UNMATCHED_LINE")
    ).all()
    assert len(audit_events) == 1

    # Reprocess the case (a second processing run over the same lines). The
    # same unmatched line must not stage a second proposal.
    _add_processing_run(session, case, suffix="run2")
    result2 = run_case_comparison(session, case)
    session.commit()
    assert result2["mapped_count"] in {0, 1}  # the provisional item may now exact-match

    assert _count(session, ResearchTask) == 1
    assert _count(session, ResearchItem) == 1
    assert (
        len(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type == "RESEARCH_AUTO_STAGED_FROM_UNMATCHED_LINE"
                )
            ).all()
        )
        == 1
    )


def test_stage_unmatched_line_proposal_dedupes_on_direct_recall(staging_session) -> None:
    """Directly exercises the dedupe path, independent of retrieval convergence."""

    session, case, invoice = staging_session
    line = _add_line(
        invoice,
        session,
        sequence_no=1,
        description="Bespoke aftermarket splitter kit",
        price_net="315.50",
        part_number="XK-990Z",
    )
    session.commit()

    first = stage_unmatched_line_proposal(session, case_id=case.id, line=line, invoice=invoice)
    session.flush()
    assert first is not None
    assert _count(session, ResearchTask) == 1

    second = stage_unmatched_line_proposal(session, case_id=case.id, line=line, invoice=invoice)
    session.flush()
    assert second is not None
    assert second.id == first.id
    assert _count(session, ResearchTask) == 1
    assert _count(session, ResearchItem) == 1


# ---------------------------------------------------------------------------
# (d) Approving a staged proposal maps the line to the new item on rerun, with
#     the approved observation's price as evidence.
# ---------------------------------------------------------------------------


def test_approving_staged_proposal_maps_line_with_approved_price_evidence(
    staging_session,
) -> None:
    session, case, invoice = staging_session
    line = _add_line(
        invoice,
        session,
        sequence_no=1,
        description="Bespoke aftermarket splitter kit",
        price_net="315.50",
    )
    session.commit()
    _add_processing_run(session, case, suffix="run1")
    run_case_comparison(session, case)
    session.commit()

    research_item = session.scalar(select(ResearchItem))
    assert research_item is not None
    ontology_item_id = research_item.provisional_ontology_item_id

    approval = approve_research_item(
        session,
        research_item_id=research_item.id,
        approved_by="handler@example.test",
    )
    assert approval["status"] == "approved"
    assert approval["ontology_item_id"] == ontology_item_id
    assert approval["comparison_refresh"]["status"] == "recomputed"

    refreshed_mapping = session.scalar(
        select(OntologyMapping).where(
            OntologyMapping.mapping_run_id == approval["comparison_refresh"]["mapping_run_id"],
            OntologyMapping.invoice_line_item_id == line.id,
        )
    )
    assert refreshed_mapping is not None
    assert refreshed_mapping.selected_ontology_item_id == ontology_item_id

    refreshed_run_id = approval["comparison_refresh"]["processing_run_id"]
    comparison = session.scalar(
        select(PriceComparison).where(
            PriceComparison.processing_run_id == refreshed_run_id,
            PriceComparison.invoice_line_item_id == line.id,
        )
    )
    assert comparison is not None

    ontology_item = session.get(OntologyItem, ontology_item_id)
    assert ontology_item is not None
    assert ontology_item.approval_status == ApprovalStatus.APPROVED

    observation = session.scalar(
        select(PriceObservation).where(PriceObservation.ontology_item_id == ontology_item_id)
    )
    assert observation is not None
    assert observation.approval_status == ApprovalStatus.APPROVED
    assert Decimal(comparison.ontology_unit_net) == Decimal(observation.price_net)
    assert comparison.ontology_line_net is not None


# ---------------------------------------------------------------------------
# (e) An unapproved staged proposal contributes no price evidence.
# ---------------------------------------------------------------------------


def test_unapproved_staged_proposal_contributes_no_price_evidence(staging_session) -> None:
    session, case, invoice = staging_session
    line = _add_line(
        invoice,
        session,
        sequence_no=1,
        description="Bespoke aftermarket splitter kit",
        price_net="315.50",
    )
    session.commit()
    _add_processing_run(session, case, suffix="run1")
    run_case_comparison(session, case)
    session.commit()

    research_item = session.scalar(select(ResearchItem))
    assert research_item is not None
    assert research_item.status == ResearchStatus.PROVISIONAL

    # Rerun comparison (e.g. a reprocess) without ever approving the staged
    # proposal. Even if the provisional item now retrieves as a candidate for
    # its own originating line, the ontology leg must stay unpriced.
    run2 = _add_processing_run(session, case, suffix="run2")
    run_case_comparison(session, case)
    session.commit()

    comparison = session.scalar(
        select(PriceComparison).where(
            PriceComparison.processing_run_id == run2.id,
            PriceComparison.invoice_line_item_id == line.id,
        )
    )
    assert comparison is not None
    mapping = session.get(OntologyMapping, comparison.ontology_mapping_id)
    assert mapping is not None

    ontology_item_id = research_item.provisional_ontology_item_id
    # The provisional item exact-name-retrieves as a candidate for its own
    # originating line on rerun; confirm that even though the mapping resolves
    # to it, the price it carries never entered the benchmark/challenge.
    assert mapping.selected_ontology_item_id == ontology_item_id
    assert mapping.flags_json["ontology_approval"] == ApprovalStatus.PROVISIONAL.value
    assert "ONTOLOGY_EVIDENCE_NOT_APPROVED" in comparison.eligibility_flags_json["flags"]
    # No approved benchmark is available (unapproved ontology, no history), so
    # the challenge/benchmark leg is empty and nothing is challenged from it.
    assert comparison.benchmark_line_net is None
    assert comparison.selected_benchmark_source == "none"

    ontology_item = session.get(OntologyItem, ontology_item_id)
    assert ontology_item is not None
    assert ontology_item.approval_status == ApprovalStatus.PROVISIONAL

    # No ComparisonComparable ever references a not-yet-approved observation;
    # the ontology leg only ever reads OntologyItem.reference_price_net gated
    # by approval_status, never PriceObservation rows directly.
    observation = session.scalar(
        select(PriceObservation).where(PriceObservation.ontology_item_id == ontology_item_id)
    )
    assert observation is not None
    assert observation.approval_status == ApprovalStatus.PROVISIONAL
