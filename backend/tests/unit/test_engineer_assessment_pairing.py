"""Pairing, gap-fill and the total-to-section breakdown, on the client pairs.

Everything here is deterministic: no extractor is configured in the test
settings, so the native parsers do the work and the three client `.docx`
pairs are uploaded through the real API exactly as
`tests/integration/test_extracts_persistence.py` does.

The rules under test are identity rules, so the interesting cases are the
negative ones: formats 1 and 7 print the *same* invoice number
("343653726836/1~3538") for two different claims, and format 2's invoice
prints an "Assessment Ref" ("BOY1537") that matches nothing on the report it
arrives with. Neither may ever become a pairing key.

The other negative case has no fixture, because no client document shows it:
two engineer reports reaching for one invoice. A gap-filled value must never
become the evidence the next report is judged against, so those cases are
built on top of an uploaded invoice with synthetic assessments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.database import get_db
from app.domain.normalisation import normalise_identifier
from app.enums import DocumentRole, UploadStatus
from app.init_db import initialize_database
from app.main import app
from app.models import Document, EngineerAssessment, Invoice
from app.services.engineer_assessment import (
    engineer_assessment_payload,
    run_case_gap_fill,
    section_breakdown_for_invoice,
)
from app.services.vehicle_classification import normalise_registration

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

PAIRS: dict[int, tuple[str, str]] = {
    1: ("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_1.docx"),
    2: ("DL_Auda_format_2_assessment.docx", "DL_Invoice_2_request_for_payment.docx"),
    7: ("DL_Auda_format_7_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
}

UPLOAD_ORDERS = ("assessment_first", "invoice_first")


def test_normalise_identifier_keeps_the_claim_separator() -> None:
    # "base/incident" is one identity in two parts: dropping the separator
    # would make claim 123456/1 indistinguishable from the claim 1234561.
    assert normalise_identifier("245338996/1") == "245338996/1"
    assert normalise_identifier("245338996 / 1") == "245338996/1"
    assert normalise_identifier("123456/1") != normalise_identifier("1234561")
    assert normalise_identifier("123456/1") != normalise_identifier("123456/2")
    assert normalise_identifier("AB12 XYZ") == "AB12XYZ"
    assert normalise_identifier("PL-739284") == "PL739284"
    assert normalise_identifier("  ") is None
    assert normalise_identifier("--") is None
    assert normalise_identifier("/") is None
    assert normalise_identifier(None) is None


def test_registration_normalisation_has_one_implementation() -> None:
    # A registration never prints a "/", so keeping the separator changes
    # nothing for it and the two functions stay the same function.
    for value in ("ab12 xyz", "AB12-XYZ", None, ""):
        assert normalise_registration(value) == normalise_identifier(value)


@pytest.fixture
def pairing_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pairing.db'}",
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


def _process_pair(
    client: TestClient,
    pair_id: int,
    *,
    files: tuple[str, ...] | None = None,
    order: str = "assessment_first",
) -> str:
    """Upload and process one client pair (or an arbitrary mix); return its case reference."""

    reference = f"PAIRING-{pair_id}"
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": reference,
            "claim_number": f"2026/PAIRING/{pair_id}",
            "created_by": "pytest.handler",
        },
    )
    assert created.status_code == 201, created.text
    names = list(files or PAIRS[pair_id])
    if order == "invoice_first":
        names.reverse()
    for filename in names:
        uploaded = client.post(
            f"/api/v1/claims/{reference}/documents",
            files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
            data={"role": "current"},
        )
        assert uploaded.status_code == 200, uploaded.text
        processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
        assert processed.status_code == 200, processed.text
    return reference


def _session(client: TestClient) -> Session:
    return Session(client.engine, expire_on_commit=False)


def _only_assessment(session: Session) -> EngineerAssessment:
    return session.scalars(select(EngineerAssessment)).one()


def _only_invoice(session: Session) -> Invoice:
    return session.scalars(select(Invoice)).one()


def _add_assessment(
    session: Session,
    invoice: Invoice,
    name: str,
    *,
    created_at: datetime,
    paired_document_id: str | None = None,
    **fields,
) -> EngineerAssessment:
    """A synthetic engineer report in the invoice's case and intake group."""

    document = Document(
        case_id=invoice.case_id,
        document_role=DocumentRole.CURRENT,
        original_filename=name,
        storage_path=f"/tmp/{name}",
        sha256=name.ljust(64, "0")[:64],
        mime_type="application/pdf",
        file_size=100,
        upload_status=UploadStatus.READY,
        metadata_json={
            "intake_group": (invoice.document.metadata_json or {}).get("intake_group"),
            "paired_document_id": paired_document_id,
        },
    )
    session.add(document)
    session.flush()
    assessment = EngineerAssessment(
        case_id=invoice.case_id,
        document_id=document.id,
        created_at=created_at,
        **fields,
    )
    session.add(assessment)
    session.flush()
    return assessment


@pytest.mark.parametrize(
    ("pair_id", "expected_reasons", "expected_verdicts", "expected_confidence"),
    [
        (
            1,
            ["registration exact match", "claim reference exact match"],
            [
                "registration exact match",
                "claim reference exact match",
                # "PH" is printed on the assessment only, so the key is not
                # comparable -- absence is never a conflict, and it is not a
                # reason the pair is linked either.
                "policy number not printed on the invoice",
            ],
            2 / 3,
        ),
        (
            2,
            [
                "registration exact match",
                "claim reference exact match",
                "policy number exact match",
            ],
            [
                "registration exact match",
                "claim reference exact match",
                "policy number exact match",
            ],
            1.0,
        ),
        (
            7,
            ["registration exact match", "claim reference exact match"],
            [
                "registration exact match",
                "claim reference exact match",
                "policy number not printed on the invoice",
            ],
            2 / 3,
        ),
    ],
)
def test_client_pairs_link_on_their_printed_identities(
    pairing_client,
    pair_id: int,
    expected_reasons: list[str],
    expected_verdicts: list[str],
    expected_confidence: float,
) -> None:
    _process_pair(pairing_client, pair_id)

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        # pair_reasons_json justifies the link and nothing else; the full
        # per-key verdicts travel on the payload.
        assert assessment.pair_reasons_json == expected_reasons
        assert assessment.pair_confidence == pytest.approx(expected_confidence)
        assert not any("conflict" in reason for reason in assessment.pair_reasons_json)
        payload = engineer_assessment_payload(assessment, session)
        assert payload["pair_key_verdicts"] == expected_verdicts


def test_neither_the_invoice_number_nor_the_assessment_reference_is_a_key(
    pairing_client,
) -> None:
    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        document = session.get(Document, invoice.document_id)
        # The reference is captured for display and matches nothing on the report.
        assert document.metadata_json["assessment_reference"] == "BOY1537"
        reasons = " ".join(_only_assessment(session).pair_reasons_json)
        assert "BOY1537" not in reasons
        assert invoice.invoice_number not in reasons


def test_a_claim_conflict_rejects_a_pair_that_shares_an_invoice_number(
    pairing_client,
) -> None:
    """Format 1's assessment must not attach to format 7's invoice.

    Both invoices print "343653726836/1~3538". Only the claim reference (and
    here the registration) tells the two claims apart, and a conflict on a key
    printed by both documents is fatal however the other keys read.
    """

    _process_pair(
        pairing_client,
        17,
        files=("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        assert invoice.invoice_number == "343653726836/1~3538"
        assert assessment.claim_reference == "245338996/1"
        assert invoice.claim_reference == "426953180/3"
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        # Nothing was filled onto an invoice belonging to another claim.
        assert invoice.policy_number is None
        assert (session.get(Document, invoice.document_id).metadata_json or {}).get(
            "field_sources"
        ) in (None, {})


def test_an_unpaired_assessment_reports_no_confidence_and_no_positive_reasons(
    pairing_client,
) -> None:
    """An unlinked report says what blocked it, never what nearly matched.

    The review screen renders ``pair_reasons`` as "is paired to this invoice
    using <reasons>", so a rejected candidate's positive verdicts must not
    survive there, and the confidence of a link that does not exist is zero.
    """

    _process_pair(
        pairing_client,
        17,
        files=("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        assert assessment.pair_status == "unpaired"
        assert assessment.pair_confidence == 0.0
        assert not any("exact match" in reason for reason in assessment.pair_reasons_json)
        assert all("conflict" in reason for reason in assessment.pair_reasons_json)
        payload = engineer_assessment_payload(assessment, session)
        assert payload["pair_key_verdicts"] == []
        assert payload["pair_confidence"] == 0.0


def test_a_claim_conflict_is_fatal_even_when_the_registration_matches(
    pairing_client,
) -> None:
    """The claim reference alone rejects the pair; the other keys cannot rescue it."""

    _process_pair(
        pairing_client,
        18,
        files=("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        invoice.vehicle.registration = assessment.registration
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert any("claim reference conflict" in reason for reason in assessment.pair_reasons_json)


def test_a_claim_and_policy_match_pairs_without_any_registration(
    pairing_client,
) -> None:
    """Eligibility is symmetric across the two strong keys.

    An invoice that prints no registration but does print the claim reference
    and the policy number identifies its claim at least as well as a
    registration does, so demanding a registration match refused it for no
    reason an adjuster would recognise.
    """

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        invoice.vehicle.registration = None
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert assessment.pair_reasons_json == [
            "claim reference exact match",
            "policy number exact match",
        ]
        assert assessment.pair_confidence == pytest.approx(2 / 3)
        # The registration the invoice never printed is then gap-filled.
        assert invoice.vehicle.registration == assessment.registration


def test_a_registration_match_pairs_when_only_the_invoice_prints_the_claim(
    pairing_client,
) -> None:
    """A key printed on one side only is an absence, never a disagreement."""

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        assessment.claim_reference = None
        assessment.policy_number = None
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert invoice.claim_reference == "123456/1"
        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert assessment.pair_reasons_json == ["registration exact match"]
        assert assessment.pair_confidence == pytest.approx(1 / 3)


@pytest.mark.parametrize("order", ["oldest_first", "oldest_last"])
def test_two_claims_on_one_registration_leave_the_invoice_unclaimed(
    pairing_client, order: str
) -> None:
    """Neither report may write its claim onto an invoice that printed none.

    Both reports match this invoice on the registration alone, so whichever
    the database happened to return first used to pair, gap-fill its own claim
    reference onto the invoice, and leave the other rejected on a "conflict"
    with a value the invoice never printed.
    """

    _process_pair(pairing_client, 7, files=("DL_Repair_Invoice_format_7.docx",))

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        registration = invoice.vehicle.registration
        invoice.claim_reference = None
        session.flush()
        # created_at follows the claim, not the insertion order, so the two
        # orderings are the same data arriving two ways.
        specifications = [
            ("first-report.pdf", "111111/1", datetime(2026, 1, 1, tzinfo=UTC)),
            ("second-report.pdf", "222222/2", datetime(2026, 1, 2, tzinfo=UTC)),
        ]
        for name, claim, created_at in (
            specifications if order == "oldest_first" else list(reversed(specifications))
        ):
            _add_assessment(
                session,
                invoice,
                name,
                created_at=created_at,
                registration=registration,
                claim_reference=claim,
            )

        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assessments = session.scalars(select(EngineerAssessment)).all()
        assert len(assessments) == 2
        assert {assessment.pair_status for assessment in assessments} == {"unpaired"}
        assert all(assessment.paired_invoice_id is None for assessment in assessments)
        assert all(assessment.pair_confidence == 0.0 for assessment in assessments)
        assert all(
            "manual linkage required" in assessment.pair_reasons_json[0]
            for assessment in assessments
        )
        # Neither claim reached the invoice, and nothing was gap-filled.
        assert invoice.claim_reference is None
        assert (session.get(Document, invoice.document_id).metadata_json or {}).get(
            "field_sources"
        ) in (None, {})


def test_one_report_on_that_registration_still_pairs(pairing_client) -> None:
    """The counterpart to the two-claim case: one claimant is not ambiguous.

    Documented residual risk -- this invoice prints no claim reference, so the
    link rests on the registration alone and a second claim on the same
    vehicle would be indistinguishable. It is the shape of the five
    ``sample-data/engineer-invoice-pairs`` fixtures, so the rule stays.
    """

    _process_pair(pairing_client, 7, files=("DL_Repair_Invoice_format_7.docx",))

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        invoice.claim_reference = None
        session.flush()
        assessment = _add_assessment(
            session,
            invoice,
            "only-report.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            registration=invoice.vehicle.registration,
            claim_reference="111111/1",
        )
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert assessment.pair_reasons_json == ["registration exact match"]
        assert invoice.claim_reference == "111111/1"


@pytest.mark.parametrize("order", ["oldest_first", "oldest_last"])
def test_a_duplicate_report_is_refused_and_the_first_copy_keeps_the_link(
    pairing_client, order: str
) -> None:
    """Two reports of the same identity: the older keeps the link, the newer waits."""

    _process_pair(pairing_client, 7, files=("DL_Repair_Invoice_format_7.docx",))

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        identity = {
            "registration": invoice.vehicle.registration,
            "claim_reference": invoice.claim_reference,
        }
        specifications = [
            ("older-report.pdf", datetime(2026, 1, 1, tzinfo=UTC)),
            ("newer-report.pdf", datetime(2026, 1, 2, tzinfo=UTC)),
        ]
        for name, created_at in (
            specifications if order == "oldest_first" else list(reversed(specifications))
        ):
            _add_assessment(session, invoice, name, created_at=created_at, **identity)

        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        by_name = {
            session.get(Document, assessment.document_id).original_filename: assessment
            for assessment in session.scalars(select(EngineerAssessment)).all()
        }
        assert by_name["older-report.pdf"].pair_status == "paired"
        assert by_name["older-report.pdf"].paired_invoice_id == invoice.id
        assert by_name["newer-report.pdf"].pair_status == "unpaired"
        assert by_name["newer-report.pdf"].paired_invoice_id is None
        assert by_name["newer-report.pdf"].pair_confidence == 0.0
        assert (
            "manual linkage required" in by_name["newer-report.pdf"].pair_reasons_json[0]
        )


def test_an_explicit_upload_link_reports_only_the_keys_that_agree(
    pairing_client,
) -> None:
    """"Uploaded together" is a reason for the link, not evidence of identity."""

    _process_pair(pairing_client, 7, files=("DL_Repair_Invoice_format_7.docx",))

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _add_assessment(
            session,
            invoice,
            "uploaded-together.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            paired_document_id=invoice.document_id,
            vehicle_make="HYUNDAI",
        )
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        # No pairing key agrees, so the confidence is 0/3 and the upload
        # association says so in words instead of inflating the number.
        assert assessment.pair_confidence == 0.0
        assert assessment.pair_reasons_json == ["Uploaded together for this invoice"]


@pytest.mark.parametrize("order", UPLOAD_ORDERS)
def test_invoice_seven_takes_its_vehicle_from_the_assessment_without_manual_review(
    pairing_client, order: str
) -> None:
    reference = _process_pair(pairing_client, 7, order=order)

    documents = pairing_client.get(f"/api/v1/claims/{reference}/documents")
    assert documents.status_code == 200, documents.text
    invoice_document = next(
        entry
        for entry in documents.json()
        if entry["filename"] == "DL_Repair_Invoice_format_7.docx"
    )
    # A missing make/model is filled from the assessment, not escalated.
    assert invoice_document["manual_review"] is False
    assert invoice_document["manual_review_reason"] is None

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        # The invoice itself printed neither.
        header = invoice.extraction_payload_json["header"]
        assert header["vehicle_make"] is None
        assert header["vehicle_model"] is None

        assert invoice.vehicle.make == "HYUNDAI"
        assert invoice.vehicle.model == "140 SE Nav"
        assert invoice.policy_number == "PL-739284"

        sources = session.get(Document, invoice.document_id).metadata_json["field_sources"]
        # The upload order cannot change what was filled or where from.
        assert sorted(sources) == ["make", "mileage", "model", "policy_number", "vin"]
        for field, value in (
            ("make", "HYUNDAI"),
            ("model", "140 SE Nav"),
            ("policy_number", "PL-739284"),
        ):
            assert sources[field] == {
                "document_id": assessment.document_id,
                "label": "Filled from engineer assessment",
                "value": value,
            }
        # claim_reference was printed on the invoice, so it was never filled.
        assert "claim_reference" not in sources


@pytest.mark.parametrize("order", UPLOAD_ORDERS)
def test_the_gap_fill_sweep_is_idempotent_and_keeps_handler_corrections(
    pairing_client, order: str
) -> None:
    _process_pair(pairing_client, 7, order=order)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        case_id = invoice.case_id
        run_case_gap_fill(session, case_id)
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()

        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        sources = session.get(Document, invoice.document_id).metadata_json["field_sources"]
        assert assessment.pair_status == "paired"
        assert invoice.vehicle.make == "HYUNDAI"
        assert invoice.policy_number == "PL-739284"
        assert sorted(sources) == ["make", "mileage", "model", "policy_number", "vin"]

        # A handler correction outranks the assessment and is never reverted.
        invoice.vehicle.make = "HYUNDAI (corrected)"
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()
        invoice = _only_invoice(session)
        sources = session.get(Document, invoice.document_id).metadata_json["field_sources"]
        assert invoice.vehicle.make == "HYUNDAI (corrected)"
        assert "make" not in sources


def test_format_one_totals_resolve_to_their_assessment_sections(pairing_client) -> None:
    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        breakdowns = {
            entry["line_item_type"]: entry
            for entry in section_breakdown_for_invoice(session, invoice)
        }
        assert sorted(breakdowns) == ["labour", "paint_materials"]

        labour = breakdowns["labour"]
        assert Decimal(labour["invoice_total"]) == Decimal("2509.20")
        assert Decimal(labour["assessment_total"]) == Decimal("2509.20")
        assert labour["matches"] is True
        assert Decimal(labour["difference"]) == Decimal("0.00")
        assert labour["difference_convention"] == "invoice_total - assessment_total"
        # One invoice "Total Labour" pays for both work-unit sections.
        assert labour["breakdown_available"] is True
        assert len(labour["rows"]) == 41
        # The section total agrees with the invoice, but the report's own rows
        # price to less than the section it prints them under. Reporting
        # rows_total beside assessment_total is the only way that shows.
        assert Decimal(labour["rows_total"]) == Decimal("1410.60")
        categories = [row["category"] for row in labour["rows"]]
        assert categories.count("labour") == 25
        assert categories.count("paint") == 16
        assert all(row["description"] for row in labour["rows"])
        assert any(row["work_units"] for row in labour["rows"])

        materials = breakdowns["paint_materials"]
        assert Decimal(materials["assessment_total"]) == Decimal("1029.57")
        assert materials["matches"] is True


def test_format_two_reports_its_labour_gap_without_blocking(pairing_client) -> None:
    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        breakdowns = {
            entry["line_item_type"]: entry
            for entry in section_breakdown_for_invoice(session, invoice)
        }
        assert sorted(breakdowns) == ["extras", "labour", "paint_materials", "parts"]

        labour = breakdowns["labour"]
        # This assessment prints panel labour only, so the invoice bills more
        # than the report accounts for. It is reported, never enforced.
        assert Decimal(labour["invoice_total"]) == Decimal("2008.00")
        assert Decimal(labour["assessment_total"]) == Decimal("1112.00")
        assert labour["matches"] is False
        assert Decimal(labour["difference"]) == Decimal("896.00")
        assert len(labour["rows"]) == 17
        assert labour["breakdown_available"] is True
        # The rows priced by the report, beside the section total they came
        # from: the labour the invoice bills for is in neither figure.
        assert Decimal(labour["rows_total"]) == Decimal("1112.00")

        for line_item_type in ("parts", "paint_materials", "extras"):
            entry = breakdowns[line_item_type]
            # Not captured is not the same answer as does not match.
            assert entry["assessment_total"] is None
            assert entry["matches"] is None
            assert entry["difference"] is None
            assert entry["rows"] == []
            assert entry["breakdown_available"] is False
            assert entry["rows_total"] is None


def test_an_unresolved_section_total_gets_no_breakdown_rows(pairing_client) -> None:
    """"unknown" is not a section: it must not collect the unknown operations."""

    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        total = next(line for line in invoice.line_items if line.is_section_total)
        total.line_item_type = "unknown"
        assessment.operations[0].category = "unknown"
        session.flush()

        entry = next(
            row
            for row in section_breakdown_for_invoice(session, invoice, assessment)
            if row["invoice_line_item_id"] == total.id
        )
        assert entry["line_item_type"] == "unknown"
        assert entry["rows"] == []
        assert entry["breakdown_available"] is False
        assert entry["rows_total"] is None


def test_the_breakdown_uses_the_assessment_the_caller_holds(pairing_client) -> None:
    """A second row pointing at the invoice must not displace the caller's."""

    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        decoy = _add_assessment(
            session,
            invoice,
            "decoy-report.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            labour_net="1.00",
        )
        decoy.paired_invoice_id = invoice.id
        session.flush()

        labour = next(
            entry
            for entry in section_breakdown_for_invoice(session, invoice, assessment)
            if entry["line_item_type"] == "labour"
        )
        assert labour["assessment_id"] == assessment.id
        assert Decimal(labour["assessment_total"]) == Decimal("2509.20")
        assert len(labour["rows"]) == 41


def test_the_breakdown_reaches_the_assessment_payload(pairing_client) -> None:
    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        payload = engineer_assessment_payload(_only_assessment(session), session)
        types = {entry["line_item_type"] for entry in payload["section_breakdowns"]}
        assert types == {"labour", "paint_materials"}
        assert payload["field_sources"]["policy_number"]["value"] == "PH"
        assert payload["pair_key_verdicts"] == [
            "registration exact match",
            "claim reference exact match",
            "policy number not printed on the invoice",
        ]
