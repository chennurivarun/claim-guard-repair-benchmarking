"""Regression: two retained invoices sharing a parsed invoice number must both
persist instead of violating uq_invoices_document_group.

Before the no-discard change, one of the duplicates was usually filtered out by
has_benchmarkable_part_lines(), hiding the collision. Found live against the
1646540 fixture during the Phase-5 corpus run.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.extraction.schemas import (
    DocumentAnalysis,
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
    PageAnalysis,
    PageType,
)
from app.init_db import initialize_database
from app.main import app
from app.models import Invoice
from app.services import document_processing


def _line(description: str, sequence_no: int = 1) -> ExtractedLine:
    return ExtractedLine(
        sequence_no=sequence_no,
        raw_description=description,
        normalised_description=description.lower(),
        item_kind="part",
        part_number=None,
        line_total_net=Decimal("40.00"),
        source=FieldSource(page_number=1, extraction_method="native", confidence=0.95),
    )


def _invoice(page_number: int, invoice_number: str) -> ExtractedInvoice:
    return ExtractedInvoice(
        header=InvoiceHeader(invoice_number=invoice_number, supplier_name="Acme Repairs"),
        totals=InvoiceTotals(subtotal_net=Decimal("40.00")),
        line_items=[_line(f"Part on page {page_number}")],
        page_numbers=[page_number],
        extraction_method="native_table",
        extraction_confidence=0.9,
    )


def _duplicate_number_analysis(source_path: Path) -> DocumentAnalysis:
    pages = [
        PageAnalysis(
            page_number=number,
            width=595,
            height=842,
            rotation=0,
            native_character_count=200,
            positioned_word_count=40,
            image_count=0,
            extraction_method="native",
            extraction_confidence=0.9,
            text=f"Invoice 90000 page {number}",
            page_type=PageType.INVOICE,
            classification_confidence=0.9,
        )
        for number in (1, 2)
    ]
    return DocumentAnalysis(
        source_path=source_path,
        sha256="d" * 64,
        page_count=len(pages),
        pages=pages,
        invoices=[_invoice(1, "90000"), _invoice(2, "90000")],
        engineer_assessments=[],
        manual_review_reason=None,
    )


@pytest.fixture
def duplicate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dupes.db'}",
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
    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(
        document_processing.PDFPipeline,
        "analyse",
        lambda self, pdf_path, output_dir: _duplicate_number_analysis(Path(pdf_path)),
    )
    with TestClient(app) as test_client:
        yield test_client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def test_duplicate_invoice_numbers_both_persist(duplicate_env) -> None:
    test_client, factory = duplicate_env
    created = test_client.post(
        "/api/v1/claims",
        json={
            "case_reference": "CG-DUPES",
            "claim_number": "CLM-DUPES",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201
    uploaded = test_client.post(
        "/api/v1/claims/CG-DUPES/documents",
        files={"file": ("dupes.pdf", b"%PDF-1.4\n%mock", "application/pdf")},
        data={"role": "current"},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["id"]

    processed = test_client.post(f"/api/v1/documents/{document_id}/process")
    assert processed.status_code == 200, processed.text

    with factory() as session:
        invoices = session.scalars(select(Invoice)).all()
        assert len(invoices) == 2
        group_ids = {record.document_group_id for record in invoices}
        assert len(group_ids) == 2, group_ids
        assert all(record.invoice_number == "90000" for record in invoices)
