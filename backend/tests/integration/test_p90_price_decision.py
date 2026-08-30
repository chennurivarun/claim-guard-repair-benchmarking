"""End-to-end tests for the server-side unified P90 price decision.

Covers: threshold propagation through the ``/workspace`` endpoint, summary
aggregation (rejected-line exclusion, invoiceNet fallback), workspace/export
consistency, per-line calculation breakdown completeness, and MOT VAT
suppression -- all driven from directly-constructed ORM fixtures (bypassing
the OCR/extraction pipeline, which is out of scope for this change).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.enums import (
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    PriceScope,
    ReviewStatus,
    UploadStatus,
)
from app.exports.common import approved_challenge_lines, compute_financial_summary
from app.init_db import initialize_database
from app.main import app
from app.models import Case, Document, Invoice, InvoiceLineItem, Vehicle
from app.services.case_result import build_case_result, build_claim_workspace

CASE_REFERENCE = "CG-P90-DECISION"


def _add_document(session: Session, case_id: str, name: str) -> Document:
    document = Document(
        case_id=case_id,
        document_role=DocumentRole.CURRENT,
        original_filename=name,
        storage_path=f"/tmp/{name}",
        sha256=name.ljust(64, "0")[:64],
        mime_type="application/pdf",
        file_size=100,
        upload_status=UploadStatus.READY,
    )
    session.add(document)
    session.flush()
    return document


def _add_invoice(
    session: Session,
    case_id: str,
    document_id: str,
    *,
    group_id: str,
    invoice_date: date,
    subtotal_net: str | None = None,
    non_vat_total: str | None = None,
    vat_total: str | None = None,
    gross_total: str | None = None,
) -> Invoice:
    vehicle = Vehicle(
        case_id=case_id,
        make="BMW",
        model="3 Series",
        source="pytest",
        verification_status=ReviewStatus.APPROVED,
    )
    session.add(vehicle)
    session.flush()
    invoice = Invoice(
        case_id=case_id,
        document_id=document_id,
        document_group_id=group_id,
        document_role=InvoiceDocumentRole.INVOICE,
        invoice_number=group_id,
        invoice_date=invoice_date,
        vehicle_id=vehicle.id,
        extraction_method=ExtractionMethod.NATIVE_TEXT,
        review_status=ReviewStatus.APPROVED,
        subtotal_net=subtotal_net,
        non_vat_total=non_vat_total,
        vat_total=vat_total,
        gross_total=gross_total,
    )
    session.add(invoice)
    session.flush()
    return invoice


def _add_line(
    session: Session,
    invoice_id: str,
    sequence_no: int,
    description: str,
    net: str,
    *,
    vat_rate: str = "20.00",
    kind: LineItemKind = LineItemKind.PART,
    status: ReviewStatus = ReviewStatus.APPROVED,
) -> InvoiceLineItem:
    line = InvoiceLineItem(
        invoice_id=invoice_id,
        sequence_no=sequence_no,
        raw_description=description,
        normalised_description=description.lower(),
        item_kind=kind,
        quantity="1",
        unit="each",
        price_scope=PriceScope.LINE_TOTAL,
        unit_price_net=net,
        line_total_net=net,
        vat_rate=vat_rate,
        extraction_method=ExtractionMethod.NATIVE_TABLE,
        status=status,
    )
    session.add(line)
    session.flush()
    return line


@pytest.fixture()
def p90_engine(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'p90.db'}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)

    with Session(engine, expire_on_commit=False) as session:
        case = Case(case_reference=CASE_REFERENCE, created_by="pytest.handler")
        session.add(case)
        session.flush()

        dates = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4)]
        invoices = []
        for index, invoice_date in enumerate(dates, start=1):
            document = _add_document(session, case.id, f"invoice-{index}.pdf")
            is_current = index == 4
            invoice = _add_invoice(
                session,
                case.id,
                document.id,
                group_id=f"invoice-{index}",
                invoice_date=invoice_date,
                subtotal_net="658.00" if is_current else None,
                non_vat_total="0.00" if is_current else None,
                vat_total="91.20" if is_current else None,
                gross_total="749.20" if is_current else None,
            )
            invoices.append(invoice)

        prior_bumper_prices = ["90.00", "95.00", "100.00"]
        for invoice, price in zip(invoices[:3], prior_bumper_prices, strict=True):
            _add_line(session, invoice.id, 1, "Front bumper reinforcement", price)
        # Current invoice: billed far above the P90 (99.00) -> big challenge.
        _add_line(session, invoices[3].id, 1, "Front bumper reinforcement", "200.00")

        for invoice in invoices[:3]:
            _add_line(session, invoice.id, 2, "Wheel alignment", "100.00")
        # Current invoice: only 8% above the P90 (100.00) -> borderline gate.
        _add_line(session, invoices[3].id, 2, "Wheel alignment", "108.00")

        for invoice in invoices[:3]:
            _add_line(session, invoice.id, 3, "MOT Test", "100.00")
        # Current invoice: well above P90 -> challenged, but VAT suppressed.
        _add_line(session, invoices[3].id, 3, "MOT Test", "150.00")

        for invoice in invoices[:3]:
            _add_line(session, invoice.id, 4, "Rejected replacement panel", "100.00")
        # Current invoice: extraction-rejected -> must be excluded entirely.
        _add_line(
            session,
            invoices[3].id,
            4,
            "Rejected replacement panel",
            "200.00",
            status=ReviewStatus.REJECTED,
        )

        session.commit()

    yield engine
    engine.dispose()


@pytest.fixture()
def p90_session(p90_engine):
    with Session(p90_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def p90_client(p90_engine):
    factory = sessionmaker(bind=p90_engine, class_=Session, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# --- Threshold parameter (via decide_line_price is covered in
# tests/unit/test_price_decision.py; this covers the same line via the
# workspace endpoint) -----------------------------------------------------


def test_wheel_alignment_line_is_challenged_at_5_and_within_at_10_via_workspace(
    p90_client,
) -> None:
    at_5 = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/workspace", params={"p90_threshold_pct": 5}
    )
    at_10 = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/workspace", params={"p90_threshold_pct": 10}
    )
    assert at_5.status_code == 200
    assert at_10.status_code == 200

    line_at_5 = next(row for row in at_5.json()["lines"] if row["description"] == "Wheel alignment")
    line_at_10 = next(
        row for row in at_10.json()["lines"] if row["description"] == "Wheel alignment"
    )
    assert line_at_5["comparisonStatus"] == "CHALLENGE"
    assert line_at_5["challenge"] == 8.0
    assert line_at_10["comparisonStatus"] == "WITHIN"
    assert line_at_10["challenge"] == 0.0


def test_invalid_threshold_is_rejected(p90_client) -> None:
    response = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/workspace", params={"p90_threshold_pct": 7}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_P90_THRESHOLD"


def test_invoice_list_uses_same_operational_p90_challenges_as_workspace(p90_client) -> None:
    at_10 = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/invoices", params={"p90_threshold_pct": 10}
    )
    at_5 = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/invoices", params={"p90_threshold_pct": 5}
    )

    assert at_10.status_code == 200
    assert at_5.status_code == 200
    reviews_at_10 = {row["invoice_number"]: row["challenge_review"] for row in at_10.json()}
    reviews_at_5 = {row["invoice_number"]: row["challenge_review"] for row in at_5.json()}
    invoice_rows_at_10 = {row["invoice_number"]: row for row in at_10.json()}

    # This fixture has no persisted legacy comparison/challenge rows. The
    # invoice list must still expose the operational P90 decisions.
    assert reviews_at_10["invoice-4"] == {
        "positive": 2,
        "approved": 0,
        "rejected": 0,
        "unresolved": 2,
    }
    assert reviews_at_5["invoice-4"] == {
        "positive": 3,
        "approved": 0,
        "rejected": 0,
        "unresolved": 3,
    }
    assert all(reviews_at_10[f"invoice-{index}"]["positive"] == 0 for index in range(1, 4))
    assert len(invoice_rows_at_10["invoice-4"]["challenge_lines"]) == 2
    assert all(
        line["challenge_net"] > 0 and line["billed_net"] > line["supported_net"]
        for line in invoice_rows_at_10["invoice-4"]["challenge_lines"]
    )
    assert invoice_rows_at_10["invoice-4"]["uploaded_at"]


# --- Aggregation: rejected lines excluded, breakdown present --------------


def test_summary_excludes_rejected_line_and_includes_challenged_lines(p90_session) -> None:
    workspace = build_claim_workspace(p90_session, CASE_REFERENCE, p90_threshold_pct=10)

    rejected_line = next(
        row for row in workspace["lines"] if row["description"] == "Rejected replacement panel"
    )
    assert rejected_line["comparisonStatus"] == "EXCLUDED"
    assert rejected_line["challenge"] == 0.0

    bumper_line = next(
        row for row in workspace["lines"] if row["description"] == "Front bumper reinforcement"
    )
    assert bumper_line["comparisonStatus"] == "CHALLENGE"
    assert bumper_line["challenge"] == 101.0
    assert bumper_line["recommended"] == 99.0

    # 101.00 (bumper) + 50.00 (MOT) is challenged; wheel alignment (8.00) does
    # not clear the 10% gate; the rejected line contributes nothing.
    assert workspace["summary"]["challengeAmount"] == pytest.approx(151.0)


def test_bumper_line_calculation_breakdown_is_complete(p90_session) -> None:
    workspace = build_claim_workspace(p90_session, CASE_REFERENCE, p90_threshold_pct=10)
    bumper_line = next(
        row for row in workspace["lines"] if row["description"] == "Front bumper reinforcement"
    )
    calculation = bumper_line["calculation"]
    labels = [step["label"] for step in calculation]
    assert "Percentage gate" in labels
    assert "Absolute gate" in labels
    assert "Supported price" in labels
    pct_step = next(step for step in calculation if step["label"] == "Percentage gate")
    amount_step = next(step for step in calculation if step["label"] == "Absolute gate")
    assert "passed" in pct_step and "passed" in amount_step
    supported_step = next(step for step in calculation if step["label"] == "Supported price")
    assert "weighted evidence price" in supported_step["detail"]


def test_line_price_evidence_reconciles_with_workspace_decision(p90_client) -> None:
    workspace_response = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/workspace",
        params={"p90_threshold_pct": 10},
    )
    assert workspace_response.status_code == 200
    bumper_line = next(
        row
        for row in workspace_response.json()["lines"]
        if row["description"] == "Front bumper reinforcement"
    )

    response = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/lines/{bumper_line['id']}/price-evidence",
        params={"p90_threshold_pct": 10},
    )

    assert response.status_code == 200
    evidence = response.json()
    historical = evidence["sources"]["historicalClaims"]
    assert evidence["lineId"] == bumper_line["id"]
    assert evidence["decision"]["supportedNet"] == bumper_line["recommended"]
    assert evidence["decision"]["challengeNet"] == bumper_line["challenge"]
    assert historical["currentInvoiceExcluded"] is True
    assert historical["sampleCount"] == len(historical["observations"])
    assert all(
        row["description"] == "Front bumper reinforcement" for row in historical["observations"]
    )
    assert all(
        row["invoiceId"] != workspace_response.json()["invoice"]["id"]
        for row in historical["observations"]
    )


def test_line_price_evidence_hides_unknown_or_cross_claim_line(p90_client) -> None:
    response = p90_client.get(
        f"/api/v1/claims/{CASE_REFERENCE}/lines/not-a-line/price-evidence",
        params={"p90_threshold_pct": 10},
    )

    assert response.status_code == 404


def test_mot_line_suppresses_vat_in_workspace(p90_session) -> None:
    workspace = build_claim_workspace(p90_session, CASE_REFERENCE, p90_threshold_pct=10)
    mot_line = next(row for row in workspace["lines"] if row["description"] == "MOT Test")
    assert mot_line["comparisonStatus"] == "CHALLENGE"
    assert mot_line["challenge"] == 50.0
    assert mot_line["challengeVat"] == 0.0


# --- Review recommendations stay separate from approved exports -----------


def test_workspace_recommendations_are_not_exported_before_approval(p90_session) -> None:
    workspace = build_claim_workspace(p90_session, CASE_REFERENCE, p90_threshold_pct=10)
    result = build_case_result(p90_session, CASE_REFERENCE, p90_threshold_pct=10)
    export_summary = compute_financial_summary(result)

    assert Decimal(str(workspace["summary"]["challengeAmount"])) == Decimal("151.0")
    assert Decimal(str(workspace["summary"]["vatImpact"])) == Decimal("20.2")
    assert export_summary.challenge_amount_net == Decimal("0.00")
    assert export_summary.vat_impact == Decimal("0.00")
    assert approved_challenge_lines(result) == []


def test_five_percent_recommendations_still_require_approval_for_export(p90_session) -> None:
    workspace = build_claim_workspace(p90_session, CASE_REFERENCE, p90_threshold_pct=5)
    result = build_case_result(p90_session, CASE_REFERENCE, p90_threshold_pct=5)
    export_summary = compute_financial_summary(result)

    assert Decimal(str(workspace["summary"]["challengeAmount"])) == Decimal("159.0")
    assert export_summary.challenge_amount_net == Decimal("0.00")
    letter_lines = {line.description for line in approved_challenge_lines(result)}
    # At the 5% threshold the wheel-alignment line also clears the gate.
    assert "Wheel alignment" not in letter_lines


# --- invoiceNet fallback ----------------------------------------------------


def test_invoice_net_falls_back_to_sum_of_line_totals_when_invoice_total_missing(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fallback.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    case_reference = "CG-P90-FALLBACK"
    with Session(engine, expire_on_commit=False) as session:
        case = Case(case_reference=case_reference, created_by="pytest.handler")
        session.add(case)
        session.flush()
        dates = [date(2026, 2, 1), date(2026, 2, 2), date(2026, 2, 3), date(2026, 2, 4)]
        invoices = []
        for index, invoice_date in enumerate(dates, start=1):
            document = _add_document(session, case.id, f"fallback-{index}.pdf")
            # Deliberately leave subtotal/non_vat totals unset (falsy) on
            # every invoice, including the current one, to force the
            # line-current-total fallback used by the JS overlay.
            invoice = _add_invoice(
                session,
                case.id,
                document.id,
                group_id=f"fallback-{index}",
                invoice_date=invoice_date,
            )
            invoices.append(invoice)
        for invoice, price in zip(invoices[:3], ["90.00", "95.00", "100.00"], strict=True):
            _add_line(session, invoice.id, 1, "Front bumper reinforcement", price)
        _add_line(session, invoices[3].id, 1, "Front bumper reinforcement", "200.00")
        session.commit()

    with Session(engine, expire_on_commit=False) as session:
        workspace = build_claim_workspace(session, case_reference, p90_threshold_pct=10)

    assert workspace["invoice"]["netIncludingMot"] == 0.0
    # Fallback: sum of line current totals (200.00) minus the challenge
    # (101.00) = 99.00.
    assert workspace["summary"]["challengePrice"] == 99.0
    assert workspace["summary"]["challengeAmount"] == 101.0
    engine.dispose()
