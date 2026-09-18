"""End to end: two benchmark sources, vehicle category, analysis, challenge email.

This is what the client asked Nikitha to do on 17 Sep: copies of the client's
own documents loaded under each source, each source's mapping approved, a new
invoice uploaded, and that invoice judged line by line against both
benchmarks.

* Third party insured invoices (``historical_claim``): formats 1, 3 and 6.
* Aviva DLG invoices (``in_house``): formats 5, 4 and 7.
* New invoice (``live``): the format 2 pair, through the real upload API.

The client's formats do not happen to produce a line of every challenge level
against each other, so one purpose-built live invoice is added beside them:
a HYUNDAI (the make+model formats 1/5/6/7 carry after gap-fill) whose lines
reuse the corpus's own repair items at prices chosen to land on High, Medium,
Low and none deterministically, plus a rolled-up "Total Labour" whose
engineer assessment rows agree with it.  The expected P90s below are
computed from the client documents' own figures:

========================  =======================  =======================
repair item (Hatchback)   third party P90 (n)      Aviva DLG P90 (n)
========================  =======================  =======================
L/R DOOR (parts)          847.73, 882.30 -> 878.84  645.00, 847.73 -> 827.46
L/SILL PANEL COVER        317.28, 330.22 -> 328.93  240.00, 317.28 -> 309.55
Car Sanitisation          30.00, 31.22 -> 31.10     22.80, 30.00 -> 29.28
REMOVE ATTACHED PARTS     15.20, 15.20 -> 15.20     15.20, 15.20 -> 15.20
========================  =======================  =======================
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.config import get_settings
from app.database import get_db
from app.domain.normalisation import normalise_description
from app.enums import (
    DocumentKind,
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    UploadStatus,
)
from app.init_db import initialize_database
from app.main import app
from app.models import (
    AssessmentOperation,
    AuditEvent,
    Case,
    Document,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
    Vehicle,
)
from app.services.source_benchmarks import analysis_money_figures, money_figures_in_text

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REFERENCE = "BENCHMARKS-E2E"
HANDLER = "pytest.handler"

SOURCES: dict[str, tuple[list[str], list[str]]] = {
    "historical_claim": (
        [
            "DL_Repair_Invoice_format_1.docx",
            "DL_Invoice_3_request_for_payment.docx",
            "DL_Repair_Invoice_format_6.docx",
        ],
        [
            "DL_Auda_format_1_assessment.docx",
            "DL_Auda_format_3_assessment.docx",
            "DL_Auda_format_6_assessment.docx",
        ],
    ),
    "in_house": (
        [
            "DL_Repair_Invoice_format_5.docx",
            "DL_Invoice_4_request_for_payment.docx",
            "DL_Repair_Invoice_format_7.docx",
        ],
        [
            "DL_Auda_format_5_assessment.docx",
            "DL_Auda_format_4_assessment.docx",
            "DL_Auda_format_7_assessment.docx",
        ],
    ),
    "live": (
        ["DL_Invoice_2_request_for_payment.docx"],
        ["DL_Auda_format_2_assessment.docx"],
    ),
}
FILES_BY_GROUP = {group: set(inv) | set(est) for group, (inv, est) in SOURCES.items()}
PURPOSE_BUILT = "purpose-built-live-invoice.pdf"
PURPOSE_BUILT_ASSESSMENT = "purpose-built-live-assessment.pdf"


@pytest.fixture
def bench_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    # "No LLM key is configured on the client's machines by default": make that
    # true here whatever the developer's own environment holds.
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'benchmarks.db'}",
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


def _upload_sources(client: TestClient) -> None:
    created = client.post(
        "/api/v1/claims",
        json={"case_reference": REFERENCE, "claim_number": "2026/BENCH/1", "created_by": HANDLER},
    )
    assert created.status_code == 201, created.text
    for group, (invoices, estimates) in SOURCES.items():
        response = client.post(
            f"/api/v1/claims/{REFERENCE}/documents/batch",
            files=[
                ("invoice_files", (name, (FIXTURES / name).read_bytes(), DOCX_MIME))
                for name in invoices
            ]
            + [
                ("estimate_files", (name, (FIXTURES / name).read_bytes(), DOCX_MIME))
                for name in estimates
            ],
            data={"intake_group": group},
        )
        assert response.status_code == 200, response.text
        assert response.json()["failed"] == 0, response.json()


def _approve(client: TestClient, group: str | None) -> dict:
    body: dict[str, str] = {"actor": HANDLER}
    if group is not None:
        body["intake_group"] = group
    response = client.post(f"/api/v1/claims/{REFERENCE}/document-mapping/approve", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _mapping(client: TestClient, group: str | None = None) -> dict:
    suffix = f"?intake_group={group}" if group else ""
    response = client.get(f"/api/v1/claims/{REFERENCE}/document-mapping{suffix}")
    assert response.status_code == 200, response.text
    return response.json()


def _add_purpose_built_live_invoice(client: TestClient) -> tuple[str, dict[str, str]]:
    """A live HYUNDAI invoice + assessment built to hit every challenge level."""

    with Session(client.engine, expire_on_commit=False) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        documents = {}
        for name, kind in (
            (PURPOSE_BUILT, DocumentKind.REPAIR_INVOICE),
            (PURPOSE_BUILT_ASSESSMENT, DocumentKind.ENGINEER_ASSESSMENT),
        ):
            documents[name] = Document(
                case_id=case.id,
                document_role=DocumentRole.CURRENT,
                document_kind=kind,
                original_filename=name,
                storage_path=f"/tmp/{name}",
                sha256=name.encode().hex().ljust(64, "0")[:64],
                mime_type="application/pdf",
                file_size=100,
                upload_status=UploadStatus.READY,
                metadata_json={"intake_group": "live"},
            )
            session.add(documents[name])
        vehicle = Vehicle(
            case_id=case.id, registration="LV24LVE", make="HYUNDAI", model="140 SE Nav",
            source="pytest",
        )
        session.add(vehicle)
        session.flush()
        invoice = Invoice(
            case_id=case.id,
            document_id=documents[PURPOSE_BUILT].id,
            document_group_id="purpose-built",
            document_role=InvoiceDocumentRole.INVOICE,
            invoice_number="LIVE-0001",
            claim_reference="777000111/1",
            vehicle_id=vehicle.id,
            labour_net="45.60",
            extraction_method=ExtractionMethod.MANUAL,
        )
        session.add(invoice)
        session.flush()
        rows = [
            ("L/R DOOR", "parts", LineItemKind.PART, "1000.00", False),
            ("L/SILL PANEL COVER", "parts", LineItemKind.PART, "345.00", False),
            ("Car Sanitisation", "specialist_operation", LineItemKind.FEE, "31.50", False),
            ("Door Fitting Kit", "parts", LineItemKind.PART, "5.00", False),
            ("Wheel alignment check", "specialist_operation", LineItemKind.FEE, "60.00", False),
            ("Total Labour", "labour", LineItemKind.UNKNOWN, "45.60", True),
        ]
        line_ids = {}
        for sequence, (description, section, kind, amount, is_total) in enumerate(rows, 1):
            line = InvoiceLineItem(
                invoice_id=invoice.id,
                sequence_no=sequence,
                raw_description=description,
                normalised_description=normalise_description(description),
                line_item_type=section,
                is_section_total=is_total,
                item_kind=kind,
                line_total_net=amount,
                extraction_method=ExtractionMethod.MANUAL,
            )
            session.add(line)
            session.flush()
            line_ids[description] = line.id
        assessment = EngineerAssessment(
            case_id=case.id,
            document_id=documents[PURPOSE_BUILT_ASSESSMENT].id,
            assessment_number="LIVE-ASSESS-1",
            claim_reference="777000111/1",
            registration="LV24LVE",
            vehicle_make="HYUNDAI",
            vehicle_model="140 SE Nav",
            labour_net="45.60",
        )
        session.add(assessment)
        session.flush()
        for sequence, (description, amount) in enumerate(
            (("R + R DOOR MIRROR", "7.60"), ("REMOVE ATTACHED PARTS", "38.00")), 1
        ):
            session.add(
                AssessmentOperation(
                    assessment_id=assessment.id,
                    sequence_no=sequence,
                    category="labour",
                    raw_description=description,
                    normalised_description=normalise_description(description),
                    total_net=amount,
                )
            )
        session.commit()
        invoice_id = invoice.id
    # The printed registration and claim reference are what pair them: the
    # real rule, not a hand-set column.
    swept = client.post(f"/api/v1/claims/{REFERENCE}/documents/link-sweep")
    assert swept.status_code == 200, swept.text
    return invoice_id, line_ids


def _source_filenames(client: TestClient, group: str) -> set[str]:
    return FILES_BY_GROUP[group]


# --------------------------------------------------------------------------
# Source scoping and per-source mapping approval
# --------------------------------------------------------------------------


def test_extracts_and_mapping_are_scoped_by_source_and_approved_per_source(bench_client):
    client = bench_client
    _upload_sources(client)

    everything = client.get(f"/api/v1/claims/{REFERENCE}/extracts").json()
    third_party = client.get(
        f"/api/v1/claims/{REFERENCE}/extracts?intake_group=historical_claim"
    ).json()
    aviva = client.get(f"/api/v1/claims/{REFERENCE}/extracts?intake_group=in_house").json()

    assert set(everything) == {"invoice_extracts", "assessment_extracts", "section_breakdowns"}
    assert len(everything["invoice_extracts"]) == 7
    assert {row["vehicle_registration"] for row in third_party["invoice_extracts"]} == {
        "AB12XYZ", "AM06TAH", "GH58JKL",
    }
    assert {row["vehicle_registration"] for row in aviva["invoice_extracts"]} == {
        "CD34EFG", "PD73UUF", "JK21MNO",
    }
    assert {row["vehicle_registration"] for row in third_party["assessment_extracts"]} == {
        "AB12XYZ", "AM06TAH", "GH58JKL",
    }
    third_party_invoice_ids = {row["invoice_id"] for row in third_party["invoice_extracts"]}
    assert {row["invoice_id"] for row in third_party["section_breakdowns"]} <= (
        third_party_invoice_ids
    )
    bad = client.get(f"/api/v1/claims/{REFERENCE}/extracts?intake_group=nonsense")
    assert bad.status_code == 422

    tp_mapping = _mapping(client, "historical_claim")
    assert {row["intake_group"] for row in tp_mapping["invoices"]} == {"historical_claim"}
    assert {row["intake_group"] for row in tp_mapping["assessments"]} == {"historical_claim"}
    assert tp_mapping["assessments_total"] == 3 and tp_mapping["paired"] == 3
    assert tp_mapping["approval"]["approved"] is False

    approved = _approve(client, "historical_claim")
    assert approved["approval"]["approved"] is True
    assert set(approved["approval"]["approved_pairs"]) == {
        row["assessment_id"] for row in tp_mapping["assessments"]
    }
    # Approving the third-party source approves nothing else.
    assert _mapping(client, "historical_claim")["approval"]["approved"] is True
    assert _mapping(client, "in_house")["approval"]["approved"] is False
    assert _mapping(client, "live")["approval"]["approved"] is False
    # ...and the no-parameter, case-level approval is exactly as it was.
    case_level = _mapping(client)
    assert case_level["approval"]["approved"] is False
    assert "intake_group" not in case_level
    assert case_level["assessments_total"] == 7

    _approve(client, "in_house")
    assert _mapping(client, "historical_claim")["approval"]["approved"] is True
    assert _mapping(client, "in_house")["approval"]["approved"] is True

    # A new Aviva DLG document reopens that source's approval only.
    extra = client.post(
        f"/api/v1/claims/{REFERENCE}/documents/batch",
        files=[(
            "estimate_files",
            ("EXL_demo_engineer_report.docx",
             (FIXTURES / "EXL_demo_engineer_report.docx").read_bytes(), DOCX_MIME),
        )],
        data={"intake_group": "in_house"},
    )
    assert extra.status_code == 200, extra.text
    assert _mapping(client, "in_house")["approval"]["approved"] is False
    assert _mapping(client, "historical_claim")["approval"]["approved"] is True


# --------------------------------------------------------------------------
# Benchmarks, analysis and the challenge email, end to end
# --------------------------------------------------------------------------


def _row(payload: dict, category: str, description: str, kind: str) -> dict:
    key_matches = [
        row for row in payload["rows"]
        if row["vehicle_category"] == category
        and row["line_item_type"] == kind
        and normalise_description(description)
        in {normalise_description(evidence["description"]) for evidence in row["evidence"]}
    ]
    assert len(key_matches) == 1, (category, description, kind, key_matches)
    return key_matches[0]


def test_two_sources_benchmark_analysis_and_challenge_email(bench_client):
    client = bench_client
    _upload_sources(client)
    for group in ("historical_claim", "in_house", "live"):
        _approve(client, group)
    live_invoice_id, live_line_ids = _add_purpose_built_live_invoice(client)

    # ---- /benchmarks: each source is only its own documents -------------
    third_party = client.get(f"/api/v1/claims/{REFERENCE}/benchmarks?source=third_party")
    aviva = client.get(f"/api/v1/claims/{REFERENCE}/benchmarks?source=aviva_dlg")
    assert third_party.status_code == 200, third_party.text
    assert aviva.status_code == 200, aviva.text
    third_party, aviva = third_party.json(), aviva.json()
    assert client.get(f"/api/v1/claims/{REFERENCE}/benchmarks?source=seed").status_code == 422

    assert (third_party["source"], third_party["intake_group"]) == (
        "third_party", "historical_claim",
    )
    assert third_party["label"] == "Third party insured invoices"
    assert (aviva["source"], aviva["intake_group"], aviva["label"]) == (
        "aviva_dlg", "in_house", "Aviva DLG invoices",
    )
    assert third_party["invoice_count"] == 3 and aviva["invoice_count"] == 3
    assert third_party["threshold_pct"] == "10"

    for payload, group in ((third_party, "historical_claim"), (aviva, "in_house")):
        assert payload["rows"], group
        for row in payload["rows"]:
            assert row["observations"] == len(row["evidence"]) >= 1
            assert row["p90"] is not None
            for evidence in row["evidence"]:
                # Only this source's uploaded documents: never the other source,
                # never the new invoice, never synthetic or seed rows.
                assert evidence["document_filename"] in _source_filenames(client, group), evidence
                assert evidence["origin"] in {"invoice", "engineer_assessment"}
                # A rolled-up total is never an observation.
                assert not normalise_description(evidence["description"]).startswith("total ")
                assert "Mixed synthetic vehicles" != row["vehicle_category"]

    assert {
        (row["category"], row["invoice_count"], row["source"])
        for row in third_party["vehicle_categories"]
    } == {("Hatchback", 2, "lookup"), ("Supermini", 1, "lookup")}
    assert {
        (row["category"], row["invoice_count"], row["source"])
        for row in aviva["vehicle_categories"]
    } == {("Hatchback", 2, "lookup"), ("SUV", 1, "lookup")}

    door = _row(third_party, "Hatchback", "L/R DOOR", "parts")
    assert (door["observations"], door["p90"], door["min"], door["max"]) == (
        2, "878.84", "847.73", "882.30",
    )
    assert {evidence["origin"] for evidence in door["evidence"]} == {"invoice"}
    assert {evidence["vehicle_make"] for evidence in door["evidence"]} == {"HYUNDAI"}
    assert _row(aviva, "Hatchback", "L/R DOOR", "parts")["p90"] == "827.46"
    # Assessment rows behind a rolled-up Total Labour that agrees with the
    # assessment's labour total are admitted, and labelled as such.
    removal = _row(third_party, "Hatchback", "REMOVE ATTACHED PARTS", "labour")
    assert {evidence["origin"] for evidence in removal["evidence"]} == {"engineer_assessment"}
    assert removal["observations"] == 2
    # The SEAT (Supermini) does not feed the Hatchback P90 of a part it shares.
    assert all(
        evidence["registration"] != "AM06TAH"
        for row in third_party["rows"] if row["vehicle_category"] == "Hatchback"
        for evidence in row["evidence"]
    )

    # ---- /benchmark-analysis on the purpose-built live invoice -----------
    response = client.get(f"/api/v1/claims/{REFERENCE}/benchmark-analysis")
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["invoice"]["id"] == live_invoice_id, "defaults to the latest live invoice"
    assert analysis["invoice"]["vehicle_category"] == "Hatchback"
    assert analysis["invoice"]["vehicle_category_source"] == "lookup"
    assert analysis["invoice"]["paired_assessment_number"] == "LIVE-ASSESS-1"
    assert {row["id"] for row in analysis["live_invoices"]} >= {live_invoice_id}
    assert analysis["threshold_pct"] == "10"
    assert analysis["minimum_challenge_amount"] == "5.00"

    origins = [line["origin"] for line in analysis["lines"]]
    assert origins == sorted(origins, key=lambda origin: origin != "invoice"), origins
    assert "engineer_assessment" in origins and "invoice" in origins
    assert live_line_ids["Total Labour"] not in {line["line_id"] for line in analysis["lines"]}
    assert all(line["description"] != "Total Labour" for line in analysis["lines"])

    by_description = {line["description"]: line for line in analysis["lines"]}
    for line in analysis["lines"]:
        assert set(line["benchmarks"]) == {"third_party", "aviva_dlg"}

    door_line = by_description["L/R DOOR"]
    assert door_line["benchmarks"]["third_party"]["p90"] == "878.84"
    assert door_line["benchmarks"]["aviva_dlg"]["p90"] == "827.46"
    assert door_line["benchmarks"]["third_party"]["evidence"]
    assert door_line["challenge"]["level"] == "high"
    assert door_line["challenge"]["justified_amount"] == "878.84"
    assert door_line["challenge"]["challenge_amount"] == "121.16"

    sill = by_description["L/SILL PANEL COVER"]["challenge"]
    assert (sill["level"], sill["justified_amount"], sill["challenge_amount"]) == (
        "medium", "309.55", "35.45",
    )
    low = by_description["Car Sanitisation"]
    assert low["challenge"]["level"] == "low"
    assert low["challenge"]["challenge_amount"] == "0.00"
    assert low["benchmarks"]["third_party"]["above_p90"] is True
    assert by_description["Door Fitting Kit"]["challenge"]["level"] is None

    unseen = by_description["Wheel alignment check"]
    for source in ("third_party", "aviva_dlg"):
        assert unseen["benchmarks"][source]["available"] is False
        assert unseen["benchmarks"][source]["p90"] is None
        assert unseen["benchmarks"][source]["violated"] is False
    assert unseen["challenge"]["level"] is None

    removal_line = by_description["REMOVE ATTACHED PARTS"]
    assert removal_line["origin"] == "engineer_assessment"
    assert removal_line["challenge"]["level"] == "high"
    assert removal_line["challenge"]["challenge_amount"] == "22.80"
    assert by_description["R + R DOOR MIRROR"]["challenge"]["level"] is None

    labour_breakdown = [
        row for row in analysis["section_breakdowns"]
        if row["invoice_line_item_id"] == live_line_ids["Total Labour"]
    ]
    assert len(labour_breakdown) == 1 and labour_breakdown[0]["matches"] is True
    assert labour_breakdown[0]["rows_total"] == "45.60"

    assert analysis["totals"] == {
        "line_count": 7,
        "challenge_count": 3,
        "by_level": {"high": 2, "medium": 1, "low": 1},
        "total_challenge_amount": "179.41",
    }

    # ---- the real format 2 live invoice: rolled up, never benchmarked ----
    with Session(client.engine) as session:
        format_2 = session.scalar(
            select(Invoice).join(Document).where(
                Document.original_filename == "DL_Invoice_2_request_for_payment.docx"
            )
        )
        format_2_id = format_2.id
    rolled = client.get(
        f"/api/v1/claims/{REFERENCE}/benchmark-analysis?invoice_id={format_2_id}"
    ).json()
    assert rolled["invoice"]["vehicle_category"] == "SUV"
    assert rolled["lines"] == [], "every format 2 invoice line is a rolled-up total"
    assert len(rolled["section_breakdowns"]) == 4
    labour_section = next(
        row for row in rolled["section_breakdowns"] if row["line_item_type"] == "labour"
    )
    # 2008.00 invoiced against 1112.00 assessed: the rows are not admitted.
    assert labour_section["matches"] is False
    assert client.get(
        f"/api/v1/claims/{REFERENCE}/benchmark-analysis?invoice_id=not-an-invoice"
    ).status_code == 404

    # ---- /challenge-email -------------------------------------------------
    with Session(client.engine) as session:
        audit_before = session.scalar(select(func.count(AuditEvent.id)))
    challenged = [line["line_id"] for line in analysis["lines"] if line["challenge"]["is_challenge"]]
    draft = client.post(
        f"/api/v1/claims/{REFERENCE}/challenge-email",
        json={"invoice_id": live_invoice_id, "line_ids": challenged, "recipient": "Acme Motor"},
    )
    assert draft.status_code == 200, draft.text
    draft = draft.json()
    assert draft["generated_by"] == "template"
    assert draft["total_challenge_amount"] == "179.41"
    assert {line["line_id"] for line in draft["lines"]} == set(challenged)
    figures = money_figures_in_text(draft["subject"] + "\n" + draft["body"])
    assert figures and figures <= analysis_money_figures(analysis)
    assert Decimal("179.41") in figures
    with Session(client.engine) as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == audit_before + 1
        event_row = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "CHALLENGE_EMAIL_DRAFTED")
        )
        assert event_row is not None
        assert set(event_row.event_payload_json["line_ids"]) == set(challenged)
        assert event_row.event_payload_json["generated_by"] == "template"

    not_challenged = client.post(
        f"/api/v1/claims/{REFERENCE}/challenge-email",
        json={"invoice_id": live_invoice_id, "line_ids": [low["line_id"]]},
    )
    assert not_challenged.status_code == 422
