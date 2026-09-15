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
from app.enums import CheckStatus, Severity
from app.init_db import initialize_database
from app.main import app
from app.models import (
    AssessmentOperation,
    ClaimConsistencyFinding,
    Document,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
    MathFinding,
)

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
        assert payload["operations"][0]["price_derived"] is True

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
