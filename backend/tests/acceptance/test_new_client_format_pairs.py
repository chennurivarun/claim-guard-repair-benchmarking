"""Acceptance: formats 5 and 6, and the EXL demo pair, through the real API.

These are the three pairs nothing in the suite had ever parsed. The upload,
process and assertion style is the one
``tests/acceptance/test_client_format_pairs.py`` established for formats 1, 2
and 7; this module stays separate so that file's parametrisation over the
pairs it already covers is untouched.

Two things this module is for.

**The acceptance pair.** Invoices 5 and 6 are the same DLAS template from the
same repairer, both carrying an embedded "Validation note" asserting the
totals are aligned to the engineer's report. Invoice 6 reconciles exactly.
Invoice 5 is out by £78.77: it bills itemised parts (£1,237.50) and
specialist operations (£136.32) while totalling on the report's *summary*
figures (£1,308.46 and £144.13). The tool must surface that, must pass
invoice 6, and must be persuaded by neither note -- both assert the same
thing and only one of them is true.

**The demo pair.** The EXL invoice is a third invoice layout unlike anything
else in the corpus: a bordered label/value table, a rolled-up summary with no
priced rows, a grand total labelled ``Claim`` and four section labels nothing
else prints. ``test_exl_invoice_reconciles_against_its_own_summary`` is the
specification of how it reads. One assertion is still labelled GAP -- the
report's claim reference -- and says why it stays open.

Deterministic and LLM-free: no extractor tier is configured, so the native
``.docx`` parsers do all of the work and every number here is exact, taken
from ``sample-data/client-formats/manifest.json`` and the transcriptions it
was built from.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.database import get_db
from app.enums import Severity
from app.init_db import initialize_database
from app.main import app
from app.models import (
    Case,
    ClaimConsistencyFinding,
    Document,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
    MathFinding,
)

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MANIFEST: list[dict] = json.loads((FIXTURES / "manifest.json").read_text())

PAIRS: dict[int, tuple[str, str]] = {
    5: ("DL_Auda_format_5_assessment.docx", "DL_Repair_Invoice_format_5.docx"),
    6: ("DL_Auda_format_6_assessment.docx", "DL_Repair_Invoice_format_6.docx"),
    8: ("EXL_demo_engineer_report.docx", "EXL_demo_invoice.docx"),
}


def _manifest(filename: str) -> dict:
    return next(entry for entry in MANIFEST if entry["filename"] == filename)


@pytest.fixture
def api(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'new_client_format_pairs.db'}",
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


def _money(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _create_case(client: TestClient, reference: str) -> None:
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": f"2026/{reference}",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text


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


def _process_pair(client: TestClient, pair_id: int) -> tuple[str, dict[str, dict]]:
    reference = f"NEW-PAIR-{pair_id}"
    _create_case(client, reference)
    return reference, {
        filename: _upload_and_process(client, reference, filename)
        for filename in PAIRS[pair_id]
    }


def _findings(session: Session, invoice: Invoice) -> dict[str, list[MathFinding]]:
    grouped: dict[str, list[MathFinding]] = {}
    for finding in session.scalars(
        select(MathFinding).where(MathFinding.invoice_id == invoice.id)
    ).all():
        grouped.setdefault(finding.check_code, []).append(finding)
    return grouped


def _one(findings: dict[str, list[MathFinding]], code: str) -> MathFinding:
    matches = findings.get(code) or []
    assert len(matches) == 1, f"expected exactly one {code}, got {len(matches)}"
    return matches[0]


# --------------------------------------------------------------------------
# 1. Identity -- exactly what each document prints, and nothing it does not
# --------------------------------------------------------------------------


def test_format_5_identity_is_exactly_what_the_pair_prints(api) -> None:
    reference, documents = _process_pair(api, 5)
    for filename, document in documents.items():
        assert document["status"] == "ready", (filename, document)
        assert document["kind"] == _manifest(filename)["document_kind"]

    with _session(api) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        assessment = session.scalars(
            select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
        ).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()

        # The Summary grid and the later page headers agree on D8432196; the
        # page-1 banner's L0987892222 is the outlier and must not win.
        assert assessment.assessment_number == "D8432196"
        assert assessment.claim_reference == "247816542/1"
        assert assessment.policy_number == "PX-784219"
        assert assessment.registration == "CD34EFG"
        assert assessment.vehicle_make == "HYUNDAI"
        assert assessment.vehicle_model == "140 SE Nav"
        assert assessment.vin == "TRN9876543210"
        assert assessment.mileage == 576882

        # A fourth document carrying the shared invoice number, and the
        # tilde survives.
        assert invoice.invoice_number == "343653726836/1~3538"
        assert invoice.claim_reference == "247816542/1"
        # The invoice prints neither a policy number nor a make/model, so
        # each arrives from the assessment with attribution.
        header = invoice.extraction_payload_json["header"]
        assert header["policy_number"] is None
        assert header["vehicle_make"] is None
        assert header["vehicle_model"] is None
        document_row = session.get(Document, invoice.document_id)
        field_sources = (document_row.metadata_json or {}).get("field_sources") or {}
        for field, expected in (
            ("policy_number", "PX-784219"),
            ("make", "HYUNDAI"),
            ("model", "140 SE Nav"),
        ):
            assert field_sources[field]["label"] == "Filled from engineer assessment"
            assert field_sources[field]["value"] == expected

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id


def test_format_6_identity_and_the_heated_windscreen_column_bleed(api) -> None:
    """Format 6 prints ``HEATED WINDSCREEN`` -- a Model Options item -- in
    the left column directly under ``Odometer: 576882 miles``. An unlabelled
    line following a field is not that field's continuation, so neither the
    odometer nor the registration above it may absorb it.
    """

    reference, documents = _process_pair(api, 6)
    for filename, document in documents.items():
        assert document["status"] == "ready", (filename, document)
        assert document["kind"] == _manifest(filename)["document_kind"]

    with _session(api) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        assessment = session.scalars(
            select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
        ).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()

        assert assessment.assessment_number == "R6725148"
        # The corpus's first "/2" suffix: the slash and the suffix survive.
        assert assessment.claim_reference == "318742905/2"
        assert assessment.policy_number == "PK-562847"
        assert assessment.registration == "GH58JKL"
        assert assessment.vehicle_make == "HYUNDAI"
        assert assessment.vehicle_model == "140 SE Nav"
        assert assessment.vin == "TRN5647382910"
        # The bleed regression: mileage is the printed odometer alone, and
        # the registration did not pick the stray line up either.
        assert assessment.mileage == 576882
        assert "HEATED" not in (assessment.registration or "")
        assert "HEATED" not in (assessment.vehicle_model or "")

        assert invoice.invoice_number == "343653726836/1~3538"
        assert invoice.claim_reference == "318742905/2"
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id


def test_exl_demo_pair_identity(api) -> None:
    """The demo pair's identity, including the two keys the parser misses.

    GAPs are labelled; everything else is what the documents print.
    """

    reference, documents = _process_pair(api, 8)
    for filename, document in documents.items():
        assert document["status"] == "ready", (filename, document)
        assert document["kind"] == _manifest(filename)["document_kind"]

    with _session(api) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        assessment = session.scalars(
            select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
        ).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()

        assert assessment.assessment_number == "AAA6576879"  # "Estimate ID"
        assert assessment.policy_number == "200-1222-33333"
        assert assessment.registration == "ABC02QQQ"
        assert assessment.vehicle_make == "VOLVO"
        assert assessment.vehicle_model == "XC40(XZ)(18-)"
        # GAP, deliberately still open: the report prints "Claim: ABC 123456"
        # and its invoice prints "123456". Reading the label -- which is a
        # three-line change, and the only thing needed is to accept "Claim"
        # when a colon follows it -- makes the two documents disagree on the
        # claim reference, and ``_compare_pair_keys`` scores that a conflict,
        # which is fatal: the demo pair stops pairing at all. Leaving the
        # field empty is the lesser harm until the pairing rule decides
        # whether a printed prefix token may be tolerated. See the comment on
        # ``label_grid.FIELD_SYNONYMS["claim_reference"]``.
        assert assessment.claim_reference is None

        assert invoice.invoice_number == "ABC1234"
        # No "/n" suffix, against format 2's "123456/1".
        assert invoice.claim_reference == "123456"
        # Eight characters, not a standard UK plate shape, read whole.
        assert invoice.vehicle.registration == "ABC02QQQ"
        # Brackets and a trailing hyphen kept: a model is free text.
        assert invoice.vehicle.model == "XC40(XZ)(18-)"
        assert invoice.vehicle.make == "VOLVO"
        # The label is "Vehicle registration" with a lower-case r, against
        # the DLAS "Vehicle Registration": label matching stays insensitive.
        # The repairer is the page-2 footer company, not the party billed at
        # the top ("EXL Insurance Company Ltd").
        assert invoice.supplier_name == "EXL Repairer Services Ltd"
        # The only VAT registration number in the corpus.
        assert invoice.supplier_vat_number == "106 9411 33"
        # "Insured Name | John Smith": the longer label is in the synonym
        # table, so none of it is left on the front of the value.
        assert invoice.customer_name == "John Smith"

        # The report prints no claim reference the reader takes and the
        # invoice prints no policy number, so registration is the only
        # comparable key and the pair is flagged weak rather than strong.
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert any("weak pair" in reason for reason in assessment.pair_reasons_json)


def test_exl_claim_reference_never_collides_with_format_2(api) -> None:
    """``123456`` (EXL demo) and ``123456/1`` (format 2) are two different
    claims separated only by the suffix. Loaded into one case they must stay
    two invoices with two distinct references -- a normaliser that stripped
    the suffix would merge them.
    """

    reference = "SUFFIX-COLLISION"
    _create_case(api, reference)
    for filename in ("EXL_demo_invoice.docx", "DL_Invoice_2_request_for_payment.docx"):
        _upload_and_process(api, reference, filename)

    with _session(api) as session:
        references = sorted(
            invoice.claim_reference for invoice in session.scalars(select(Invoice)).all()
        )
        assert references == ["123456", "123456/1"]


# --------------------------------------------------------------------------
# 2. The pair that earns the lane: invoice 5 against invoice 6
# --------------------------------------------------------------------------


def test_invoice_6_reconciles_against_its_own_printed_lines(api) -> None:
    """Parts £1,287.94 + specialist ops £141.87 + labour £2,611.41 + paint &
    materials £1,071.52 = £5,112.74, VAT £1,022.55, total £6,135.29 -- and
    every one of those agrees with the assessment. The only check that fails
    is the client's own 13p defect: the twelve Specialist Operation rows sum
    to £142.00 under a printed £141.87, exactly as the report's EXTRAS page
    does.
    """

    reference, _ = _process_pair(api, 6)

    with _session(api) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()
        assessment = session.scalars(
            select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
        ).one()

        assert _money(invoice.parts_net) == Decimal("1287.94")
        assert _money(invoice.other_net) == Decimal("141.87")
        assert _money(invoice.labour_net) == Decimal("2611.41")
        assert _money(invoice.paint_net) == Decimal("1071.52")
        assert _money(invoice.subtotal_net) == Decimal("5112.74")
        assert _money(invoice.vat_total) == Decimal("1022.55")
        assert _money(invoice.gross_total) == Decimal("6135.29")
        assert (
            Decimal("1287.94") + Decimal("141.87") + Decimal("2611.41") + Decimal("1071.52")
            == Decimal("5112.74")
        )

        # Every figure agrees with the assessment it was written against.
        assert _money(assessment.parts_net) == _money(invoice.parts_net)
        assert _money(assessment.extras_net) == _money(invoice.other_net)
        assert _money(assessment.labour_net) == _money(invoice.labour_net)
        assert _money(assessment.paint_net) == _money(invoice.paint_net)
        assert _money(assessment.subtotal_net) == _money(invoice.subtotal_net)
        assert _money(assessment.vat_total) == _money(invoice.vat_total)
        assert _money(assessment.gross_total) == _money(invoice.gross_total)

        findings = _findings(session, invoice)
        # The summary reconciles: VAT is 20% of the invoice's own subtotal
        # and the gross is that subtotal plus that VAT.
        assert _one(findings, "VAT_MISCALC").status.value == "pass"
        assert _one(findings, "TOTAL_MISMATCH").status.value == "pass"
        assert _one(findings, "PARTS_TOTAL_MISMATCH").status.value == "pass"
        # ...and the one failure is the document's own 13p row-sum gap.
        extras = _one(findings, "EXTRAS_TOTAL_MISMATCH")
        assert extras.status.value == "fail"
        assert _money(extras.expected_value) == Decimal("142.00")
        assert _money(extras.observed_value) == Decimal("141.87")


def test_invoice_5_is_out_by_78_77_and_the_tool_surfaces_it(api) -> None:
    """Invoice 5's own printed lines sum to £5,115.42, but its VAT is 20% of
    the report's £5,194.19 and its total is £6,233.03.

    The tool catches it today: ``TOTAL_MISMATCH`` fails by exactly £78.77 and
    ``VAT_MISCALC`` by £15.76 (20% of the same £78.77). The gap decomposes as
    parts £1,308.46 - £1,237.50 = £70.96 plus additional £144.13 - £136.32 =
    £7.81, which is asserted here against the two documents' own figures
    rather than restated as a constant.
    """

    reference, _ = _process_pair(api, 5)

    with _session(api) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()

        # What the invoice itself prints.
        assert _money(invoice.parts_net) == Decimal("1237.50")
        assert _money(invoice.other_net) == Decimal("136.32")
        assert _money(invoice.labour_net) == Decimal("2653.01")
        assert _money(invoice.paint_net) == Decimal("1088.59")
        assert _money(invoice.subtotal_net) == Decimal("5115.42")
        assert _money(invoice.vat_total) == Decimal("1038.84")
        assert _money(invoice.gross_total) == Decimal("6233.03")

        # The report's summary figures, which is what the invoice totalled on.
        report_parts = Decimal("1308.46")
        report_additional = Decimal("144.13")
        gap = (report_parts - _money(invoice.parts_net)) + (
            report_additional - _money(invoice.other_net)
        )
        assert gap == Decimal("78.77")
        assert _money(invoice.subtotal_net) + gap == Decimal("5194.19")
        assert (
            _money(invoice.subtotal_net) + gap + _money(invoice.vat_total)
            == _money(invoice.gross_total)
        )

        findings = _findings(session, invoice)
        total = _one(findings, "TOTAL_MISMATCH")
        assert total.status.value == "fail"
        assert total.severity == Severity.ERROR
        assert _money(total.expected_value) == Decimal("6154.26")
        assert _money(total.observed_value) == Decimal("6233.03")
        assert _money(total.difference) == gap

        vat = _one(findings, "VAT_MISCALC")
        assert vat.status.value == "fail"
        assert vat.severity == Severity.ERROR
        assert _money(vat.expected_value) == Decimal("1023.08")
        assert _money(vat.observed_value) == Decimal("1038.84")
        # 20% of the same £78.77, to the penny the invoice rounds to.
        assert _money(vat.difference) == Decimal("15.76")

        # The parts section itself is internally perfect -- the £70.96 is
        # not a bad row sum, it is a total the invoice never printed.
        assert _one(findings, "PARTS_TOTAL_MISMATCH").status.value == "pass"


def test_neither_validation_note_is_treated_as_evidence(api) -> None:
    """Invoices 5 and 6 carry the same kind of embedded "Validation note".
    Invoice 6's claims are all true; invoice 5's are not -- it cites "Total
    Additional Costs £144.13" while the document's own Specialist Operation
    block totals £136.32.

    The note must never become a line item, and must never supply a total the
    printed lines contradict.
    """

    for pair_id, note_figure, printed_figure in (
        (5, Decimal("144.13"), Decimal("136.32")),
        (6, Decimal("141.87"), Decimal("141.87")),
    ):
        reference = f"NEW-PAIR-{pair_id}"
        _create_case(api, reference)
        for filename in PAIRS[pair_id]:
            _upload_and_process(api, reference, filename)

        with _session(api) as session:
            case = session.scalars(
                select(Case).where(Case.case_reference == reference)
            ).one()
            invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()

            # The extras total is the printed Specialist Operation total,
            # never the figure the note asserts.
            assert _money(invoice.other_net) == printed_figure
            if pair_id == 5:
                assert _money(invoice.other_net) != note_figure

            lines = session.scalars(
                select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id)
            ).all()
            # The note is a 40-plus word paragraph quoting every total on the
            # invoice; none of it is a priced row.
            for line in lines:
                assert "Validation note" not in (line.raw_description or "")
                assert "aligned to report" not in (line.raw_description or "")
                assert "Assessment" not in (line.raw_description or "")
            assert not any(
                _money(line.line_total_net) == note_figure and pair_id == 5 for line in lines
            )


def test_format_5_and_6_reports_keep_both_sides_of_every_disagreement(api) -> None:
    """Each report's printed section total and its own row sum are both
    filed, verbatim, as WARNING findings -- neither is reconciled towards the
    other. Formats 5 and 6 carry the labour 218-against-101 work-unit gap the
    whole family carries, and an extras gap of 18p and 13p respectively.
    """

    expected: dict[int, list[tuple[str, str, str]]] = {
        5: [
            ("labour work units", "218", "101"),
            ("extras total", "136.32", "136.50"),
        ],
        6: [
            ("labour work units", "218", "101"),
            ("extras total", "141.87", "142.00"),
        ],
    }
    for pair_id, rows in expected.items():
        reference = f"DISAGREEMENT-{pair_id}"
        _create_case(api, reference)
        for filename in PAIRS[pair_id]:
            _upload_and_process(api, reference, filename)

        with _session(api) as session:
            case = session.scalars(
                select(Case).where(Case.case_reference == reference)
            ).one()
            assessment = session.scalars(
                select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
            ).one()
            for field_name, printed, row_sum in rows:
                finding = session.scalars(
                    select(ClaimConsistencyFinding).where(
                        ClaimConsistencyFinding.finding_code
                        == "ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT",
                        ClaimConsistencyFinding.source_entity_id == assessment.id,
                        ClaimConsistencyFinding.field_name == field_name,
                    )
                ).one()
                assert finding.severity == Severity.WARNING
                assert finding.expected_value == printed
                assert finding.observed_value == row_sum


# --------------------------------------------------------------------------
# 3. The EXL layout, read
# --------------------------------------------------------------------------


def test_exl_invoice_reconciles_against_its_own_summary(api) -> None:
    """The demo invoice is arithmetically perfect and now reads that way.

    On paper: labour 2019.98 + parts 872.38 + paint 389.81 + additional
    extras 785.75 + collection & delivery 156.14 = 4224.06, VAT 844.81,
    ``Claim`` 5068.87. The engineer report prints the same 5068.87.

    Four things had to change for that to come out of the pipeline, and each
    is asserted below: the grand total is labelled ``Claim``; the bare labels
    ``Paint`` and ``Additional Extras`` are section totals, not priced rows;
    ``Collection & Delivery`` is a section code nothing else in the corpus
    prints and its money is extras; and ``Recovery``, printed with an empty
    Amount cell, stays visible as a row the document printed.
    """

    reference, documents = _process_pair(api, 8)

    with _session(api) as session:
        case = session.scalars(select(Case).where(Case.case_reference == reference)).one()
        invoice = session.scalars(select(Invoice).where(Invoice.case_id == case.id)).one()
        assessment = session.scalars(
            select(EngineerAssessment).where(EngineerAssessment.case_id == case.id)
        ).one()

        # The report reads the same figures it always did.
        assert _money(assessment.labour_net) == Decimal("2019.98")
        assert _money(assessment.parts_net) == Decimal("872.38")
        assert _money(assessment.paint_net) == Decimal("389.81")
        assert _money(assessment.extras_net) == Decimal("941.89")
        assert _money(assessment.subtotal_net) == Decimal("4224.06")
        assert _money(assessment.vat_total) == Decimal("844.81")
        assert _money(assessment.gross_total) == Decimal("5068.87")

        # The grand total is labelled "Claim" -- no "Total", "Grand Total",
        # "Invoice Total" or "Total Due" appears anywhere on the document. It
        # is read because the row is a whole line of "Claim" and one amount
        # printed directly beneath the block's VAT row; the "Claim Reference"
        # row two tables above and the bare "Claim" heading on every DL Auda
        # report satisfy neither half.
        assert _money(invoice.gross_total) == Decimal("5068.87")

        lines = list(
            session.scalars(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice.id)
                .order_by(InvoiceLineItem.sequence_no)
            ).all()
        )
        by_description = {line.raw_description: line for line in lines}

        # The grand total is the invoice's answer, never a thing it billed
        # for, so it is not a line item at all.
        assert "Claim" not in by_description

        # Every printed summary row is a section total, including the bare
        # labels the vocabulary did not know.
        assert [line.raw_description for line in lines] == [
            "Labour",
            "Parts",
            "Paint",
            "Additional Extras",
            "Collection & Delivery",
            "Recovery",
        ]
        assert all(line.is_section_total for line in lines)

        assert _money(by_description["Labour"].line_total_net) == Decimal("2019.98")
        assert by_description["Labour"].line_item_type == "labour"
        assert _money(by_description["Parts"].line_total_net) == Decimal("872.38")
        assert by_description["Parts"].line_item_type == "parts"
        # Bare "Paint" on a summary block is the paint *and materials*
        # figure: 389.81 is the report's "Total Paint & Materials", and the
        # report's paintwork labour is inside its labour total.
        assert _money(by_description["Paint"].line_total_net) == Decimal("389.81")
        assert by_description["Paint"].line_item_type == "paint_materials"
        assert _money(by_description["Additional Extras"].line_total_net) == Decimal("785.75")
        assert by_description["Additional Extras"].line_item_type == "extras"
        # A line-item type nothing else in the corpus prints. The vocabulary
        # is open, so it keeps its own code rather than being flattened into
        # an existing one -- its money is extras, which is where the paired
        # report rolls it up.
        assert _money(by_description["Collection & Delivery"].line_total_net) == Decimal(
            "156.14"
        )
        assert by_description["Collection & Delivery"].line_item_type == "collection_and_delivery"
        # Printed with an empty Amount cell. It stays visible as a row the
        # document printed, and carries no amount, rate, VAT or gross -- a
        # zero here would be the tool inventing a figure the document does
        # not state.
        recovery = by_description["Recovery"]
        assert recovery.line_item_type == "recovery"
        assert recovery.line_total_net is None
        assert recovery.vat_rate is None
        assert recovery.vat_amount is None
        assert recovery.vat_applicable is False

        # The section totals the summary states, and the arithmetic they
        # close. Extras is the two extras rows together, exactly as the
        # report rolls them up.
        assert _money(invoice.labour_net) == Decimal("2019.98")
        assert _money(invoice.parts_net) == Decimal("872.38")
        assert _money(invoice.paint_net) == Decimal("389.81")
        assert _money(invoice.other_net) == Decimal("941.89")
        assert _money(invoice.subtotal_net) == Decimal("4224.06")
        assert _money(invoice.vat_total) == Decimal("844.81")

        # The point of the lane: a document that is correct to the penny
        # produces no arithmetic finding.
        findings = _findings(session, invoice)
        for code in ("PARTS_TOTAL_MISMATCH", "LABOUR_TOTAL_MISMATCH"):
            assert _one(findings, code).status.value == "not_applicable"
        for code in ("SUBTOTAL_MISMATCH", "VAT_MISCALC", "TOTAL_MISMATCH"):
            finding = _one(findings, code)
            assert finding.status.value == "pass", (code, finding.observed_value)

        # Still routed to manual review as rolled up: the invoice prints no
        # priced rows at all, which is correct and intended.
        invoice_document = documents["EXL_demo_invoice.docx"]
        assert invoice_document["manual_review"] is True
        assert invoice_document["manual_review_reason"].startswith(
            "Line-item information is not available"
        )




def test_all_eight_pairs_in_primary_source(api):
    reference = 'ALL-EIGHT-SOURCE'
    _create_case(api, reference)
    entries = sorted(MANIFEST, key=lambda row: row['document_kind'] == 'engineer_assessment')
    for entry in entries:
        filename = entry['filename']
        uploaded = api.post(
            f'/api/v1/claims/{reference}/documents',
            files={'file': (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
            data={'intake_group': 'historical_claim'},
        )
        assert uploaded.status_code == 200, (filename, uploaded.text)
        processed = api.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
        assert processed.status_code == 200, (filename, processed.text)
        assert processed.json()['document']['kind'] == entry['document_kind'], filename
    sweep = api.post(f'/api/v1/claims/{reference}/documents/link-sweep')
    assert sweep.status_code == 200, sweep.text
    payload = api.get(f'/api/v1/claims/{reference}/extracts?intake_group=historical_claim').json()
    assert len(payload['invoice_extracts']) == 8
    assert len(payload['assessment_extracts']) == 8
    for assessment in payload['assessment_extracts']:
        assert assessment['pair_status'] == 'paired', assessment
        invoice = next(row for row in payload['invoice_extracts']
                       if row['vehicle_registration'] == assessment['vehicle_registration'])
        assert invoice['paired_assessment_number'] == assessment['assessment_number']
        assert invoice['invoice_number'] == assessment['paired_invoice_number']
        assert assessment['lines'], assessment


def test_assessment_picker_hint_recovers_missed_page_classification(api, monkeypatch):
    from app.extraction.schemas import PageType
    from app.services import document_processing

    reference = 'ASSESSMENT-HINT'
    _create_case(api, reference)
    filename = 'DL_Auda_format_1_assessment.docx'
    uploaded = api.post(
        f'/api/v1/claims/{reference}/documents',
        files={'file': ('report.docx', (FIXTURES / filename).read_bytes(), DOCX_MIME)},
        data={'intake_group': 'historical_claim', 'document_kind': 'engineer_assessment'},
    )
    assert uploaded.status_code == 200, uploaded.text
    original_analyse = document_processing.PDFPipeline.analyse

    def miss_classification(self, *args, **kwargs):
        result = original_analyse(self, *args, **kwargs)
        for page in result.pages:
            page.page_type = PageType.OTHER
        result.engineer_assessments = []
        return result

    monkeypatch.setattr(document_processing.PDFPipeline, 'analyse', miss_classification)
    processed = api.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
    assert processed.status_code == 200, processed.text
    extracts = api.get(f'/api/v1/claims/{reference}/extracts?intake_group=historical_claim').json()
    assert len(extracts['assessment_extracts']) == 1
    assert extracts['assessment_extracts'][0]['assessment_number'] == 'D7576879'
    assert extracts['invoice_extracts'] == []
