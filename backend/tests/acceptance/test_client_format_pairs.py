"""End-to-end acceptance: the three client format pairs through the real API.

Task 10 of the invoice-assessment-matching sprint. Every upload helper and
assertion style here is reused rather than reinvented:

- upload/process pattern: tests/integration/test_extracts_persistence.py
- pairing, gap-fill, and section-breakdown assertions:
  tests/unit/test_engineer_assessment_pairing.py
- ``GET /claims/{case_reference}/extracts`` response shape:
  tests/integration/test_extracts_api.py
- deterministic, LLM-free acceptance style: tests/acceptance/test_auda_style_documents.py

Deterministic, LLM-free: no extractor tier is configured in the test
settings, so the native ``.docx`` parsers do all of the work and every number
below is exact, taken from ``sample-data/client-formats/manifest.json`` and
the existing unit/integration coverage above.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.database import get_db
from app.enums import LineItemKind, Severity
from app.init_db import initialize_database
from app.main import app
from app.models import (
    AssessmentOperation,
    Case,
    ClaimConsistencyFinding,
    Document,
    EngineerAssessment,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    OntologyMapping,
    PriceComparison,
)
from app.services.comparison_workflow import run_case_comparison
from app.services.engineer_assessment import engineer_assessment_payload

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MANIFEST: list[dict] = json.loads((FIXTURES / "manifest.json").read_text())

PAIRS: dict[int, tuple[str, str]] = {
    1: ("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_1.docx"),
    2: ("DL_Auda_format_2_assessment.docx", "DL_Invoice_2_request_for_payment.docx"),
    7: ("DL_Auda_format_7_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
}

#: ``(matched keys, comparable keys)`` -- the two numbers ``pair_confidence``
#: divides, asserted instead of the ratio. Formats 1 and 7 do not compare a
#: policy number at all (format 1's report prints the placeholder "PH";
#: format 7's invoice prints none), so both agree on the two keys they can
#: compare; format 2 prints all three and matches on all three. Every one of
#: those ratios is 1.0, so asserting the ratio would pass unchanged against a
#: regression to matched-over-three -- only the denominator catches it.
EXPECTED_KEY_COUNTS: dict[int, tuple[int, int]] = {1: (2, 2), 2: (3, 3), 7: (2, 2)}

#: The per-key states the payload must carry for each pair, so the UI can show
#: a skipped key as skipped rather than as a silent failure to match -- and
#: can tell a key nobody printed from one printed as a placeholder.
EXPECTED_KEY_STATES: dict[int, dict[str, str]] = {
    1: {
        "registration": "matched",
        "claim_reference": "matched",
        "policy_number": "placeholder",
    },
    2: {
        "registration": "matched",
        "claim_reference": "matched",
        "policy_number": "matched",
    },
    7: {
        "registration": "matched",
        "claim_reference": "matched",
        "policy_number": "not_compared",
    },
}

#: The section-total ``line_item_type`` values each invoice is rolled up
#: into, per the Decisions log and the manifest's own ``section_totals``.
EXPECTED_SECTION_TOTAL_TYPES: dict[int, set[str]] = {
    1: {"labour", "paint_materials"},
    2: {"parts", "paint_materials", "labour", "extras"},
    7: {"labour", "paint_materials"},
}

#: (line_item_type, measure, printed, rows) -- every printed-vs-row
#: disagreement the client's own documents reproduce. Format 2's report is
#: never captured beyond its labour schedule, so it prints no disagreement.
DISAGREEMENTS: dict[int, list[tuple[str, str, str, str]]] = {
    1: [("labour", "work units", "218", "101")],
    2: [],
    7: [
        ("labour", "work units", "300", "101"),
        ("paint", "work units", "113.2", "151"),
        ("parts", "total", "907.70", "908.30"),
    ],
}

#: Mandatory identity fields neither invoice prints, so the gap-fill sweep
#: must supply them from the paired assessment (with field_sources
#: attribution). Format 2 prints all of them itself.
GAP_FILLED_INVOICE_FIELDS: dict[int, set[str]] = {
    1: {"make", "model", "policy_number"},
    2: set(),
    7: {"make", "model", "policy_number"},
}


def _manifest_entry(document_kind: str, pair_id: int) -> dict:
    return next(
        entry
        for entry in MANIFEST
        if entry["document_kind"] == document_kind and entry["pair_id"] == pair_id
    )


def _manifest_entry_by_filename(filename: str) -> dict:
    return next(entry for entry in MANIFEST if entry["filename"] == filename)


def _expected_assessment_identity(pair_id: int) -> dict[str, str]:
    manifest = _manifest_entry("engineer_assessment", pair_id)
    return {
        "assessment_number": manifest["assessment_number"],
        "claim_reference": manifest["claim_reference"],
        "policy_number": manifest["policy_number"],
        "registration": manifest["registration"],
        "vehicle_make": manifest["vehicle_make"],
        "vehicle_model": manifest["vehicle_model"],
    }


def _expected_invoice_identity(pair_id: int) -> dict[str, str]:
    invoice_manifest = _manifest_entry("repair_invoice", pair_id)
    assessment_manifest = _manifest_entry("engineer_assessment", pair_id)
    return {
        "invoice_number": invoice_manifest["invoice_number"],
        "claim_reference": invoice_manifest["claim_reference"],
        # Printed on the invoice where the manifest says so; otherwise the
        # value the gap-fill sweep must pull from the matched assessment.
        "policy_number": invoice_manifest["policy_number"] or assessment_manifest["policy_number"],
        "vehicle_make": invoice_manifest["vehicle_make"] or assessment_manifest["vehicle_make"],
        "vehicle_model": invoice_manifest["vehicle_model"] or assessment_manifest["vehicle_model"],
    }


@pytest.fixture
def extracts_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'client_format_pairs.db'}",
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


def _session(client: TestClient) -> Session:
    return Session(client.engine, expire_on_commit=False)


def _money(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _upload_and_process(client: TestClient, reference: str, filename: str) -> dict:
    uploaded = client.post(
        f"/api/v1/claims/{reference}/documents",
        files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
        data={"role": "current"},
    )
    assert uploaded.status_code == 200, uploaded.text
    processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
    assert processed.status_code == 200, processed.text
    return processed.json()["document"]


def _process_pair(client: TestClient, pair_id: int, *, reference: str | None = None) -> tuple[str, dict[str, dict]]:
    """Create a case and upload+process one client pair; return its reference and documents."""

    reference = reference or f"CLIENT-PAIR-{pair_id}"
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": f"2026/CLIENT-PAIR/{pair_id}",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text
    documents = {
        filename: _upload_and_process(client, reference, filename) for filename in PAIRS[pair_id]
    }
    return reference, documents


def _invoice_without_vehicle_make_model(tmp_path: Path) -> Path:
    """Format 2's invoice, rewritten with its Vehicle Make/Model cells blanked.

    ``DL_Invoice_2_request_for_payment.docx`` prints "Vehicle Make"/"Vehicle
    Model" as a label cell followed by a value cell in a no-colon grid table
    (see ``scripts/build_client_format_fixtures.py:add_grid_table``). Both
    cells of each pair are cleared so the document reads exactly like format
    7's invoice: registration/claim/policy printed, vehicle identity absent.
    """

    source = FIXTURES / "DL_Invoice_2_request_for_payment.docx"
    document = DocxDocument(str(source))
    blanked = 0
    for table in document.tables:
        for row in table.rows:
            cells = row.cells
            for index, cell in enumerate(cells):
                if cell.text.strip() in {"Vehicle Make", "Vehicle Model"}:
                    cell.text = ""
                    if index + 1 < len(cells):
                        cells[index + 1].text = ""
                    blanked += 1
    assert blanked == 2, "expected to blank exactly the Vehicle Make and Vehicle Model cells"

    output = tmp_path / "invoice_2_without_vehicle.docx"
    document.save(str(output))
    return output


@pytest.mark.parametrize("pair_id", sorted(PAIRS))
def test_client_pair_end_to_end_through_the_real_api(extracts_client, pair_id: int) -> None:
    reference, documents = _process_pair(extracts_client, pair_id)

    # -- 1. Both documents reach "ready" with the manifest's document_kind;
    # nothing FAILED or discarded.
    for filename, document in documents.items():
        manifest_entry = _manifest_entry_by_filename(filename)
        assert document["status"] == "ready", (filename, document)
        assert document["kind"] == manifest_entry["document_kind"], (filename, document)

    with _session(extracts_client) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()
        assessment = session.scalars(
            select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
        ).one()

        # -- 2. Assessment persisted with all six mandatory columns non-null,
        # matching the manifest, and every operation carries a governed
        # category and its raw label.
        expected_assessment = _expected_assessment_identity(pair_id)
        for field, expected_value in expected_assessment.items():
            actual = getattr(assessment, field)
            assert actual == expected_value, f"assessment.{field}: {actual!r} != {expected_value!r}"

        operations = list(
            session.scalars(
                select(AssessmentOperation)
                .where(AssessmentOperation.assessment_id == assessment.id)
                .order_by(AssessmentOperation.sequence_no)
            ).all()
        )
        assert operations, "expected at least one assessment operation"
        for operation in operations:
            assert operation.category in {"labour", "paint", "parts", "extras"}, operation.category
            assert operation.raw_category

        # -- 3. Invoice persisted with invoice_number (tilde intact),
        # claim_reference, and policy_number either printed or filled with
        # field_sources attribution. Every line carries a line_item_type and
        # raw_category, and the section-total rows are exactly the expected
        # set and never benchmarkable.
        expected_invoice = _expected_invoice_identity(pair_id)
        assert invoice.invoice_number == expected_invoice["invoice_number"]
        assert "~" in invoice.invoice_number
        assert invoice.claim_reference == expected_invoice["claim_reference"]
        assert invoice.policy_number == expected_invoice["policy_number"]
        assert invoice.vehicle is not None
        assert invoice.vehicle.make == expected_invoice["vehicle_make"]
        assert invoice.vehicle.model == expected_invoice["vehicle_model"]

        document_row = session.get(Document, invoice.document_id)
        field_sources = (document_row.metadata_json or {}).get("field_sources") or {}
        expected_filled = GAP_FILLED_INVOICE_FIELDS[pair_id]
        for field_name, source_key, expected_value in (
            ("make", "make", expected_invoice["vehicle_make"]),
            ("model", "model", expected_invoice["vehicle_model"]),
            ("policy_number", "policy_number", expected_invoice["policy_number"]),
        ):
            if field_name in expected_filled:
                assert field_sources[source_key]["label"] == "Filled from engineer assessment"
                assert field_sources[source_key]["value"] == expected_value
            else:
                assert source_key not in field_sources, (
                    f"{source_key} was printed on the invoice and must not be gap-filled"
                )

        lines = list(
            session.scalars(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice.id)
                .order_by(InvoiceLineItem.sequence_no)
            ).all()
        )
        assert lines
        for line in lines:
            assert line.line_item_type, line
            assert line.raw_category, line

        section_totals = [line for line in lines if line.is_section_total]
        assert {line.line_item_type for line in section_totals} == EXPECTED_SECTION_TOTAL_TYPES[pair_id]
        for line in section_totals:
            # A section total is the value of a whole section, never a priced
            # item: it carries no part number, no unit price, and an
            # ``unknown`` item kind, so it can never satisfy
            # ``ExtractedLine.benchmarkable`` (app/extraction/schemas.py).
            assert line.item_kind == LineItemKind.UNKNOWN
            assert line.part_number is None
            assert line.unit_price_net is None

        # -- 4. Pairing: paired, with the expected confidence and
        # positive-only reasons that never leak an invoice number or the
        # unrelated "Assessment Ref" as a pairing key.
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert not any("conflict" in reason for reason in assessment.pair_reasons_json)
        joined_reasons = " ".join(assessment.pair_reasons_json)
        assert "BOY1537" not in joined_reasons
        assert invoice.invoice_number not in joined_reasons

        payload = engineer_assessment_payload(assessment, session)
        verdicts = payload["pair_key_verdicts"]
        assert {entry["key"]: entry["state"] for entry in verdicts} == (
            EXPECTED_KEY_STATES[pair_id]
        )
        # The confidence is checked through its own counts, so a denominator
        # that regressed to a flat three would fail here rather than divide
        # out to the same 1.0.
        matched = sum(1 for entry in verdicts if entry["state"] == "matched")
        compared = sum(1 for entry in verdicts if entry["compared"])
        assert (matched, compared) == EXPECTED_KEY_COUNTS[pair_id]
        assert assessment.pair_confidence == pytest.approx(matched / compared)

        # -- 5. Gap-fill and manual review, where the client called it out
        # explicitly: format 7's invoice is never held up for a missing
        # vehicle, format 2's rolled-up invoice is always manual review.
        invoice_filename = next(
            filename for filename in PAIRS[pair_id] if "assessment" not in filename.lower()
        )
        invoice_document = documents[invoice_filename]
        if pair_id == 7:
            assert invoice_document["manual_review"] is False
            assert invoice_document["manual_review_reason"] is None
            assert invoice.vehicle.make == "HYUNDAI"
            assert invoice.vehicle.model == "140 SE Nav"
        if pair_id == 2:
            assert invoice_document["manual_review"] is True
            assert invoice_document["manual_review_reason"].startswith(
                "Line-item information is not available"
            )

        # -- 7. Printed-versus-row disagreements: filed as WARNING findings,
        # with both figures kept verbatim (nothing reconciled or corrected).
        for line_item_type, measure, printed, rows in DISAGREEMENTS[pair_id]:
            finding = session.scalars(
                select(ClaimConsistencyFinding).where(
                    ClaimConsistencyFinding.finding_code == "ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT",
                    ClaimConsistencyFinding.source_entity_id == assessment.id,
                    ClaimConsistencyFinding.field_name == f"{line_item_type} {measure}",
                )
            ).one()
            assert finding.severity == Severity.WARNING
            assert finding.expected_value == printed
            assert finding.observed_value == rows

        extraction_payload = assessment.extraction_payload_json
        for line_item_type, measure, printed, rows in DISAGREEMENTS[pair_id]:
            printed_values = (
                extraction_payload["printed_work_units"]
                if measure == "work units"
                else extraction_payload["printed_totals"]
            )[line_item_type]
            row_values = (
                extraction_payload["row_work_units"]
                if measure == "work units"
                else extraction_payload["row_totals"]
            )
            # Both figures still live in the payload untouched -- neither was
            # dropped nor reconciled towards the other.
            assert printed in printed_values.values()
            assert row_values[line_item_type] == rows

        # -- 8. Governance: no HistoricalObservation is ever sourced from an
        # assessment or a section-total row.
        observations = list(session.scalars(select(HistoricalObservation)).all())
        assert observations == []
        section_total_ids = {line.id for line in section_totals}
        observed_source_ids = {
            observation.source_line_item_id
            for observation in observations
            if observation.source_line_item_id
        }
        assert observed_source_ids.isdisjoint(section_total_ids)

        if pair_id == 2:
            # Format 2's invoice is wholly rolled up -- no itemised rows
            # exist for run_case_comparison to map, so the endpoint refuses
            # rather than silently comparing nothing.
            compare_response = extracts_client.post(f"/api/v1/claims/{reference}/compare")
            # The test database seeds no ontology items and no historical
            # claims, so the endpoint's own pre-flight check ("The ontology
            # bank is empty...") fires before run_case_comparison's
            # "Extraction is incomplete" check ever runs (see
            # tests/integration/test_extracts_persistence.py::
            # test_format_2_section_totals_are_never_mapped_priced_or_compared
            # for that check exercised directly against the service
            # function). Either way the invariant under test holds: the
            # request is refused with a 409 and zero comparisons are ever
            # created for the section-total rows.
            assert compare_response.status_code == 409, compare_response.text
            comparisons = list(session.scalars(select(PriceComparison)).all())
            assert comparisons == []
        else:
            # Formats 1 and 7 carry itemised parts/extras rows alongside
            # their section totals, so comparison can run; the section
            # totals must never be mapped or priced.
            result = run_case_comparison(session, case)
            assert result["status"] == "succeeded"
            session.commit()
            mapped_ids = set(session.scalars(select(OntologyMapping.invoice_line_item_id)).all())
            compared_ids = set(session.scalars(select(PriceComparison.invoice_line_item_id)).all())
            assert section_total_ids.isdisjoint(mapped_ids)
            assert section_total_ids.isdisjoint(compared_ids)

        # -- 6. Section breakdowns via the extracts endpoint.
        response = extracts_client.get(f"/api/v1/claims/{reference}/extracts")
        assert response.status_code == 200, response.text
        extracts_payload = response.json()
        breakdowns = {
            breakdown["line_item_type"]: breakdown
            for breakdown in extracts_payload["section_breakdowns"]
            if breakdown["invoice_id"] == invoice.id
        }
        assert set(breakdowns) == EXPECTED_SECTION_TOTAL_TYPES[pair_id]

        if pair_id == 1:
            labour = breakdowns["labour"]
            assert labour["matches"] is True
            assert len(labour["rows"]) == 41
            assert _money(labour["rows_total"]) == Decimal("1410.60")
            assert _money(labour["assessment_total"]) == Decimal("2509.20")
        if pair_id == 2:
            labour = breakdowns["labour"]
            assert _money(labour["invoice_total"]) == Decimal("2008.00")
            assert _money(labour["assessment_total"]) == Decimal("1112.00")
            assert labour["matches"] is False
            assert _money(labour["difference"]) == Decimal("896.00")
            assert len(labour["rows"]) == 17


def test_cross_pair_isolation_by_claim_reference(extracts_client) -> None:
    """Formats 1 and 7 share one invoice number ("343653726836/1~3538") for
    two different claims. Loading both into one case must still pair each
    assessment to its own invoice -- by claim reference, never the shared
    invoice number -- and the extracts endpoint must key each section
    breakdown to the right invoice_id rather than blending the two.
    """

    reference = "CROSS-PAIR-ISOLATION"
    created = extracts_client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": "2026/CROSS-PAIR/ISOLATION",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text
    for pair_id in (1, 7):
        for filename in PAIRS[pair_id]:
            _upload_and_process(extracts_client, reference, filename)

    with _session(extracts_client) as session:
        assessments = list(session.scalars(select(EngineerAssessment)).all())
        assert len(assessments) == 2
        invoices_by_id = {
            invoice.id: invoice for invoice in session.scalars(select(Invoice)).all()
        }
        assert len(invoices_by_id) == 2
        # Both invoices genuinely do share the printed invoice number --
        # that is the whole point of the regression.
        assert len({invoice.invoice_number for invoice in invoices_by_id.values()}) == 1

        for assessment in assessments:
            assert assessment.pair_status == "paired"
            paired_invoice = invoices_by_id[assessment.paired_invoice_id]
            assert paired_invoice.claim_reference == assessment.claim_reference

        assert len({assessment.paired_invoice_id for assessment in assessments}) == 2

    response = extracts_client.get(f"/api/v1/claims/{reference}/extracts")
    assert response.status_code == 200, response.text
    payload = response.json()

    invoice_extracts = payload["invoice_extracts"]
    assert len(invoice_extracts) == 2
    invoice_ids = {extract["invoice_id"] for extract in invoice_extracts}
    assert len(invoice_ids) == 2

    labour_breakdowns_by_invoice_id = {
        breakdown["invoice_id"]: breakdown
        for breakdown in payload["section_breakdowns"]
        if breakdown["line_item_type"] == "labour"
    }
    assert set(labour_breakdowns_by_invoice_id) == invoice_ids
    invoice_totals = sorted(
        Decimal(breakdown["invoice_total"]) for breakdown in labour_breakdowns_by_invoice_id.values()
    )
    assert invoice_totals == [Decimal("1910.00"), Decimal("2509.20")]


def test_new_invoice_missing_vehicle_still_pairs_and_gap_fills(extracts_client, tmp_path) -> None:
    """"Build on this in such a way that if I input other files also it
    should work the same" (Nikitha). Format 7's invoice already prints no
    vehicle make/model, so this exercises the same shape on a file the
    pipeline has never seen: format 2's invoice with its Vehicle Make/Vehicle
    Model cells stripped by python-docx. It must still parse, pair on
    registration + claim + policy (all three are unaffected and still
    printed), and gain its vehicle identity from the assessment.
    """

    reference = "NEW-FILE-JUST-WORKS"
    created = extracts_client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": "2026/NEW-FILE/JUST-WORKS",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text

    modified_invoice_path = _invoice_without_vehicle_make_model(tmp_path)

    assessment_uploaded = extracts_client.post(
        f"/api/v1/claims/{reference}/documents",
        files={
            "file": (
                "DL_Auda_format_2_assessment.docx",
                (FIXTURES / "DL_Auda_format_2_assessment.docx").read_bytes(),
                DOCX_MIME,
            )
        },
        data={"role": "current"},
    )
    assert assessment_uploaded.status_code == 200, assessment_uploaded.text
    assessment_processed = extracts_client.post(
        f"/api/v1/documents/{assessment_uploaded.json()['id']}/process"
    )
    assert assessment_processed.status_code == 200, assessment_processed.text

    invoice_uploaded = extracts_client.post(
        f"/api/v1/claims/{reference}/documents",
        files={
            "file": (
                "invoice_2_without_vehicle.docx",
                modified_invoice_path.read_bytes(),
                DOCX_MIME,
            )
        },
        data={"role": "current"},
    )
    assert invoice_uploaded.status_code == 200, invoice_uploaded.text
    invoice_processed = extracts_client.post(
        f"/api/v1/documents/{invoice_uploaded.json()['id']}/process"
    )
    assert invoice_processed.status_code == 200, invoice_processed.text
    invoice_document = invoice_processed.json()["document"]

    # It still parses: ready, correct kind, its four rolled-up section-total
    # lines survive with their printed values intact.
    assert invoice_document["status"] == "ready"
    assert invoice_document["kind"] == "repair_invoice"

    with _session(extracts_client) as session:
        invoice = session.scalars(select(Invoice)).one()
        assessment = session.scalars(select(EngineerAssessment)).one()

        header = invoice.extraction_payload_json["header"]
        assert header["vehicle_make"] is None
        assert header["vehicle_model"] is None

        lines = list(
            session.scalars(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice.id)
                .order_by(InvoiceLineItem.sequence_no)
            ).all()
        )
        assert {
            line.line_item_type: _money(line.line_total_net) for line in lines
        } == {
            "parts": Decimal("448.91"),
            "paint_materials": Decimal("1034.02"),
            "labour": Decimal("2008.00"),
            "extras": Decimal("627.00"),
        }

        # It pairs on registration + claim + policy -- none of which the
        # missing vehicle identity touches -- at full confidence.
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert assessment.pair_confidence == pytest.approx(1.0)
        assert assessment.pair_reasons_json == [
            "registration exact match",
            "claim reference exact match",
            "policy number exact match",
        ]

        # It gains make/model from the assessment, attributed the same way
        # format 7's invoice is.
        assert invoice.vehicle is not None
        assert invoice.vehicle.make == "SKODA"
        assert invoice.vehicle.model == "KAROQ SE TSI 115]"
        document_row = session.get(Document, invoice.document_id)
        field_sources = (document_row.metadata_json or {}).get("field_sources") or {}
        for field in ("make", "model"):
            assert field_sources[field]["label"] == "Filled from engineer assessment"
        assert field_sources["make"]["value"] == "SKODA"
        assert field_sources["model"]["value"] == "KAROQ SE TSI 115]"
