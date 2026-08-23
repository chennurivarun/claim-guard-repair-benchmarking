"""Acceptance: Audatex-style ("Auda 7") documents never dead-end.

Fixtures in sample-data/auda-style/ replicate the client's real Auda 7 set
(regenerate with backend/scripts/build_auda_fixtures.py):
- a rolled-up calculation invoice (totals only, no line items),
- an Audatex Full Report (summary, labour work units, EXTRAS charges, and a
  priced PARTS schedule),
- a photo-page PDF (image-only pages, as uploaded from a phone).

The intake contract under test: processing succeeds, nothing is FAILED or
discarded, every manual-review document carries a stored briefing, and mixed
documents (assessment content plus genuinely priced pages) yield invoice
units for their priced pages even in deterministic, LLM-free mode.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.init_db import initialize_database
from app.main import app

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "auda-style"


@pytest.fixture
def auda_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auda.db'}",
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
        client.post(
            "/api/v1/claims",
            json={
                "case_reference": "AUDA-ACCEPT",
                "claim_number": "2025/ABC/12345",
                "created_by": "pytest.handler",
            },
        )
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def _process(client: TestClient, filename: str) -> dict:
    pdf = FIXTURES / filename
    uploaded = client.post(
        "/api/v1/claims/AUDA-ACCEPT/documents",
        files={"file": (filename, pdf.read_bytes(), "application/pdf")},
        data={"role": "current"},
    )
    assert uploaded.status_code == 200, uploaded.text
    processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
    assert processed.status_code == 200, processed.text
    return processed.json()["document"]


def test_rolled_up_calculation_invoice_is_retained_with_briefing(auda_client):
    document = _process(auda_client, "Auda7_format_invoice.pdf")
    assert document["status"] == "ready"
    assert document["kind"] == "repair_invoice"
    assert document["invoice_units"] >= 1
    assert document["manual_review"] is True
    assert "rolled up" in document["manual_review_reason"]
    assert document["review_briefing"], "manual-review document must carry a briefing"


def test_audatex_full_report_extracts_priced_pages_as_invoice_units(auda_client):
    """Deterministic mode: the mixed Full Report keeps its assessment kind but
    its priced PARTS and EXTRAS pages become invoice units with correct
    page provenance instead of dead-ending in manual review with zero units."""

    document = _process(auda_client, "Auda7_full_report.pdf")
    assert document["status"] == "ready"
    assert document["kind"] == "engineer_assessment"
    assert document["invoice_units"] >= 1

    invoices = auda_client.get("/api/v1/claims/AUDA-ACCEPT/invoices").json()
    document_invoices = [
        invoice for invoice in invoices if invoice["document_id"] == document["id"]
    ]
    assert document_invoices, "priced pages must be persisted as invoice units"
    lines = [line for invoice in document_invoices for line in invoice["lines"]]

    parts_lines = [line for line in lines if line["part_number"]]
    assert parts_lines, "parts schedule lines must carry their part numbers"
    assert {"0019846529", "0008111122", "9068110198"} <= {
        line["part_number"] for line in parts_lines
    }
    assert all(Decimal(str(line["line_total_net"])) > 0 for line in parts_lines)
    # Page provenance: every part-numbered line comes from the PARTS page (4).
    assert {line["source_page_number"] for line in parts_lines} == {4}

    # ExtractedLine.benchmarkable semantics: part kind or part number, positive net.
    benchmarkable = [
        line
        for line in lines
        if (line["kind"] == "part" or line["part_number"])
        and line["line_total_net"] is not None
        and Decimal(str(line["line_total_net"])) > 0
    ]
    assert benchmarkable, "parts-page lines must be benchmarkable"

    # The assessment side may still need manual review (the labour pages hold
    # no governed operation rows); when it does, the briefing must exist.
    if document["manual_review"]:
        assert document["review_briefing"]


def test_full_report_parts_lines_are_benchmarkable_in_deterministic_pipeline(tmp_path):
    """Pipeline-level check of ExtractedLine.benchmarkable on the parts page."""

    from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig

    analysis = PDFPipeline(PipelineConfig(ocr_enabled=False)).analyse(
        FIXTURES / "Auda7_full_report.pdf", tmp_path / "pages"
    )
    part_lines = [
        line
        for invoice in analysis.invoices
        for line in invoice.line_items
        if line.part_number
    ]
    assert part_lines
    assert all(line.benchmarkable for line in part_lines)
    assert any(invoice.has_benchmarkable_part_lines() for invoice in analysis.invoices)


@pytest.mark.slow
def test_photo_pages_reach_manual_review_with_briefing(auda_client):
    document = _process(auda_client, "Auda7_photo_pages.pdf")
    assert document["status"] == "ready"
    assert document["manual_review"] is True
    assert document["review_briefing"]
