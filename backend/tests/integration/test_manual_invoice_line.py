from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.enums import (
    CaseStatus,
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    ReviewStatus,
    UploadStatus,
)
from app.init_db import initialize_database
from app.main import app
from app.models import AuditEvent, Case, Document, Invoice, InvoiceLineItem
from app.services import document_processing


@pytest.fixture
def manual_line_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'manual-line.db'}",
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
    with TestClient(app) as test_client:
        yield test_client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def _seed_case_document_invoice(
    factory: sessionmaker[Session],
    *,
    case_reference: str,
    case_status: CaseStatus = CaseStatus.EXTRACTION_REVIEW,
) -> tuple[str, str]:
    """Seed a case with a document + zero-line invoice, mirroring what a
    rolled-up invoice looks like once the pipeline stops filtering out
    non-benchmarkable invoices entirely (only their unusable lines).
    """

    with factory() as session:
        case = Case(case_reference=case_reference, status=case_status, created_by="pytest.handler")
        document = Document(
            case=case,
            document_role=DocumentRole.CURRENT,
            original_filename="rolled-up-invoice.pdf",
            storage_path="/tmp/rolled-up-invoice.pdf",
            sha256="b" * 64,
            mime_type="application/pdf",
            file_size=2048,
            page_count=1,
            upload_status=UploadStatus.READY,
            metadata_json={
                "manual_review": True,
                "manual_review_reason": "No benchmarkable invoice line items were detected.",
            },
        )
        invoice = Invoice(
            case=case,
            document=document,
            document_group_id="invoice:manual-review",
            document_role=InvoiceDocumentRole.INVOICE,
            invoice_number="INV-ROLLED-UP",
            currency="GBP",
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            extraction_confidence=0.4,
            review_status=ReviewStatus.PENDING,
            page_numbers_json=[1],
        )
        session.add(case)
        session.add(invoice)
        session.commit()
        return case.id, invoice.id


def test_manual_line_creates_approved_line_with_audit_event(manual_line_env) -> None:
    test_client, factory = manual_line_env
    _case_id, invoice_id = _seed_case_document_invoice(factory, case_reference="CG-MANUAL-001")

    response = test_client.post(
        f"/api/v1/claims/CG-MANUAL-001/invoices/{invoice_id}/lines",
        json={
            "description": "Front bumper repair",
            "quantity": "1",
            "unit": "each",
            "unit_price_net": "150.00",
            "line_total_net": "150.00",
            "vat_rate": "20",
            "item_kind": "part",
            "part_number": "BUMP-001",
            "recorded_by": "pytest.handler",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["description"] == "Front bumper repair"
    assert body["status"] == "approved"
    assert body["extraction_method"] == "manual"
    assert Decimal(str(body["line_total_net"])) == Decimal("150.00")

    with factory() as session:
        line = session.scalar(
            select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        )
        assert line is not None
        assert line.status == ReviewStatus.APPROVED
        assert line.extraction_method == ExtractionMethod.MANUAL
        assert line.extraction_confidence == 1.0
        assert line.user_corrected is True

        case = session.get(Case, line.invoice.case_id)
        assert case.status == CaseStatus.EXTRACTION_REVIEW

        events = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "INVOICE_LINE_MANUALLY_ADDED")
        ).all()
        assert len(events) == 1
        assert events[0].entity_id == line.id
        assert events[0].actor_id == "pytest.handler"


def test_manual_line_rejects_finalised_case(manual_line_env) -> None:
    test_client, factory = manual_line_env
    _case_id, invoice_id = _seed_case_document_invoice(
        factory, case_reference="CG-MANUAL-002", case_status=CaseStatus.FINALISED
    )

    response = test_client.post(
        f"/api/v1/claims/CG-MANUAL-002/invoices/{invoice_id}/lines",
        json={
            "description": "Front bumper repair",
            "line_total_net": "150.00",
            "recorded_by": "pytest.handler",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CASE_ALREADY_FINALISED"


def test_manual_line_rejects_empty_description(manual_line_env) -> None:
    test_client, factory = manual_line_env
    _case_id, invoice_id = _seed_case_document_invoice(factory, case_reference="CG-MANUAL-003")

    response = test_client.post(
        f"/api/v1/claims/CG-MANUAL-003/invoices/{invoice_id}/lines",
        json={
            "description": "   ",
            "line_total_net": "150.00",
            "recorded_by": "pytest.handler",
        },
    )
    assert response.status_code == 422


def test_manual_line_rejects_non_positive_total(manual_line_env) -> None:
    test_client, factory = manual_line_env
    _case_id, invoice_id = _seed_case_document_invoice(factory, case_reference="CG-MANUAL-004")

    response = test_client.post(
        f"/api/v1/claims/CG-MANUAL-004/invoices/{invoice_id}/lines",
        json={
            "description": "Front bumper repair",
            "line_total_net": "0",
            "recorded_by": "pytest.handler",
        },
    )
    assert response.status_code == 422


def test_manual_line_404_for_unknown_invoice(manual_line_env) -> None:
    test_client, factory = manual_line_env
    _seed_case_document_invoice(factory, case_reference="CG-MANUAL-005")

    response = test_client.post(
        "/api/v1/claims/CG-MANUAL-005/invoices/not-a-real-id/lines",
        json={
            "description": "Front bumper repair",
            "line_total_net": "150.00",
            "recorded_by": "pytest.handler",
        },
    )
    assert response.status_code == 404
