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
        # pair_confidence is matched pairing keys over *comparable* ones, not
        # the old weighted score whose registration term happened to be worth
        # 0.70 and not a share of three. These fixtures print a registration on
        # both documents and a claim reference on neither invoice, so exactly
        # one key is comparable and it agrees: certain about the only evidence
        # there is, and flagged as the weakest shape of link the rule allows.
        assert all(
            assessment.pair_confidence == pytest.approx(1 / 1) for assessment in assessments
        )
        assert all(
            any("weak pair" in reason for reason in assessment.pair_reasons_json)
            for assessment in assessments
        )
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


def test_client_live_invoice_and_separate_estimate_are_processed_as_one_invoice(engineer_engine):
    from sqlalchemy import select

    from app.models import Invoice
    with Session(engineer_engine, expire_on_commit=False) as session:
        case = Case(case_reference="CG-CLIENT-LIVE-TEST", created_by="pytest.handler")
        session.add(case)
        session.flush()
        path = PAIR_DIR / "CLM-UK-001_Repair_Invoice.pdf"
        invoice_document = document_processing.store_pdf(
            session, case=case, filename=path.name, content=path.read_bytes(), intake_group="live"
        )
        document_processing.process_document(session, invoice_document)
        path = PAIR_DIR / "CLM-UK-001_Engineer_Assessment.pdf"
        estimate_document = document_processing.store_pdf(
            session, case=case, filename=path.name, content=path.read_bytes(),
            intake_group="live", paired_document_id=invoice_document.id,
        )
        document_processing.process_document(session, estimate_document)
        session.flush()
        invoices = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).all()
        assert len(invoices) == 1
        assessment = session.scalar(select(EngineerAssessment).where(EngineerAssessment.case_id == case.id))
        assert assessment.paired_invoice_id == invoices[0].id
        assert not estimate_document.invoices
        assert document_processing.serialise_document(estimate_document)["intake_group"] == "live"
