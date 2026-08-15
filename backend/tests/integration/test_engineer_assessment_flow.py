from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.enums import DocumentKind, DocumentRole
from app.init_db import initialize_database
from app.models import (
    AssessmentInvoiceVariance,
    AssessmentOperation,
    Case,
    EngineerAssessment,
    HistoricalObservation,
    InvoiceLineItem,
)
from app.services import document_processing


PAIR_DIR = Path(__file__).resolve().parents[3] / "sample-data" / "engineer-invoice-pairs"


@pytest.fixture()
def engineer_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if not PAIR_DIR.is_dir():
        pytest.skip("Engineer Assessment acceptance fixtures are not available")
    engine = create_engine(f"sqlite:///{tmp_path / 'engineer-flow.db'}")
    initialize_database(engine, seed_defaults=True)
    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    yield engine
    engine.dispose()


def test_five_assessments_pair_safely_without_entering_p90_history(engineer_engine) -> None:
    with Session(engineer_engine, expire_on_commit=False) as session:
        for sequence in range(1, 6):
            reference = f"CLM-UK-{sequence:03d}"
            case = Case(case_reference=reference, created_by="pytest.handler")
            session.add(case)
            session.flush()
            for suffix in ("Engineer_Assessment", "Repair_Invoice"):
                path = PAIR_DIR / f"{reference}_{suffix}.pdf"
                document = document_processing.store_pdf(
                    session,
                    case=case,
                    filename=path.name,
                    content=path.read_bytes(),
                    role=DocumentRole.CURRENT,
                )
                run = document_processing.process_document(session, document)
                assert run.status.value == "succeeded"
                expected_kind = (
                    DocumentKind.ENGINEER_ASSESSMENT
                    if suffix == "Engineer_Assessment"
                    else DocumentKind.REPAIR_INVOICE
                )
                assert document.document_kind == expected_kind
        session.commit()

        assessments = session.scalars(select(EngineerAssessment)).all()
        assert len(assessments) == 5
        assert all(assessment.pair_status == "paired" for assessment in assessments)
        assert all((assessment.pair_confidence or 0) >= 0.70 for assessment in assessments)
        assert session.scalar(select(func.count()).select_from(AssessmentOperation)) == 25
        assert session.scalar(select(func.count()).select_from(AssessmentInvoiceVariance)) == 25
        assert session.scalar(select(func.count()).select_from(InvoiceLineItem)) == 25
        # Engineer Assessment rows are evidence only and never become P90 observations.
        assert session.scalar(select(func.count()).select_from(HistoricalObservation)) == 0

        statuses = set(
            session.scalars(select(AssessmentInvoiceVariance.threshold_status)).all()
        )
        assert "within_threshold" in statuses
        assert "above_10_percent" in statuses
