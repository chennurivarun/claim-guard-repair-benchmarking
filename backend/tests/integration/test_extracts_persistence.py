"""The three client format pairs, uploaded and processed through the real API.

Every column the "two standardised tables" need has to survive the round trip
from a `.docx` upload to the database: the invoice's section totals and claim
identity, each line's printed section and whether it is a rolled-up total, and
each assessment operation's section. The arithmetic checks have to read those
columns too -- a section total is evidence of a section's value, never a
priced row, so counting one in a row sum makes every rolled-up invoice look
fraudulent.

Deterministic, LLM-free: no extractor is configured in the test settings, so
the native parsers do all of the work and the numbers below are exact.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.database import get_db
from app.enums import (
    CheckStatus,
    LineItemKind,
    MappingDecision,
    MappingStatus,
    PageType,
    RunStatus,
    Severity,
)
from app.extraction.pdf_pipeline import PDFPipeline
from app.init_db import initialize_database
from app.main import app
from app.models import (
    AssessmentOperation,
    Case,
    ClaimConsistencyFinding,
    Document,
    DocumentPage,
    EngineerAssessment,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    MappingRun,
    MathFinding,
    OntologyItem,
    OntologyMapping,
    OntologyVersion,
    PriceComparison,
)
from app.services.benchmarking import sync_finalised_case_to_benchmarks
from app.services.comparison_workflow import run_case_comparison

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PAIRS: dict[int, tuple[str, str]] = {
    1: ("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_1.docx"),
    2: ("DL_Auda_format_2_assessment.docx", "DL_Invoice_2_request_for_payment.docx"),
    7: ("DL_Auda_format_7_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
}

#: Row sums are only ever compared against a stated section total; every other
#: check on the list is stated-versus-stated and cannot see a row at all.
ROW_SUM_CHECKS = ("LABOUR_TOTAL_MISMATCH", "PARTS_TOTAL_MISMATCH")


@pytest.fixture
def extracts_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'extracts.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    from app.services import document_processing

    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    with TestClient(app) as client:
        client.engine = engine
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def _process_pair(client: TestClient, pair_id: int) -> dict[str, dict]:
    """Upload and process one client pair; return each document's API payload."""

    reference = f"EXTRACTS-{pair_id}"
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": f"2026/EXTRACTS/{pair_id}",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text
    documents: dict[str, dict] = {}
    for filename in PAIRS[pair_id]:
        uploaded = client.post(
            f"/api/v1/claims/{reference}/documents",
            files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
            data={"role": "current"},
        )
        assert uploaded.status_code == 200, uploaded.text
        processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
        assert processed.status_code == 200, processed.text
        documents[filename] = processed.json()["document"]
    return documents


def _session(client: TestClient) -> Session:
    return Session(client.engine, expire_on_commit=False)


def test_repeated_extracted_line_numbers_are_persisted_without_losing_rows(
    extracts_client, monkeypatch
) -> None:
    original_analyse = PDFPipeline.analyse

    def repeated_line_number(self, *args, **kwargs):
        analysis = original_analyse(self, *args, **kwargs)
        if not analysis.invoices:
            return analysis
        lines = analysis.invoices[0].line_items
        assert len(lines) > 1
        lines[1].sequence_no = lines[0].sequence_no
        return analysis

    monkeypatch.setattr(PDFPipeline, "analyse", repeated_line_number)
    _process_pair(extracts_client, 1)
    with _session(extracts_client) as session:
        invoice = session.scalars(select(Invoice)).one()
        lines = _lines(session, invoice)
        assert len(lines) == len(invoice.extraction_payload_json["line_items"])
        assert all(line.sequence_no >= 1 for line in lines)
        assert len({line.sequence_no for line in lines}) == len(lines)
        raw_lines = invoice.extraction_payload_json["line_items"]
        assert raw_lines[0]["sequence_no"] == raw_lines[1]["sequence_no"]


def test_database_flush_failure_marks_document_failed_and_retryable(
    extracts_client, monkeypatch
) -> None:
    original_analyse = PDFPipeline.analyse

    def invalid_confidence(self, *args, **kwargs):
        analysis = original_analyse(self, *args, **kwargs)
        analysis.invoices[0].line_items[0].source.confidence = 1.5
        return analysis

    monkeypatch.setattr(PDFPipeline, "analyse", invalid_confidence)
    reference = "EXTRACTS-BAD-FLUSH"
    created = extracts_client.post(
        "/api/v1/claims",
        json={"case_reference": reference, "claim_number": reference, "created_by": "pytest"},
    )
    assert created.status_code == 201, created.text
    filename = PAIRS[1][1]
    uploaded = extracts_client.post(
        f"/api/v1/claims/{reference}/documents",
        files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
        data={"role": "current"},
    )
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()["id"]
    processed = extracts_client.post(f"/api/v1/documents/{document_id}/process")
    assert processed.status_code == 422, processed.text
    receipt = extracts_client.get(f"/api/v1/claims/{reference}/documents").json()
    row = next(item for item in receipt if item["id"] == document_id)
    assert row["status"] == "failed"
    assert row["can_retry_extraction"] is True
    assert row["processing_error"]
    with _session(extracts_client) as session:
        assert session.get(Document, document_id).upload_status.value == "failed"
        assert session.scalars(select(Invoice).where(Invoice.document_id == document_id)).all() == []


def _money(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _lines(session: Session, invoice: Invoice) -> list[InvoiceLineItem]:
    return list(
        session.scalars(
            select(InvoiceLineItem)
            .where(InvoiceLineItem.invoice_id == invoice.id)
            .order_by(InvoiceLineItem.sequence_no)
        ).all()
    )


def _operations(session: Session, assessment: EngineerAssessment) -> list[AssessmentOperation]:
    return list(
        session.scalars(
            select(AssessmentOperation)
            .where(AssessmentOperation.assessment_id == assessment.id)
            .order_by(AssessmentOperation.sequence_no)
        ).all()
    )


def test_format_1_pair_persists_every_extract_column(extracts_client) -> None:
    _process_pair(extracts_client, 1)

    with _session(extracts_client) as session:
        invoice = session.scalars(select(Invoice)).one()
        assert invoice.invoice_number == "343653726836/1~3538"
        assert invoice.claim_reference == "245338996/1"
        # The repairer's invoice prints no policy number; the assessment does,
        # and the gap-fill writes it onto the invoice once the pair is linked.
        # What was extracted is therefore checked on the extract itself.
        assert invoice.extraction_payload_json["header"]["policy_number"] is None
        assert invoice.policy_number == "PH"
        assert _money(invoice.paint_net) == Decimal("1029.57")
        assert _money(invoice.other_net) == Decimal("136.32")
        assert _money(invoice.labour_net) == Decimal("2509.20")
        assert _money(invoice.parts_net) == Decimal("1237.50")
        assert _money(invoice.gross_total) == Decimal("5895.11")

        lines = _lines(session, invoice)
        section_totals = [line for line in lines if line.is_section_total]
        itemised = [line for line in lines if not line.is_section_total]
        assert len(itemised) == 20
        assert len(section_totals) == 2
        assert all(line.line_item_type for line in lines)
        assert all(line.raw_category for line in lines)
        assert {line.line_item_type for line in section_totals} == {
            "labour",
            "paint_materials",
        }

        assessment = session.scalars(select(EngineerAssessment)).one()
        assert assessment.assessment_number == "D7576879"
        assert assessment.claim_reference == "245338996/1"
        assert assessment.policy_number == "PH"
        assert assessment.registration == "AB12XYZ"
        assert assessment.vehicle_make == "HYUNDAI"
        assert assessment.vehicle_model == "140 SE Nav"
        assert _money(assessment.labour_rate) == Decimal("38.00")
        assert _money(assessment.paint_rate) == Decimal("68.00")
        assert _money(assessment.gross_total) == Decimal("5895.11")

        operations = _operations(session, assessment)
        assert len(operations) >= 60
        assert {operation.category for operation in operations} == {
            "labour",
            "paint",
            "parts",
            "extras",
        }
        assert all(operation.raw_category for operation in operations)

        payload = assessment.extraction_payload_json
        # Printed and row figures are kept side by side and never reconciled.
        assert payload["printed_work_units"]["labour"]["total_work_units"] == "218"
        assert payload["row_work_units"]["labour"] == "101"
        # Namespaced: the LLM tiers write their own "operations" key with an
        # entirely different shape, so the deterministic detail has its own.
        assert payload["deterministic_operations"][0]["price_derived"] is True

        disagreements = session.scalars(
            select(ClaimConsistencyFinding).where(
                ClaimConsistencyFinding.finding_code
                == "ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT",
                ClaimConsistencyFinding.source_entity_id == assessment.id,
            )
        ).all()
        work_units = next(
            finding for finding in disagreements if finding.field_name == "labour work units"
        )
        # Medium severity: the handler must see it, nothing is corrected or blocked.
        assert work_units.severity == Severity.WARNING
        assert work_units.expected_value == "218"
        assert work_units.observed_value == "101"
        assert "218" in work_units.explanation and "101" in work_units.explanation

        # The two rolled-up rows must not have produced a single failure.
        findings = session.scalars(
            select(MathFinding).where(MathFinding.invoice_id == invoice.id)
        ).all()
        failures = {
            finding.check_code for finding in findings if finding.status == CheckStatus.FAIL
        }
        assert failures == set()


def test_format_2_rolled_up_invoice_and_its_labour_schedule(extracts_client) -> None:
    documents = _process_pair(extracts_client, 2)

    invoice_document = documents["DL_Invoice_2_request_for_payment.docx"]
    assert invoice_document["manual_review"] is True
    assert invoice_document["manual_review_reason"].startswith(
        "Line-item information is not available"
    )

    with _session(extracts_client) as session:
        invoice = session.scalars(select(Invoice)).one()
        assert invoice.policy_number == "103466899"
        assert invoice.claim_reference == "123456/1"
        assert _money(invoice.other_net) == Decimal("627.00")

        lines = _lines(session, invoice)
        assert [line for line in lines if not line.is_section_total] == []
        assert {
            line.line_item_type: _money(line.line_total_net)
            for line in lines
            if line.is_section_total
        } == {
            "parts": Decimal("448.91"),
            "paint_materials": Decimal("1034.02"),
            "labour": Decimal("2008.00"),
            "extras": Decimal("627.00"),
        }

        # The reference the invoice prints matches no assessment on the paired
        # report, so it is display evidence in metadata and never a pairing key.
        document = session.get(Document, invoice.document_id)
        assert document.metadata_json["assessment_reference"] == "BOY1537"

        assessment = session.scalars(select(EngineerAssessment)).one()
        operations = _operations(session, assessment)
        assert len(operations) == 17
        assert {operation.category for operation in operations} == {"labour"}
        assert {_money(operation.unit_price_net) for operation in operations} == {
            Decimal("80.00")
        }
        assert sum(
            (_money(operation.total_net) for operation in operations), Decimal("0")
        ) == Decimal("1112.00")


def test_format_2_schedule_continuation_page_is_stored_as_assessment(
    extracts_client,
) -> None:
    """The report's labour schedule runs onto page 2, which carries no
    identity marker and classifies as OTHER. It is reclassified before
    anything reads it, so the page type the document stores, the page the
    operations point at, and the pages the parser read are one and the same."""

    _process_pair(extracts_client, 2)

    with _session(extracts_client) as session:
        assessment = session.scalars(select(EngineerAssessment)).one()
        pages = list(
            session.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == assessment.document_id)
                .order_by(DocumentPage.page_number)
            ).all()
        )
        continuation = next(page for page in pages if page.page_number == 2)
        assert continuation.page_type == PageType.ENGINEER_ASSESSMENT

        operations = _operations(session, assessment)
        # Every operation is sourced from a page the document also calls an
        # assessment page -- 15 of the 17 from the continuation.
        assert all(
            session.get(DocumentPage, operation.source_page_id).page_type
            == PageType.ENGINEER_ASSESSMENT
            for operation in operations
        )
        assert (
            sum(
                1
                for operation in operations
                if operation.source_page_id == continuation.id
            )
            == 15
        )


def test_format_2_section_totals_are_never_mapped_priced_or_compared(
    extracts_client,
) -> None:
    """Pair 2's invoice is rolled up into four section totals and nothing
    else. A section total is the value of a whole section, never a priced
    repair item, so comparison must produce no mapping and no price
    comparison for one -- here that leaves nothing comparable at all."""

    _process_pair(extracts_client, 2)

    with _session(extracts_client) as session:
        case = session.scalars(
            select(Case).where(Case.case_reference == "EXTRACTS-2")
        ).one()
        section_total_ids = {
            line.id
            for line in session.scalars(
                select(InvoiceLineItem).where(InvoiceLineItem.is_section_total.is_(True))
            ).all()
        }
        assert len(section_total_ids) == 4

        with pytest.raises(ValueError, match="Extraction is incomplete"):
            run_case_comparison(session, case)
        session.rollback()

        mapped = set(session.scalars(select(OntologyMapping.invoice_line_item_id)).all())
        compared = set(session.scalars(select(PriceComparison.invoice_line_item_id)).all())
        assert section_total_ids & mapped == set()
        assert section_total_ids & compared == set()


def test_no_historical_observation_is_ever_written_from_a_section_total(
    extracts_client,
) -> None:
    """Governance: a rolled-up section total that somehow reached a mapping
    must still never become a historical observation. One in the P90 history
    would price every future claim for that item against a whole section."""

    _process_pair(extracts_client, 1)

    with _session(extracts_client) as session:
        case = session.scalars(
            select(Case).where(Case.case_reference == "EXTRACTS-1")
        ).one()
        invoice = session.scalars(select(Invoice)).one()
        section_totals = [
            line for line in _lines(session, invoice) if line.is_section_total
        ]
        assert section_totals

        version = session.scalars(
            select(OntologyVersion).where(OntologyVersion.sequence_number == 0)
        ).one()
        ontology_item = OntologyItem(
            canonical_code="TEST-SECTION-TOTAL",
            canonical_name="Any mapped item",
            item_type=LineItemKind.PART,
            category="body",
            unit="each",
            created_by="pytest.handler",
            created_in_version_id=version.id,
        )
        session.add(ontology_item)
        mapping_run = MappingRun(
            processing_run_id=case.current_processing_run_id,
            ontology_version_id=version.id,
            prompt_version="test",
            status=RunStatus.SUCCEEDED,
        )
        session.add(mapping_run)
        session.flush()
        for line in section_totals:
            session.add(
                OntologyMapping(
                    mapping_run_id=mapping_run.id,
                    invoice_line_item_id=line.id,
                    selected_ontology_item_id=ontology_item.id,
                    decision=MappingDecision.MANUAL,
                    final_status=MappingStatus.APPROVED,
                )
            )
        session.commit()

        created = sync_finalised_case_to_benchmarks(session, case)
        session.flush()

        observed_line_ids = set(
            session.scalars(select(HistoricalObservation.source_line_item_id)).all()
        )
        assert created == 0
        assert observed_line_ids & {line.id for line in section_totals} == set()


def test_forced_reprocess_does_not_duplicate_printed_total_findings(
    extracts_client,
) -> None:
    """A forced reprocess deletes the engineer_assessments row and writes a
    new one. Nothing has a foreign key onto it from the findings table, so
    without an explicit sweep the disagreements accumulate on every run and
    the old ones point at an id that no longer resolves."""

    _process_pair(extracts_client, 1)

    def _findings() -> list[ClaimConsistencyFinding]:
        with _session(extracts_client) as session:
            return list(
                session.scalars(
                    select(ClaimConsistencyFinding).where(
                        ClaimConsistencyFinding.finding_code
                        == "ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT"
                    )
                ).all()
            )

    first = _findings()
    assert first

    with _session(extracts_client) as session:
        assessment = session.scalars(select(EngineerAssessment)).one()
        document_id = assessment.document_id

    for _ in range(2):
        with _session(extracts_client) as session:
            document = session.get(Document, document_id)
            metadata = dict(document.metadata_json or {})
            metadata["reprocess_required"] = True
            document.metadata_json = metadata
            session.commit()
        processed = extracts_client.post(
            f"/api/v1/documents/{document_id}/process", params={"force": True}
        )
        assert processed.status_code == 200, processed.text

    repeated = _findings()
    assert len(repeated) == len(first)

    with _session(extracts_client) as session:
        live = session.scalars(select(EngineerAssessment.id)).all()
    # No finding is left pointing at an assessment row that has been deleted.
    assert {finding.source_entity_id for finding in repeated} <= set(live)


def test_format_7_invoice_without_a_vehicle_is_not_manual_review(extracts_client) -> None:
    documents = _process_pair(extracts_client, 7)

    invoice_document = documents["DL_Repair_Invoice_format_7.docx"]
    assert invoice_document["manual_review"] is False
    assert invoice_document["manual_review_reason"] is None

    with _session(extracts_client) as session:
        invoice = session.scalars(select(Invoice)).one()
        header = invoice.extraction_payload_json["header"]
        # The invoice itself prints neither; only the assessment carries them,
        # and their absence is not on its own a reason for manual review.
        assert header["vehicle_make"] is None
        assert header["vehicle_model"] is None
        assert invoice.claim_reference == "426953180/3"
        assert _money(invoice.paint_net) == Decimal("785.00")
        assert _money(invoice.other_net) == Decimal("104.00")

        assessment = session.scalars(select(EngineerAssessment)).one()
        assert assessment.assessment_number == "T4592861"
        assert assessment.registration == "JK21MNO"
        assert len(_operations(session, assessment)) >= 60


@pytest.mark.parametrize("pair_id", sorted(PAIRS))
def test_no_section_total_row_enters_a_row_sum(extracts_client, pair_id: int) -> None:
    _process_pair(extracts_client, pair_id)

    with _session(extracts_client) as session:
        for invoice in session.scalars(select(Invoice)).all():
            lines = _lines(session, invoice)
            itemised = [line for line in lines if not line.is_section_total]
            findings = session.scalars(
                select(MathFinding).where(MathFinding.invoice_id == invoice.id)
            ).all()

            # Line-level arithmetic is raised against itemised rows only: a
            # section total has no quantity or unit price to reconcile.
            assert {
                finding.line_item_id for finding in findings if finding.line_item_id
            } == {line.id for line in itemised}

            # A row sum can never exceed the itemised rows it is drawn from;
            # including a section total is exactly what would push it over.
            itemised_total = sum(
                (
                    _money(line.line_total_net)
                    for line in itemised
                    if line.line_total_net is not None
                ),
                Decimal("0"),
            )
            for finding in findings:
                if finding.check_code not in ROW_SUM_CHECKS:
                    continue
                if finding.expected_value is None:
                    assert finding.status == CheckStatus.NOT_APPLICABLE
                    continue
                assert Decimal(finding.expected_value) <= itemised_total
