from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.enums import (
    CaseStatus,
    DocumentRole,
    ExtractionMethod,
    PageType,
    ReviewStatus,
    UploadStatus,
)
from app.init_db import initialize_database
from app.main import app
from app.models import AuditEvent, Case, Document, DocumentPage
from app.services.page_correction import PageCorrectionCommand, correct_document_page


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'page-corrections.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=False)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    yield engine, factory
    engine.dispose()


def _seed_page(factory: sessionmaker[Session]) -> str:
    with factory() as session:
        case = Case(
            case_reference="CG-PAGE-CORRECTION",
            status=CaseStatus.EXTRACTION_REVIEW,
            created_by="pytest.handler",
        )
        document = Document(
            case=case,
            document_role=DocumentRole.CURRENT,
            original_filename="repair-invoice.pdf",
            storage_path="/tmp/repair-invoice.pdf",
            sha256="a" * 64,
            mime_type="application/pdf",
            file_size=1024,
            page_count=1,
            upload_status=UploadStatus.READY,
        )
        page = DocumentPage(
            document=document,
            page_number=1,
            width=595,
            height=842,
            rotation=0,
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            page_type=PageType.INVOICE,
            classification_confidence=0.82,
            group_id="invoice:91283",
            raw_text="Original machine extraction remains immutable evidence.",
            review_status=ReviewStatus.PENDING,
        )
        session.add(case)
        session.commit()
        return page.id


def test_page_correction_service_preserves_extraction_and_audits(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    page_id = _seed_page(factory)

    with factory() as session:
        page = session.get(DocumentPage, page_id)
        assert page is not None
        result = correct_document_page(
            session,
            page=page,
            command=PageCorrectionCommand(
                actor="pytest.handler",
                reason="Page is an MOT certificate, not an invoice.",
                page_type="mot",
                group_id=None,
                group_id_set=True,
                rotation=90,
            ),
        )
        session.commit()

        assert result.changed_fields == ("page_type", "group_id", "rotation")
        assert page.page_type is PageType.MOT
        assert page.group_id is None
        assert page.rotation == 90
        assert page.review_status is ReviewStatus.CORRECTED
        assert page.raw_text == "Original machine extraction remains immutable evidence."
        assert page.document.metadata_json["reprocess_required"] is True

        audit = session.scalar(select(AuditEvent).where(AuditEvent.entity_id == page.id))
        assert audit is not None
        assert audit.event_type == "DOCUMENT_PAGE_CORRECTED"
        assert audit.before_json["page_type"] == "invoice"
        assert audit.after_json["page_type"] == "mot"
        assert audit.event_payload_json["raw_extraction_preserved"] is True


def test_page_correction_route_refreshes_page_payload_and_marks_reprocess(
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = database
    page_id = _seed_page(factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            corrected = client.patch(
                f"/api/v1/pages/{page_id}",
                json={
                    "actor": "pytest.handler",
                    "reason": "Verified page type and grouping against the source PDF.",
                    "page_type": "service_history",
                    "group_id": None,
                    "rotation": 180,
                },
            )
            assert corrected.status_code == 200
            payload = corrected.json()
            assert payload["page_type"] == "service_history"
            assert payload["group_id"] is None
            assert payload["rotation"] == 180
            assert payload["classification_source"] == "handler"
            assert payload["review_status"] == "corrected"
            assert payload["reprocess_required"] is True
            assert payload["changed_fields"] == ["page_type", "group_id", "rotation"]

            pages = client.get("/api/v1/claims/CG-PAGE-CORRECTION/pages")
            assert pages.status_code == 200
            listed = pages.json()[0]
            assert listed["document_filename"] == "repair-invoice.pdf"
            assert listed["classification_source"] == "handler"
            assert listed["correction"]["corrected_by"] == "pytest.handler"

            processing = client.post(f"/api/v1/documents/{listed['document_id']}/process")
            assert processing.status_code == 200
            assert processing.json()["status"] == "reprocess_required"
            assert processing.json()["reprocess_required"] is True

            repeated = client.patch(
                f"/api/v1/pages/{page_id}",
                json={
                    "actor": "pytest.handler",
                    "reason": "Retry of the same correction.",
                    "page_type": "service_history",
                    "group_id": None,
                    "rotation": 180,
                },
            )
            assert repeated.status_code == 422
            assert repeated.json()["detail"]["code"] == "NO_PAGE_CHANGES"
    finally:
        app.dependency_overrides.clear()
