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
    _comparable_identifier,
    _compare_pair_keys,
    _printed_identity,
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
    3: ("DL_Auda_format_3_assessment.docx", "DL_Invoice_3_request_for_payment.docx"),
    4: ("DL_Auda_format_4_assessment.docx", "DL_Invoice_4_request_for_payment.docx"),
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


@pytest.mark.parametrize(
    "value",
    [
        "PH",
        "N/A",
        "n/a",
        "NA",
        "None",
        "NIL",
        "TBC",
        "TBA",
        "TBD",
        "Unknown",
        "N/K",
        "X",
        "XX",
        "XXX",
        "XXXX",
        "0",
        "00",
        "000",
        "0000",
        "AB1",
        "  ",
        None,
    ],
)
def test_a_placeholder_or_short_token_is_not_a_comparable_identifier(
    value: str | None,
) -> None:
    """A token that cannot single out one claim is treated as not printed.

    Absence is neutral under "match what is there", so demoting is the safe
    direction: the worst a false demotion can do is leave a pair unmade. The
    unsafe direction is believing the token -- two unrelated documents both
    printing "PH" would otherwise agree on a key at confidence 1.0.
    """

    comparable, _ = _comparable_identifier(value)
    assert comparable is None


@pytest.mark.parametrize(
    "value", ["AB12 XYZ", "245338996/1", "PL-739284", "103466899", "1234"]
)
def test_a_real_identifier_clears_the_floor(value: str) -> None:
    comparable, printed = _comparable_identifier(value)
    assert comparable is not None
    assert comparable == printed == normalise_identifier(value)


def test_a_demoted_token_is_still_reported_as_printed() -> None:
    """"Printed nothing" and "printed something meaningless" stay distinct."""

    assert _comparable_identifier("PH") == (None, "PH")
    assert _comparable_identifier(None) == (None, None)


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


def _verdicts(payload: dict) -> dict[str, dict]:
    return {entry["key"]: entry for entry in payload["pair_key_verdicts"]}


def _key_counts(assessment: EngineerAssessment, invoice: Invoice) -> tuple[int, int]:
    """``(matched, compared)`` -- the two numbers ``pair_confidence`` divides.

    Asserting on the counts is the point: every ratio the corpus produces is
    1.0, so ``confidence == approx(1.0)`` passes for any denominator and would
    not notice a regression to matched-over-three.
    """

    verdicts = _compare_pair_keys(assessment, _printed_identity(invoice))
    return (
        sum(1 for verdict in verdicts if verdict.state == "matched"),
        sum(1 for verdict in verdicts if verdict.compared),
    )


#: ``key -> (state, absent_on, placeholder_on)`` for each client pair.
CLIENT_PAIR_VERDICTS: dict[int, dict[str, tuple[str, str | None, str | None]]] = {
    1: {
        "registration": ("matched", None, None),
        "claim_reference": ("matched", None, None),
        # "PH" is a placeholder the client called out, and the invoice prints
        # no policy number at all: two independent reasons the key cannot be
        # compared, both recorded. Neither is a conflict, neither justifies
        # the link, and neither dilutes the confidence.
        "policy_number": ("placeholder", "invoice", "assessment"),
    },
    2: {
        "registration": ("matched", None, None),
        "claim_reference": ("matched", None, None),
        "policy_number": ("matched", None, None),
    },
    7: {
        "registration": ("matched", None, None),
        "claim_reference": ("matched", None, None),
        # The report prints "PL-739284"; the invoice prints no policy number,
        # so the key is absent rather than meaningless.
        "policy_number": ("not_compared", "invoice", None),
    },
}


@pytest.mark.parametrize(
    ("pair_id", "expected_reasons", "expected_counts"),
    [
        (
            1,
            ["registration exact match", "claim reference exact match"],
            # Two keys comparable, two agree -- not "two out of three".
            (2, 2),
        ),
        (
            2,
            [
                "registration exact match",
                "claim reference exact match",
                "policy number exact match",
            ],
            (3, 3),
        ),
        (
            7,
            ["registration exact match", "claim reference exact match"],
            (2, 2),
        ),
    ],
)
def test_client_pairs_link_on_their_printed_identities(
    pairing_client,
    pair_id: int,
    expected_reasons: list[str],
    expected_counts: tuple[int, int],
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
        assert not any("conflict" in reason for reason in assessment.pair_reasons_json)
        # Two keys comparable is not a weak pair; one key would be.
        assert not any("weak pair" in reason for reason in assessment.pair_reasons_json)

        # The counts, not the ratio: every ratio here is 1.0, so asserting the
        # ratio alone would pass against a matched-over-three regression.
        matched, compared = _key_counts(assessment, invoice)
        assert (matched, compared) == expected_counts
        assert assessment.pair_confidence == pytest.approx(matched / compared)

        expected_verdicts = CLIENT_PAIR_VERDICTS[pair_id]
        verdicts = _verdicts(engineer_assessment_payload(assessment, session))
        assert {
            key: (entry["state"], entry["absent_on"], entry["placeholder_on"])
            for key, entry in verdicts.items()
        } == expected_verdicts
        for key, (state, _, _) in expected_verdicts.items():
            assert verdicts[key]["compared"] is (state == "matched")
            assert verdicts[key]["text"]


def test_the_policy_number_absent_on_the_invoice_is_skipped_not_scored(
    pairing_client,
) -> None:
    """Pair 1 is the client's own case: policy "PH" is printed on one side.

    Two things at once. A key the repairer never printed is not evidence of
    disagreement and must not cost the pair a third of its confidence, which
    is all that ever stopped this pair reading as certain. And "PH" is a
    placeholder, so it could not have been compared even if the invoice had
    printed one -- the verdict says so instead of implying a third match was
    only ever one printed box away.
    """

    _process_pair(pairing_client, 1)

    with _session(pairing_client) as session:
        assessment = _only_assessment(session)
        invoice = _only_invoice(session)
        assert assessment.policy_number == "PH"
        assert _printed_identity(invoice)["policy_number"] is None
        assert _key_counts(assessment, invoice) == (2, 2)
        assert assessment.pair_confidence == pytest.approx(2 / 2)
        policy = _verdicts(engineer_assessment_payload(assessment, session))[
            "policy_number"
        ]
        assert policy["state"] == "placeholder"
        assert policy["compared"] is False
        assert policy["placeholder_on"] == "assessment"
        assert policy["absent_on"] == "invoice"
        assert policy["assessment_value"] == "PH"
        assert policy["invoice_value"] is None
        assert policy["text"] == "policy number is a placeholder on the assessment (PH)"


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
        # Two keys comparable, both agreeing: the registration the invoice
        # never printed is not counted against the pair.
        assert assessment.pair_confidence == pytest.approx(2 / 2)
        # The registration the invoice never printed is then gap-filled.
        assert invoice.vehicle.registration == assessment.registration


def test_a_registration_match_pairs_when_only_the_invoice_prints_the_claim(
    pairing_client,
) -> None:
    """A key printed on one side only is an absence, never a disagreement.

    One comparable key is enough to link, and the link says out loud that it
    rests on one key: this is the weakest pair the rule can produce and a
    handler reading "paired ... using registration exact match" alone would
    have no way to tell it apart from a three-key agreement.
    """

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
        # The sentence reuses each skipped key's own verdict, so it never
        # claims a key is missing from a document that printed it: the claim
        # reference below *is* printed on the invoice.
        assert assessment.pair_reasons_json == [
            "registration exact match",
            "weak pair: only the registration was comparable; "
            "claim reference not printed on the assessment; "
            "policy number not printed on the assessment",
        ]
        # One key comparable, one agreeing: certain about the only evidence
        # there was, which is what the "weak pair" reason is there to qualify.
        assert assessment.pair_confidence == pytest.approx(1 / 1)
        verdicts = _verdicts(engineer_assessment_payload(assessment, session))
        assert verdicts["claim_reference"]["state"] == "not_compared"
        assert verdicts["claim_reference"]["absent_on"] == "assessment"
        assert verdicts["claim_reference"]["invoice_value"] == "123456/1"
        assert verdicts["policy_number"]["absent_on"] == "assessment"


def test_a_policy_number_alone_is_enough_when_nothing_else_is_printed(
    pairing_client,
) -> None:
    """"Just match what is there" includes the case where "there" is one key.

    The old rule privileged the registration and the claim reference, so an
    invoice printing only a policy number could not pair however exactly that
    policy number agreed.
    """

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        invoice.vehicle.registration = None
        invoice.claim_reference = None
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert assessment.pair_confidence == pytest.approx(1 / 1)
        assert assessment.pair_reasons_json == [
            "policy number exact match",
            "weak pair: only the policy number was comparable; "
            "registration not printed on the invoice; "
            "claim reference not printed on the invoice",
        ]


def test_a_conflict_on_the_only_weak_key_still_refuses_the_pair(
    pairing_client,
) -> None:
    """Every compared key must agree -- the loosened rule loosened nothing here."""

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        invoice.policy_number = "103466899-OTHER"
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        # Registration and claim reference both agree; the third compared key
        # disagrees, and a disagreement is fatal however the others read.
        assert assessment.registration == invoice.vehicle.registration
        assert assessment.claim_reference == invoice.claim_reference
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert assessment.pair_confidence == 0.0
        assert assessment.pair_reasons_json == [
            "policy number conflict: assessment 103466899 versus invoice 103466899-OTHER"
        ]


def test_confidence_is_matched_over_compared_not_over_three(pairing_client) -> None:
    """The arithmetic, in one place, across every shape the corpus produces.

    Every stage below divides out to 1.0, so the *ratio* proves nothing: only
    the denominator moving 3 -> 2 -> 1 with the numerator distinguishes
    matched-over-compared from matched-over-three.
    """

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        case_id = invoice.case_id

        # 3 of 3 comparable.
        assert _key_counts(assessment, invoice) == (3, 3)
        assert assessment.pair_confidence == pytest.approx(3 / 3)

        # 2 of 2 comparable: the client's pairs 1 and 7, where the repairer
        # printed no policy number at all. Matched-over-three would read 2/3.
        invoice.policy_number = None
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()
        assert _key_counts(assessment, invoice) == (2, 2)
        assert assessment.pair_confidence == pytest.approx(2 / 2)
        assert len(assessment.pair_reasons_json) == 2

        # 1 of 1 comparable, and labelled weak. The policy number the previous
        # pass gap-filled is reverted by the sweep itself, so it stays an
        # absence rather than becoming the assessment's own evidence.
        invoice.claim_reference = None
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()
        assert _key_counts(assessment, invoice) == (1, 1)
        assert assessment.pair_confidence == pytest.approx(1 / 1)
        assert any("weak pair" in reason for reason in assessment.pair_reasons_json)

        # Nothing comparable: no link, and no division by zero.
        invoice.vehicle.registration = None
        session.flush()
        run_case_gap_fill(session, case_id)
        session.flush()
        assert _key_counts(assessment, invoice) == (0, 0)
        assert assessment.pair_status == "unpaired"
        assert assessment.pair_confidence == 0.0


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
        # Two *different* reports fitting one invoice equally well is not
        # "the same identity uploaded twice", and the reason says which.
        assert all(
            assessment.pair_reasons_json
            == ["Two assessments agree with this invoice equally well; "
                "manual linkage required"]
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
        # The one comparable key carries the link, and says so.
        assert assessment.pair_reasons_json[0] == "registration exact match"
        assert assessment.pair_reasons_json[1].startswith(
            "weak pair: only the registration was comparable"
        )
        assert invoice.claim_reference == "111111/1"


def _invoices_by_registration(session: Session) -> dict[str, Invoice]:
    return {
        invoice.vehicle.registration: invoice
        for invoice in session.scalars(select(Invoice)).all()
    }


def test_the_candidate_agreeing_on_more_keys_wins(pairing_client) -> None:
    """Two comparable keys beat one; the weaker candidate is not a rival.

    Every eligible candidate now agrees on every key it could compare, so all
    of them score 1.0 and confidence alone can no longer rank them. Without
    ranking on the *number* of agreeing keys, a registration-only lookalike
    would tie with an exact registration-and-claim match and the contention
    rule would refuse both.
    """

    _process_pair(
        pairing_client,
        19,
        files=("DL_Repair_Invoice_format_1.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        invoices = _invoices_by_registration(session)
        right, lookalike = invoices["AB12XYZ"], invoices["JK21MNO"]
        # The second invoice is the same vehicle with no claim printed: one
        # comparable key, and it agrees.
        lookalike.vehicle.registration = right.vehicle.registration
        lookalike.claim_reference = None
        session.flush()
        assessment = _add_assessment(
            session,
            right,
            "two-key-report.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            registration="AB12XYZ",
            claim_reference=right.claim_reference,
        )
        run_case_gap_fill(session, right.case_id)
        session.flush()

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == right.id
        assert assessment.pair_reasons_json == [
            "registration exact match",
            "claim reference exact match",
        ]
        assert assessment.pair_confidence == pytest.approx(2 / 2)
        # Nothing was written onto the invoice that only looked similar.
        assert lookalike.claim_reference is None


def test_two_equally_comparable_invoices_leave_the_assessment_unpaired(
    pairing_client,
) -> None:
    """Equally good evidence is not evidence: the engine refuses to guess."""

    _process_pair(
        pairing_client,
        20,
        files=("DL_Repair_Invoice_format_1.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        invoices = _invoices_by_registration(session)
        first, second = invoices["AB12XYZ"], invoices["JK21MNO"]
        case_id = first.case_id
        second.vehicle.registration = first.vehicle.registration
        for invoice in (first, second):
            invoice.claim_reference = None
        session.flush()
        assessment = _add_assessment(
            session,
            first,
            "ambiguous-report.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            registration="AB12XYZ",
            claim_reference="245338996/1",
        )
        run_case_gap_fill(session, case_id)
        session.flush()

        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert assessment.pair_confidence == 0.0
        assert "Multiple invoices" in assessment.pair_reasons_json[0]
        # Neither invoice took the claim reference of a pair that was refused.
        assert first.claim_reference is None
        assert second.claim_reference is None


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
        assert by_name["newer-report.pdf"].pair_reasons_json == [
            "The same assessment identity was uploaded more than once; the "
            "earliest copy keeps the link and manual linkage is required for "
            "this one"
        ]


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


def test_format_three_resolves_every_section_without_fabricating_labour(
    pairing_client,
) -> None:
    """The defect this pair was built to catch, end to end.

    Client format 3 prints a bordered ``Material cost paint`` table of money
    straight after the PAINT WORK work-unit schedule. Until that heading was
    recognised its rows stayed inside PAINT WORK, were read as work units and
    were priced at £83.28/hr, so the labour breakdown rendered £17,597.07 of
    fabricated labour underneath an invoice line of £1,598.97.
    """

    _process_pair(pairing_client, 3)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        breakdowns = {
            entry["line_item_type"]: entry
            for entry in section_breakdown_for_invoice(session, invoice)
        }
        assert sorted(breakdowns) == ["extras", "labour", "paint_materials", "parts"]

        labour = breakdowns["labour"]
        assert Decimal(labour["invoice_total"]) == Decimal("1598.97")
        assert Decimal(labour["assessment_total"]) == Decimal("1598.97")
        assert labour["matches"] is True
        # 14 labour rows (89 WU) and 7 paint rows (103 WU) at £83.28/hr, and
        # nothing else. The penny above the printed £1,598.97 is the report's
        # own per-row rounding (six 0.2-hour rows at £16.656 each), which is
        # exactly what publishing rows_total beside assessment_total shows.
        assert len(labour["rows"]) == 21
        assert Decimal(labour["rows_total"]) == Decimal("1598.98")
        assert all(row["category"] in {"labour", "paint"} for row in labour["rows"])

        materials = breakdowns["paint_materials"]
        assert Decimal(materials["invoice_total"]) == Decimal("384.18")
        assert Decimal(materials["assessment_total"]) == Decimal("384.18")
        assert materials["matches"] is True
        assert materials["breakdown_available"] is True
        assert [row["description"] for row in materials["rows"]] == [
            "Total paint Cost",
            "Sundry Paint Material",
            "Pre-Painting sundry materials",
        ]
        # The three components sum to the table's own subtotal; the printed
        # answer is half of it and is shown as printed, not corrected.
        assert Decimal(materials["rows_total"]) == Decimal("768.37")

        parts = breakdowns["parts"]
        assert Decimal(parts["assessment_total"]) == Decimal("13.56")
        assert parts["matches"] is True
        assert [row["description"] for row in parts["rows"]] == ["NS door hinge bolts"]

        extras = breakdowns["extras"]
        # The invoice's "Additional charges" line is Total Additional Cost,
        # never Total Extras -- adding both would count £4.00 twice.
        assert Decimal(extras["invoice_total"]) == Decimal("4.00")
        assert Decimal(extras["assessment_total"]) == Decimal("4.00")
        assert extras["matches"] is True
        assert [row["description"] for row in extras["rows"]] == [
            "ANTI CORROSION PROTE",
            "Corrosion Protection Materials External",
        ]


def test_format_four_keeps_its_headerless_schedule_page_in_the_assessment(
    pairing_client,
) -> None:
    """Format 4's third page prints no assessment header of its own.

    It opens mid-PAINT WORK and runs through Material cost paint, PARTS and
    EXTRAS, so it trips the amounts-only invoice heuristic. Left an invoice it
    took a third of the report's schedule out of the assessment: the paint
    materials and parts breakdowns came back empty and a numberless phantom
    invoice appeared on the claim.
    """

    _process_pair(pairing_client, 4)

    with _session(pairing_client) as session:
        assert session.scalars(select(Invoice)).all() == [_only_invoice(session)]
        invoice = _only_invoice(session)
        breakdowns = {
            entry["line_item_type"]: entry
            for entry in section_breakdown_for_invoice(session, invoice)
        }
        assert sorted(breakdowns) == ["extras", "labour", "paint_materials", "parts"]

        materials = breakdowns["paint_materials"]
        assert Decimal(materials["assessment_total"]) == Decimal("1425.72")
        assert materials["matches"] is True
        assert len(materials["rows"]) == 3
        assert Decimal(materials["rows_total"]) == Decimal("1425.72")

        parts = breakdowns["parts"]
        assert Decimal(parts["assessment_total"]) == Decimal("1104.39")
        assert parts["matches"] is True
        # Eleven rows against a printed SUB TOTAL of 1005.39: the report is
        # £10.00 out with itself, and both figures are published.
        assert len(parts["rows"]) == 11
        assert Decimal(parts["rows_total"]) == Decimal("995.39")

        extras = breakdowns["extras"]
        assert Decimal(extras["invoice_total"]) == Decimal("1161.02")
        assert Decimal(extras["assessment_total"]) == Decimal("1161.02")
        assert extras["matches"] is True

        labour = breakdowns["labour"]
        assert Decimal(labour["assessment_total"]) == Decimal("3331.20")
        assert labour["matches"] is True
        # 43 labour rows and 14 paint rows -- the money table is no longer
        # among them. The rows price to more than the section total because
        # this report's labour rows sum to 249 WU against a printed 244.
        assert len(labour["rows"]) == 57
        assert Decimal(labour["rows_total"]) == Decimal("3372.86")


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
        # One entry per pairing key, in key order, each carrying the state the
        # UI renders as well as the sentence it prints.
        assert [entry["text"] for entry in payload["pair_key_verdicts"]] == [
            "registration exact match",
            "claim reference exact match",
            "policy number is a placeholder on the assessment (PH)",
        ]
        assert [entry["state"] for entry in payload["pair_key_verdicts"]] == [
            "matched",
            "matched",
            "placeholder",
        ]


def test_a_placeholder_policy_number_printed_on_both_documents_never_pairs(
    pairing_client,
) -> None:
    """Scenario (a): "PH" on both documents is agreement about nothing.

    Format 1's assessment prints the policy number "PH" -- the placeholder the
    client's own requirements call out. Set against an unrelated invoice that
    also prints "PH" and shares nothing else, the relaxed rule used to compare
    that one key, find it equal, and link the two at confidence 1.0.
    """

    _process_pair(
        pairing_client,
        21,
        files=("DL_Auda_format_1_assessment.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        assert assessment.policy_number == "PH"
        # Strip the invoice back to a document that shares nothing but "PH".
        invoice.vehicle.registration = None
        invoice.claim_reference = None
        invoice.policy_number = "PH"
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert _key_counts(assessment, invoice) == (0, 0)
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert assessment.pair_confidence == 0.0
        assert assessment.pair_reasons_json == [
            "No invoice shares a printed registration, claim reference or "
            "policy number with this assessment"
        ]
        policy = _compare_pair_keys(assessment, _printed_identity(invoice))[2]
        assert policy.state == "placeholder"
        assert policy.compared is False
        assert policy.placeholder_on == "both"
        assert policy.text == "policy number is a placeholder on both documents (PH)"
        # Nothing was written onto an invoice the report never identified.
        assert invoice.claim_reference is None
        assert (session.get(Document, invoice.document_id).metadata_json or {}).get(
            "field_sources"
        ) in (None, {})


def test_a_placeholder_never_makes_the_wrong_invoice_outrank_the_right_one(
    pairing_client,
) -> None:
    """Scenario (b): the quiet failure -- a wrong pair, with no warning.

    The report's policy number is "N/A". Invoice X is its real invoice and
    prints the registration only; invoice Y is a different claim on the same
    vehicle that also prints "N/A". Y used to agree on two keys to X's one,
    win outright, and -- because two keys agreed -- not even earn the "weak
    pair" note, after which the report's claim reference, policy number and
    vehicle identity were gap-filled onto somebody else's invoice.

    With "N/A" demoted, both invoices agree on the registration alone and the
    engine refuses to guess. No pair is the safe failure; the wrong pair was
    not.
    """

    _process_pair(
        pairing_client,
        22,
        files=("DL_Repair_Invoice_format_1.docx", "DL_Repair_Invoice_format_7.docx"),
    )

    with _session(pairing_client) as session:
        invoices = _invoices_by_registration(session)
        right, sibling = invoices["AB12XYZ"], invoices["JK21MNO"]
        right.claim_reference = None
        sibling.vehicle.registration = right.vehicle.registration
        sibling.claim_reference = None
        sibling.policy_number = "N/A"
        session.flush()
        assessment = _add_assessment(
            session,
            right,
            "placeholder-policy-report.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            registration="AB12XYZ",
            claim_reference="245338996/1",
            policy_number="N/A",
        )
        run_case_gap_fill(session, right.case_id)
        session.flush()

        # The placeholder buys the sibling nothing: one comparable key each.
        assert _key_counts(assessment, right) == (1, 1)
        assert _key_counts(assessment, sibling) == (1, 1)
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert assessment.pair_confidence == 0.0
        assert "Multiple invoices" in assessment.pair_reasons_json[0]
        # Above all: nothing of this claim reached the other claim's invoice.
        assert sibling.claim_reference is None
        assert sibling.policy_number == "N/A"
        assert right.claim_reference is None
        for invoice in (right, sibling):
            assert (session.get(Document, invoice.document_id).metadata_json or {}).get(
                "field_sources"
            ) in (None, {})


def test_a_placeholder_on_one_side_is_not_a_conflict(pairing_client) -> None:
    """Demotion never blocks a pair either: it is an absence, not a mismatch."""

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        assessment = _only_assessment(session)
        assert invoice.policy_number == "103466899"
        assessment.policy_number = "N/A"
        session.flush()
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert assessment.pair_status == "paired"
        assert assessment.paired_invoice_id == invoice.id
        assert _key_counts(assessment, invoice) == (2, 2)
        assert assessment.pair_confidence == pytest.approx(2 / 2)
        assert assessment.pair_reasons_json == [
            "registration exact match",
            "claim reference exact match",
        ]
        policy = _compare_pair_keys(assessment, _printed_identity(invoice))[2]
        assert policy.state == "placeholder"
        assert policy.placeholder_on == "assessment"
        assert policy.absent_on is None
        assert policy.text == "policy number is a placeholder on the assessment (N/A)"


def test_the_strongest_claimant_keeps_the_link_and_the_weaker_one_is_refused(
    pairing_client,
) -> None:
    """A one-key lookalike must not destroy a three-of-three exact pair.

    Contention used to be resolved by refusing every claimant whose identities
    differed, however lopsided the evidence -- and to tell the handler the two
    assessments "share the same identifiers", when the lookalike shared none:
    it simply had none of its own. Ranking on agreeing keys keeps the pair the
    invoice's own report earned.
    """

    _process_pair(pairing_client, 2)

    with _session(pairing_client) as session:
        invoice = _only_invoice(session)
        correct = _only_assessment(session)
        # Older than the real report, so arrival order cannot be what decides.
        sibling = _add_assessment(
            session,
            invoice,
            "policy-only-sibling.pdf",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            policy_number=invoice.policy_number,
        )
        run_case_gap_fill(session, invoice.case_id)
        session.flush()

        assert correct.pair_status == "paired"
        assert correct.paired_invoice_id == invoice.id
        assert _key_counts(correct, invoice) == (3, 3)
        assert correct.pair_confidence == pytest.approx(3 / 3)
        assert correct.pair_reasons_json == [
            "registration exact match",
            "claim reference exact match",
            "policy number exact match",
        ]

        assert sibling.pair_status == "unpaired"
        assert sibling.paired_invoice_id is None
        assert sibling.pair_confidence == 0.0
        # The refusal says what is actually true of this claimant.
        assert sibling.pair_reasons_json == [
            "Another assessment agrees with this invoice on more printed "
            "identities; manual linkage required"
        ]
