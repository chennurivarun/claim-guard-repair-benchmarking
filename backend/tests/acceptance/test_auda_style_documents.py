"""Acceptance: Audatex-style ("Auda 7") documents never dead-end.

Fixtures in sample-data/auda-style/ replicate the client's real Auda 7 set:
- a rolled-up calculation invoice (totals only, no line items),
- an Audatex Full Report (summary, labour work units, EXTRAS charges),
- a photo-page PDF (image-only pages, as uploaded from a phone).

The intake contract under test: processing succeeds, nothing is FAILED or
discarded, and every manual-review document carries a stored briefing.
"""

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


def test_audatex_full_report_reaches_manual_review_not_failed(auda_client):
    document = _process(auda_client, "Auda7_full_report.pdf")
    assert document["status"] == "ready"
    assert document["kind"] == "engineer_assessment"
    assert document["manual_review"] is True
    assert document["review_briefing"]


@pytest.mark.slow
def test_photo_pages_reach_manual_review_with_briefing(auda_client):
    document = _process(auda_client, "Auda7_photo_pages.pdf")
    assert document["status"] == "ready"
    assert document["manual_review"] is True
    assert document["review_briefing"]
