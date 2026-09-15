"""``GET /claims/{case_reference}/extracts`` against the three client pairs.

Reuses the upload/process helpers from ``test_extracts_persistence.py`` --
this file only exercises the read-only projection endpoint, not extraction or
persistence, which are already covered there.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.database import get_db
from app.init_db import initialize_database
from app.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PAIRS: dict[int, tuple[str, str]] = {
    1: ("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_1.docx"),
    2: ("DL_Auda_format_2_assessment.docx", "DL_Invoice_2_request_for_payment.docx"),
    7: ("DL_Auda_format_7_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
}

MANDATORY_INVOICE_FIELDS = (
    "invoice_number",
    "vehicle_make",
    "vehicle_model",
    "vehicle_registration",
    "claim_number",
    "policy_number",
)
MANDATORY_ASSESSMENT_FIELDS = (
    "assessment_number",
    "vehicle_make",
    "vehicle_model",
    "vehicle_registration",
    "claim_number",
    "policy_number",
)


@pytest.fixture
def extracts_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'extracts_api.db'}",
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


def _process_pair(client: TestClient, pair_id: int) -> str:
    """Upload and process one client pair; return the case reference."""

    reference = f"EXTRACTS-API-{pair_id}"
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": f"2026/EXTRACTS-API/{pair_id}",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text
    for filename in PAIRS[pair_id]:
        uploaded = client.post(
            f"/api/v1/claims/{reference}/documents",
            files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
            data={"role": "current"},
        )
        assert uploaded.status_code == 200, uploaded.text
        processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
        assert processed.status_code == 200, processed.text
    return reference


@pytest.mark.parametrize("pair_id", sorted(PAIRS))
def test_extracts_endpoint_returns_mandatory_columns_non_null(extracts_client, pair_id: int):
    reference = _process_pair(extracts_client, pair_id)

    response = extracts_client.get(f"/api/v1/claims/{reference}/extracts")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert set(payload) == {"invoice_extracts", "assessment_extracts", "section_breakdowns"}
    assert payload["invoice_extracts"], "expected at least one invoice extract"
    assert payload["assessment_extracts"], "expected at least one assessment extract"

    for invoice_extract in payload["invoice_extracts"]:
        for field in MANDATORY_INVOICE_FIELDS:
            assert invoice_extract[field] not in (None, ""), (
                f"pair {pair_id}: invoice field {field!r} is null: {invoice_extract}"
            )
        assert isinstance(invoice_extract["lines"], list)

    for assessment_extract in payload["assessment_extracts"]:
        for field in MANDATORY_ASSESSMENT_FIELDS:
            assert assessment_extract[field] not in (None, ""), (
                f"pair {pair_id}: assessment field {field!r} is null: {assessment_extract}"
            )
        assert assessment_extract["lines"], "expected at least one assessment line"
        for line in assessment_extract["lines"]:
            assert line["line_item_type"], f"assessment line missing line_item_type: {line}"


def test_extracts_arrays_are_never_merged(extracts_client):
    reference = _process_pair(extracts_client, 1)

    response = extracts_client.get(f"/api/v1/claims/{reference}/extracts")
    assert response.status_code == 200, response.text
    payload = response.json()

    invoice_numbers = {extract["invoice_number"] for extract in payload["invoice_extracts"]}
    assessment_numbers = {extract["assessment_number"] for extract in payload["assessment_extracts"]}
    # The two identity spaces are disjoint in the client's own data, and the
    # payload keeps them in two separate top-level arrays regardless.
    assert invoice_numbers.isdisjoint(assessment_numbers)
    assert "invoice_extracts" in payload and "assessment_extracts" in payload
    assert isinstance(payload["invoice_extracts"], list)
    assert isinstance(payload["assessment_extracts"], list)


def test_format_7_invoice_gains_gap_filled_identity_with_field_source(extracts_client):
    reference = _process_pair(extracts_client, 7)

    response = extracts_client.get(f"/api/v1/claims/{reference}/extracts")
    assert response.status_code == 200, response.text
    payload = response.json()

    invoice_extract = payload["invoice_extracts"][0]
    # Format 7's invoice prints no vehicle make/model; both are gap-filled
    # from the paired assessment, and the fill is attributed in field_sources.
    assert invoice_extract["vehicle_make"] == "HYUNDAI"
    assert invoice_extract["vehicle_model"]
    field_sources = invoice_extract["field_sources"]
    assert "make" in field_sources
    assert "model" in field_sources
    assert field_sources["make"]["label"] == "Filled from engineer assessment"


def test_format_2_invoice_has_four_section_totals_and_labour_breakdown_mismatch(
    extracts_client,
):
    reference = _process_pair(extracts_client, 2)

    response = extracts_client.get(f"/api/v1/claims/{reference}/extracts")
    assert response.status_code == 200, response.text
    payload = response.json()

    invoice_extract = payload["invoice_extracts"][0]
    section_total_lines = [line for line in invoice_extract["lines"] if line["is_section_total"]]
    assert len(section_total_lines) == 4

    labour_breakdowns = [
        breakdown
        for breakdown in payload["section_breakdowns"]
        if breakdown["line_item_type"] == "labour"
        and breakdown["invoice_number"] == invoice_extract["invoice_number"]
    ]
    assert len(labour_breakdowns) == 1
    labour_breakdown = labour_breakdowns[0]
    assert labour_breakdown["matches"] is False
    assert Decimal(labour_breakdown["difference"]) == Decimal("896.00")
    assert len(labour_breakdown["rows"]) == 17


def test_unknown_case_returns_404(extracts_client):
    response = extracts_client.get("/api/v1/claims/DOES-NOT-EXIST/extracts")
    assert response.status_code == 404
