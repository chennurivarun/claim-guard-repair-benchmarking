"""Acceptance: Audatex-style ("Auda 7") documents never dead-end.

Fixtures in sample-data/auda-style/ replicate the client's real Auda 7 set
(regenerate with backend/scripts/build_auda_fixtures.py):
- a rolled-up calculation invoice (totals only, no line items),
- an Audatex Full Report (summary, labour work units, EXTRAS charges, and a
  priced PARTS schedule),
- a photo-page PDF (image-only pages, as uploaded from a phone).

The intake contract under test: processing succeeds, nothing is FAILED or
discarded, every manual-review document carries a stored briefing, and an
authorised Audatex assessment's priced PARTS/EXTRAS/LABOUR pages stay
assessment evidence rather than becoming invoice units, even in
deterministic, LLM-free mode (see test_page_classification.py for the
identity-gate unit tests, and the mixed-bundle rescue path exercised in
test_mixed_and_rotated_bundles.py, which is unaffected by this).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.extraction.schemas import PageType
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


def test_audatex_full_report_keeps_priced_pages_as_assessment_evidence(tmp_path):
    """The previous assertion here was deliberately reversed on 2026-09-15.

    Until this change, this test (then named
    ``test_audatex_full_report_extracts_priced_pages_as_invoice_units``)
    asserted that an Audatex "Full Report"'s priced PARTS and EXTRAS pages
    were flipped to INVOICE and their rows persisted as invoice line items.
    The client requires the opposite: pages belonging to an authorised
    assessment must remain assessment evidence and must never become
    invoice units, however many priced rows they contain. See
    ``_ASSESSMENT_IDENTITY_PATTERN`` and the identity gate added to
    ``_reclassify_priced_assessment_pages`` in
    backend/app/extraction/pdf_pipeline.py, and the Risks bullet in
    invoice-assessment-matching-plan.md ("Task 6 reverses a green
    acceptance assertion") which records this as an intended change.
    """

    from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig

    analysis = PDFPipeline(PipelineConfig(ocr_enabled=False)).analyse(
        FIXTURES / "Auda7_full_report.pdf", tmp_path / "pages"
    )

    # The PARTS page's part numbers must never surface as an invoice line,
    # on this page or any other -- the priced schedule stays assessment
    # evidence rather than becoming a benchmarkable invoice unit.
    invoice_part_numbers = {
        line.part_number
        for invoice in analysis.invoices
        for line in invoice.line_items
        if line.part_number
    }
    assert not {"0019846529", "0008111122", "9068110198"} & invoice_part_numbers
    assert not any(invoice.has_benchmarkable_part_lines() for invoice in analysis.invoices)

    # Every page of the document (Summary/LABOUR/EXTRAS/PARTS) stays
    # ENGINEER_ASSESSMENT; none of it is reclassified to INVOICE.
    assert [page.page_type for page in analysis.pages] == [
        PageType.ENGINEER_ASSESSMENT
    ] * len(analysis.pages)

    # TODO(task-4): once engineer_assessment_parser reads PARTS/EXTRAS/LABOUR/
    # PAINT tables (today it only reads governed `OP|` rows, so this document
    # yields zero ParsedOperation rows and no EngineerAssessment is
    # persisted), assert that part numbers 0019846529 / 0008111122 /
    # 9068110198 arrive as AssessmentOperation rows with
    # line_item_type == "parts" and source_page_id pointing at page 4.


@pytest.mark.slow
def test_photo_pages_reach_manual_review_with_briefing(auda_client):
    document = _process(auda_client, "Auda7_photo_pages.pdf")
    assert document["status"] == "ready"
    assert document["manual_review"] is True
    assert document["review_briefing"]
