"""Pairing, gap-fill and the total-to-section breakdown, on the client pairs.

Everything here is deterministic: no extractor is configured in the test
settings, so the native parsers do the work and the three client `.docx`
pairs are uploaded through the real API exactly as
`tests/integration/test_extracts_persistence.py` does.

The rules under test are identity rules, so the interesting cases are the
negative ones: formats 1 and 7 print the *same* invoice number
("343653726836/1~3538") for two different claims, and format 2's invoice
prints an "Assessment Ref" ("BOY1537") that matches nothing on the report it
arrives with. Neither may ever become a pairing key.
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
from app.domain.normalisation import normalise_identifier
from app.init_db import initialize_database
from app.main import app
from app.models import Document, EngineerAssessment, Invoice
from app.services.engineer_assessment import (
    engineer_assessment_payload,
    run_case_gap_fill,
    section_breakdown_for_invoice,
)
from app.services.vehicle_classification import normalise_registration

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PAIRS: dict[int, tuple[str, str]] = {
    1: ("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_1.docx"),
    2: ("DL_Auda_format_2_assessment.docx", "DL_Invoice_2_request_for_payment.docx"),
    7: ("DL_Auda_format_7_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
}


def test_normalise_identifier_strips_every_separator() -> None:
    assert normalise_identifier("245338996/1") == "2453389961"
    assert normalise_identifier("AB12 XYZ") == "AB12XYZ"
    assert normalise_identifier("PL-739284") == "PL739284"
    assert normalise_identifier("  ") is None
    assert normalise_identifier("--") is None
    assert normalise_identifier(None) is None


def test_registration_normalisation_has_one_implementation() -> None:
    for value in ("ab12 xyz", "AB12-XYZ", None, ""):
        assert normalise_registration(value) == normalise_identifier(value)


@pytest.fixture
def pairing_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pairing.db'}",
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


def _process_pair(client: TestClient, pair_id: int, *, files: tuple[str, ...] | None = None) -> str:
    """Upload and process one client pair (or an arbitrary mix); return its case reference."""

    reference = f"PAIRING-{pair_id}"
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": f"2026/PAIRING/{pair_id}",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text
    for filename in files or PAIRS[pair_id]:
        uploaded = client.post(
            f"/api/v1/claims/{reference}/documents",
            files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
            data={"role": "current"},
        )
        assert uploaded.status_code == 200, uploaded.text
        processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
        assert processed.status_code == 200, processed.text
    return reference


def _session(client: TestClient) -> Session:
    return Session(client.engine, expire_on_commit=False)


def _only_assessment(session: Session) -> EngineerAssessment:
    return session.scalars(select(EngineerAssessment)).one()


def _only_invoice(session: Session) -> Invoice:
    return session.scalars(select(Invoice)).one()


@pytest.mark.parametrize(
    ("pair_id", "expected_reasons", "expected_confidence"),
    [
        (
            1,
            [
                "registration exact match",
                "claim reference exact match",
                # "PH" is printed on the assessment only, so the key is not
                # comparable -- absence is never a conflict.
                "policy number not printed on the invoice",
            ],
            2 / 3,
        ),
        (
            2,
            [
                "registration exact match",
                "claim reference exact match",
                "policy number exact match",
            ],
            1.0,
        ),
        (
            7,
            [
                "registration exact match",
                "claim reference exact match",
                "policy number not printed on the invoice",
            ],
            2 / 3,
        ),
    ],
)
def test_client_pairs_link_on_their_printed_identities(
    pairing_client, pair_id: int, expected_reasons: list[str], expected_confidence: float
) -> None:
    _process_pair(pairing_client, pair_id)

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert assessment.pair_reasons_json == expected_reasons
        assert assessment.pair_confidence == pytest.approx(expected_confidence)
        assert not any("conflict" in reason for reason in assessment.pair_reasons_json)


def test_neither_the_invoice_number_nor_the_assessment_reference_is_a_key(
    pairing_client,
) -> None:
    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        document = session.get(Document, invoice.document_id)
        # The reference is captured for display and matches nothing on the report.
        assert document.metadata_json["assessment_reference"] == "BOY1537"
        reasons = " ".join(_only_assessment(session).pair_reasons_json)
        assert "BOY1537" not in reasons
        assert invoice.invoice_number not in reasons


def test_a_claim_conflict_rejects_a_pair_that_shares_an_invoice_number(
    pairing_client,
) -> None:
    """Format 1's assessment must not attach to format 7's invoice.

    Both invoices print "343653726836/1~3538". Only the claim reference (and
    here the registration) tells the two claims apart, and a conflict on a key
    printed by both documents is fatal however the other keys read.
    """

    _process_pair(
        pairing_client,
        17,
        files=("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        assert invoice.invoice_number == "343653726836/1~3538"
        assert assessment.claim_reference == "245338996/1"
        assert invoice.claim_reference == "426953180/3"
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        # Nothing was filled onto an invoice belonging to another claim.
        assert invoice.policy_number is None
        assert (session.get(Document, invoice.document_id).metadata_json or {}).get(
            "field_sources"
        ) in (None, {})


def test_a_claim_conflict_is_fatal_even_when_the_registration_matches(
    pairing_client,
) -> None:
    """The claim reference alone rejects the pair; the other keys cannot rescue it."""

    _process_pair(
        pairing_client,
        18,
        files=("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        invoice.vehicle.registration = assessment.registration
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert any("claim reference conflict" in reason for reason in assessment.pair_reasons_json)


def test_invoice_seven_takes_its_vehicle_from_the_assessment_without_manual_review(
    pairing_client,
) -> None:
    reference = _process_pair(pairing_client, 7)

    documents = pairing_client.get(f"/api/v1/claims/{reference}/documents")
    assert documents.status_code == 200, documents.text
    invoice_document = next(
        entry
        for entry in documents.json()
        if entry["filename"] == "DL_Repair_Invoice_format_7.docx"
    )
    # A missing make/model is filled from the assessment, not escalated.
    assert invoice_document["manual_review"] is False
    assert invoice_document["manual_review_reason"] is None

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        # The invoice itself printed neither.
        header = invoice.extraction_payload_json["header"]
        assert header["vehicle_make"] is None
        assert header["vehicle_model"] is None

        assert invoice.vehicle.make == "HYUNDAI"
        assert invoice.vehicle.model == "140 SE Nav"
        assert invoice.policy_number == "PL-739284"

        sources = session.get(Document, invoice.document_id).metadata_json["field_sources"]
        for field, value in (
            ("make", "HYUNDAI"),
            ("model", "140 SE Nav"),
            ("policy_number", "PL-739284"),
        ):
            assert sources[field] == {
                "document_id": assessment.document_id,
                "label": "Filled from engineer assessment",
                "value": value,
            }
        # claim_reference was printed on the invoice, so it was never filled.
        assert "claim_reference" not in sources


def test_the_gap_fill_sweep_is_idempotent_and_keeps_handler_corrections(
    pairing_client,
) -> None:
    _process_pair(pairing_client, 7)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        case_id = invoice.case_id
        run_case_gap_fill(session, case_id)
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()

        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        sources = session.get(Document, invoice.document_id).metadata_json["field_sources"]
        assert assessment.pair_status == "paired"
        assert invoice.vehicle.make == "HYUNDAI"
        assert invoice.policy_number == "PL-739284"
        assert sorted(sources) == ["make", "mileage", "model", "policy_number", "vin"]

        # A handler correction outranks the assessment and is never reverted.
        invoice.vehicle.make = "HYUNDAI (corrected)"
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()
        invoice = _only_invoice(session)
        sources = session.get(Document, invoice.document_id).metadata_json["field_sources"]
        assert invoice.vehicle.make == "HYUNDAI (corrected)"
        assert "make" not in sources


def test_format_one_totals_resolve_to_their_assessment_sections(pairing_client) -> None:
    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        breakdowns = {
            entry["line_item_type"]: entry
            for entry in section_breakdown_for_invoice(session, invoice)
        }
        assert sorted(breakdowns) == ["labour", "paint_materials"]

        labour = breakdowns["labour"]
        assert Decimal(labour["invoice_total"]) == Decimal("2509.20")
        assert Decimal(labour["assessment_total"]) == Decimal("2509.20")
        assert labour["matches"] is True
        assert Decimal(labour["difference"]) == Decimal("0.00")
        # One invoice "Total Labour" pays for both work-unit sections.
        assert len(labour["rows"]) == 41
        categories = [row["category"] for row in labour["rows"]]
        assert categories.count("labour") == 25
        assert categories.count("paint") == 16
        assert all(row["description"] for row in labour["rows"])
        assert any(row["work_units"] for row in labour["rows"])

        materials = breakdowns["paint_materials"]
        assert Decimal(materials["assessment_total"]) == Decimal("1029.57")
        assert materials["matches"] is True


def test_format_two_reports_its_labour_gap_without_blocking(pairing_client) -> None:
    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        breakdowns = {
            entry["line_item_type"]: entry
            for entry in section_breakdown_for_invoice(session, invoice)
        }
        assert sorted(breakdowns) == ["extras", "labour", "paint_materials", "parts"]

        labour = breakdowns["labour"]
        # This assessment prints panel labour only, so the invoice bills more
        # than the report accounts for. It is reported, never enforced.
        assert Decimal(labour["invoice_total"]) == Decimal("2008.00")
        assert Decimal(labour["assessment_total"]) == Decimal("1112.00")
        assert labour["matches"] is False
        assert Decimal(labour["difference"]) == Decimal("896.00")
        assert len(labour["rows"]) == 17

        for line_item_type in ("parts", "paint_materials", "extras"):
            entry = breakdowns[line_item_type]
            # Not captured is not the same answer as does not match.
            assert entry["assessment_total"] is None
            assert entry["matches"] is None
            assert entry["difference"] is None
            assert entry["rows"] == []


def test_the_breakdown_reaches_the_assessment_payload(pairing_client) -> None:
    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        payload = engineer_assessment_payload(_only_assessment(session), session)
        types = {entry["line_item_type"] for entry in payload["section_breakdowns"]}
        assert types == {"labour", "paint_materials"}
        assert payload["field_sources"]["policy_number"]["value"] == "PH"
