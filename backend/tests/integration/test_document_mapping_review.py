"""The handler's mapping review: override, survival, gap-fill and approval.

The pairing rule refuses to guess -- two assessments that fit one invoice
equally well leave it unlinked, conflicting identities refuse the pair -- and
every one of those refusals ends in "manual linkage required".  Until now
nothing could perform that linkage, so the documents stayed stuck.  These
tests cover the five facts that make the escape hatch trustworthy:

* a handler can link an assessment the rule left unpaired;
* the link survives the next document upload, which re-decides every pairing
  in the case from scratch;
* re-pointing the link takes the gap-filled values back off the old invoice
  and puts them on the new one;
* approving records the approval *and* runs the case-wide sweep over the
  pairs that were approved;
* a handler's link is distinguishable from the rule's in the payload.

The invoices are the real client ``.docx`` documents, uploaded through the
real API exactly as ``tests/unit/test_engineer_assessment_pairing.py`` does.
The assessments are synthetic, because the interesting cases -- an assessment
no invoice matches, two assessments reaching for one invoice -- have no client
fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.database import get_db
from app.enums import DocumentRole, UploadStatus
from app.init_db import initialize_database
from app.main import app
from app.models import AuditEvent, Case, Document, EngineerAssessment, Invoice
from app.services.engineer_assessment import (
    MANUAL_CONTESTED_REASON,
    MANUAL_LINK_REASON,
    MANUAL_OUTRANKS_REASON,
    MANUAL_STALE_REASON,
    MANUAL_STATE_LINKED,
)

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: Two invoices from two different claims, so a handler re-pointing an
#: assessment from one to the other is a real change of claim, not a
#: relabelling of the same one.
INVOICE_A = "DL_Invoice_2_request_for_payment.docx"
INVOICE_B = "DL_Invoice_4_request_for_payment.docx"
INVOICE_C = "DL_Invoice_3_request_for_payment.docx"

REFERENCE = "MAPPING-REVIEW"
HANDLER = "pytest.handler"


@pytest.fixture
def mapping_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'mapping.db'}",
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


def _upload(client: TestClient, filename: str, reference: str = REFERENCE) -> str:
    uploaded = client.post(
        f"/api/v1/claims/{reference}/documents",
        files={"file": (filename, (FIXTURES / filename).read_bytes(), DOCX_MIME)},
        data={"role": "current"},
    )
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()["id"]
    processed = client.post(f"/api/v1/documents/{document_id}/process")
    assert processed.status_code == 200, processed.text
    return document_id


def _case_with_two_invoices(client: TestClient) -> str:
    created = client.post(
        "/api/v1/claims",
        json={
            "case_reference": REFERENCE,
            "claim_number": "2026/MAPPING/1",
            "created_by": HANDLER,
        },
    )
    assert created.status_code == 201, created.text
    _upload(client, INVOICE_A)
    _upload(client, INVOICE_B)
    return REFERENCE


def _add_orphan_assessment(
    session: Session,
    case_id: str,
    name: str = "orphan-report.pdf",
    *,
    created_at: datetime | None = None,
    **fields,
) -> EngineerAssessment:
    """An engineer report whose printed identities match no invoice in the case.

    This is the document the rule leaves stuck: no shared registration, claim
    reference or policy number, so nothing links it and nothing ever will
    without a person.
    """

    document = Document(
        case_id=case_id,
        document_role=DocumentRole.CURRENT,
        original_filename=name,
        storage_path=f"/tmp/{name}",
        sha256=name.ljust(64, "0")[:64],
        mime_type="application/pdf",
        file_size=100,
        upload_status=UploadStatus.READY,
        metadata_json={"intake_group": None},
    )
    session.add(document)
    session.flush()
    defaults = {
        "assessment_number": "ORPHAN-1",
        "claim_reference": "999888777/9",
        "policy_number": "ORPHANPOLICY9",
        "registration": "ZZ99ZZZ",
        "vin": "VINMANUALOVERRIDE1",
        "mileage": 54321,
    }
    assessment = EngineerAssessment(
        case_id=case_id,
        document_id=document.id,
        created_at=created_at or datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        **{**defaults, **fields},
    )
    session.add(assessment)
    session.flush()
    return assessment


def _invoices(session: Session) -> list[Invoice]:
    return list(
        session.scalars(select(Invoice).order_by(Invoice.created_at, Invoice.id))
        .unique()
        .all()
    )


def _override(
    client: TestClient,
    assessment_id: str,
    decision: str,
    *,
    invoice_id: str | None = None,
    reason: str | None = "Confirmed against the paperwork",
):
    body: dict[str, object] = {"actor": HANDLER, "decision": decision, "reason": reason}
    if invoice_id is not None:
        body["invoice_id"] = invoice_id
    return client.post(
        f"/api/v1/claims/{REFERENCE}/document-mapping/assessments/{assessment_id}",
        json=body,
    )


def _row(payload: dict, assessment_id: str) -> dict:
    return next(
        row for row in payload["assessments"] if row["assessment_id"] == assessment_id
    )


def _field_sources(session: Session, invoice_id: str) -> dict:
    invoice = session.get(Invoice, invoice_id)
    return (invoice.document.metadata_json or {}).get("field_sources", {})


def test_a_handler_links_an_assessment_the_rule_left_unpaired(mapping_client) -> None:
    """The escape hatch itself: "manual linkage required" becomes possible.

    The rule's own reason for leaving this report unpaired is that no invoice
    shares a printed identity with it. Nothing about that changes -- the
    handler is not being asked to supply evidence, they are supplying a
    decision -- so the link carries no confidence and says in its reasons that
    a person made it.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        assessment = _add_orphan_assessment(session, case.id)
        invoice_a = _invoices(session)[0]
        assessment_id, invoice_id = assessment.id, invoice_a.id
        session.commit()

    before = mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping")
    assert before.status_code == 200, before.text
    row = _row(before.json(), assessment_id)
    assert row["pair_status"] == "unpaired"
    assert row["paired_invoice_id"] is None
    assert row["manual_override"] is None

    response = _override(mapping_client, assessment_id, "link", invoice_id=invoice_id)
    assert response.status_code == 200, response.text
    row = _row(response.json(), assessment_id)
    assert row["pair_status"] == "paired"
    assert row["paired_invoice_id"] == invoice_id
    assert row["pair_reasons"] == [MANUAL_LINK_REASON]

    with _session(mapping_client) as session:
        assessment = session.get(EngineerAssessment, assessment_id)
        assert assessment.paired_invoice_id == invoice_id
        assert assessment.manual_pair_state == MANUAL_STATE_LINKED
        assert assessment.manual_pair_actor == HANDLER
        assert assessment.manual_pair_at is not None
        event_types = set(
            session.scalars(
                select(AuditEvent.event_type).where(
                    AuditEvent.entity_id == assessment_id
                )
            ).all()
        )
        assert "ASSESSMENT_MAPPING_LINK" in event_types


def test_a_manual_link_is_distinguishable_from_an_automatic_one(mapping_client) -> None:
    """A handler's link and the rule's must never read the same on a screen.

    Three things say so, and all three are on the payload: ``pair_source``,
    the ``manual_override`` block with the actor and the timestamp, and a
    ``pair_confidence`` of ``None`` -- confidence is the share of comparable
    printed identities that agree, which is a fact about the rule and not
    about a person's judgement.
    """

    _case_with_two_invoices(mapping_client)
    assessment_document = _upload(mapping_client, "DL_Auda_format_2_assessment.docx")

    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        automatic = session.scalar(
            select(EngineerAssessment).where(
                EngineerAssessment.document_id == assessment_document
            )
        )
        manual = _add_orphan_assessment(session, case.id)
        invoice_b = _invoices(session)[1]
        automatic_id, manual_id, invoice_b_id = automatic.id, manual.id, invoice_b.id
        assert automatic.pair_status == "paired"
        session.commit()

    assert _override(
        mapping_client, manual_id, "link", invoice_id=invoice_b_id
    ).status_code == 200

    payload = mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json()
    automatic_row = _row(payload, automatic_id)
    manual_row = _row(payload, manual_id)

    assert automatic_row["pair_source"] == "automatic"
    assert automatic_row["manual_override"] is None
    assert automatic_row["pair_confidence"] == pytest.approx(1.0)

    assert manual_row["pair_source"] == "manual"
    assert manual_row["pair_confidence"] is None
    override = manual_row["manual_override"]
    assert override["state"] == MANUAL_STATE_LINKED
    assert override["invoice_id"] == invoice_b_id
    assert override["actor"] == HANDLER
    assert override["at"] is not None
    assert override["applied"] is True

    # The same distinction reaches the two other payloads that carry a
    # pairing, so no screen has to guess from the reason text.
    assessments = mapping_client.get(
        f"/api/v1/claims/{REFERENCE}/engineer-assessments"
    ).json()
    by_id = {row["id"]: row for row in assessments}
    assert by_id[manual_id]["pair_source"] == "manual"
    assert by_id[automatic_id]["pair_source"] == "automatic"
    extracts = mapping_client.get(f"/api/v1/claims/{REFERENCE}/extracts").json()
    by_extract = {row["assessment_id"]: row for row in extracts["assessment_extracts"]}
    assert by_extract[manual_id]["pair_source"] == "manual"
    assert by_extract[manual_id]["manual_override"]["applied"] is True


def test_a_manual_link_survives_a_later_document_upload(mapping_client) -> None:
    """The sharpest correctness problem in the feature.

    ``pair_case_assessments`` reverts every fill and re-decides every link
    from scratch on every upload. A decision a person took must not be one of
    the things it throws away -- so the decision lives in its own columns and
    the pass is overruled by it, rather than the decision being written into
    the outcome column the pass owns.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        assessment = _add_orphan_assessment(session, case.id)
        invoice_a = _invoices(session)[0]
        assessment_id, invoice_a_id = assessment.id, invoice_a.id
        session.commit()

    assert _override(
        mapping_client, assessment_id, "link", invoice_id=invoice_a_id
    ).status_code == 200

    # A third invoice arrives. Processing it re-pairs the whole case.
    _upload(mapping_client, INVOICE_C)

    with _session(mapping_client) as session:
        assessment = session.get(EngineerAssessment, assessment_id)
        assert assessment.paired_invoice_id == invoice_a_id
        assert assessment.pair_source == "manual"
        assert assessment.pair_reasons_json == [MANUAL_LINK_REASON]
        # And the gap-fill that the link earned is re-applied by the very
        # pass that reverted it.
        assert session.get(Invoice, invoice_a_id).vehicle.vin == "VINMANUALOVERRIDE1"


def test_an_unlink_survives_a_later_document_upload(mapping_client) -> None:
    """"This report pairs with nothing" is an instruction, not an absence.

    Collapsing a cleared link into "the handler has said nothing" would let
    the next upload re-propose exactly the pair the handler had just removed,
    which is the same bug as losing a link and is easier to miss.
    """

    _case_with_two_invoices(mapping_client)
    assessment_document = _upload(mapping_client, "DL_Auda_format_2_assessment.docx")
    with _session(mapping_client) as session:
        assessment = session.scalar(
            select(EngineerAssessment).where(
                EngineerAssessment.document_id == assessment_document
            )
        )
        assert assessment.pair_status == "paired"
        assessment_id = assessment.id

    assert _override(mapping_client, assessment_id, "unlink").status_code == 200
    _upload(mapping_client, INVOICE_C)

    with _session(mapping_client) as session:
        assessment = session.get(EngineerAssessment, assessment_id)
        assert assessment.pair_status == "unpaired"
        assert assessment.paired_invoice_id is None
        assert assessment.pair_source == "manual"

    # And "reset" hands the decision back to the rule, which re-proposes the
    # pair it always would have.
    assert _override(mapping_client, assessment_id, "reset").status_code == 200
    with _session(mapping_client) as session:
        assessment = session.get(EngineerAssessment, assessment_id)
        assert assessment.pair_status == "paired"
        assert assessment.pair_source == "automatic"
        assert assessment.manual_pair_state is None


def test_repointing_undoes_the_old_gap_fill_and_applies_the_new_one(
    mapping_client,
) -> None:
    """Neha's own example: "change that from four to one".

    A value filled onto the wrong invoice is worse than no value at all --
    it is evidence the invoice never printed, sitting on somebody else's
    claim -- so re-pointing has to take it back off.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        assessment = _add_orphan_assessment(session, case.id)
        invoice_a, invoice_b = _invoices(session)[:2]
        # Both invoices print no VIN, so the fill is unambiguous either way.
        invoice_a.vehicle.vin = None
        invoice_b.vehicle.vin = None
        assessment_id, invoice_a_id, invoice_b_id = assessment.id, invoice_a.id, invoice_b.id
        session.commit()

    assert _override(
        mapping_client, assessment_id, "link", invoice_id=invoice_a_id
    ).status_code == 200
    with _session(mapping_client) as session:
        assert session.get(Invoice, invoice_a_id).vehicle.vin == "VINMANUALOVERRIDE1"
        assert "vin" in _field_sources(session, invoice_a_id)
        assert session.get(Invoice, invoice_b_id).vehicle.vin is None

    assert _override(
        mapping_client, assessment_id, "link", invoice_id=invoice_b_id
    ).status_code == 200
    with _session(mapping_client) as session:
        assert session.get(Invoice, invoice_a_id).vehicle.vin is None
        assert "vin" not in _field_sources(session, invoice_a_id)
        assert session.get(Invoice, invoice_b_id).vehicle.vin == "VINMANUALOVERRIDE1"
        assert _field_sources(session, invoice_b_id)["vin"]["value"] == "VINMANUALOVERRIDE1"

    # Clearing the link takes the value back off entirely: nothing the
    # assessment supplied may outlive the link that justified it.
    assert _override(mapping_client, assessment_id, "unlink").status_code == 200
    with _session(mapping_client) as session:
        assert session.get(Invoice, invoice_b_id).vehicle.vin is None
        assert "vin" not in _field_sources(session, invoice_b_id)


def test_a_manual_link_takes_the_invoice_off_an_automatic_claimant(
    mapping_client,
) -> None:
    """A person's answer beats the rule's proposal for the same invoice.

    Ranking the two against each other would be reasoning about evidence the
    handler has already weighed. The displaced assessment is told why, in the
    same "manual linkage required" vocabulary the rule already uses.
    """

    _case_with_two_invoices(mapping_client)
    assessment_document = _upload(mapping_client, "DL_Auda_format_2_assessment.docx")
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        automatic = session.scalar(
            select(EngineerAssessment).where(
                EngineerAssessment.document_id == assessment_document
            )
        )
        contested_invoice_id = automatic.paired_invoice_id
        assert contested_invoice_id is not None
        manual = _add_orphan_assessment(session, case.id)
        automatic_id, manual_id = automatic.id, manual.id
        session.commit()

    assert _override(
        mapping_client, manual_id, "link", invoice_id=contested_invoice_id
    ).status_code == 200

    with _session(mapping_client) as session:
        assert session.get(EngineerAssessment, manual_id).paired_invoice_id == (
            contested_invoice_id
        )
        displaced = session.get(EngineerAssessment, automatic_id)
        assert displaced.pair_status == "unpaired"
        assert displaced.pair_source == "automatic"
        assert displaced.pair_reasons_json == [MANUAL_OUTRANKS_REASON]


def test_two_handler_links_on_one_invoice_are_refused_at_the_write(
    mapping_client,
) -> None:
    """One invoice is one claim's invoice, so the second link is refused here.

    Refusing at the write, where the handler can be told which assessment
    already holds the invoice, beats accepting it and silently dropping one
    of the two inside the pairing pass.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        first = _add_orphan_assessment(session, case.id, "first-report.pdf")
        second = _add_orphan_assessment(
            session,
            case.id,
            "second-report.pdf",
            assessment_number="ORPHAN-2",
            created_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
        )
        invoice_a = _invoices(session)[0]
        first_id, second_id, invoice_a_id = first.id, second.id, invoice_a.id
        session.commit()

    assert _override(
        mapping_client, first_id, "link", invoice_id=invoice_a_id
    ).status_code == 200
    clash = _override(mapping_client, second_id, "link", invoice_id=invoice_a_id)
    assert clash.status_code == 409, clash.text
    assert clash.json()["detail"]["code"] == "INVOICE_ALREADY_LINKED"

    with _session(mapping_client) as session:
        assert session.get(EngineerAssessment, first_id).paired_invoice_id == invoice_a_id
        assert session.get(EngineerAssessment, second_id).paired_invoice_id is None
        assert session.get(EngineerAssessment, second_id).manual_pair_state is None


def test_two_handler_links_written_past_the_api_keep_the_earlier_one(
    mapping_client,
) -> None:
    """The pairing pass is defensive about a state the API refuses to create.

    A reset, a data import or a hand-edited row could still produce two
    handler links on one invoice. Keeping the earlier instruction and saying
    so is deterministic; applying both would put one invoice in two claims.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        invoice_a = _invoices(session)[0]
        earlier = _add_orphan_assessment(
            session,
            case.id,
            "earlier-report.pdf",
            created_at=datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        )
        later = _add_orphan_assessment(
            session,
            case.id,
            "later-report.pdf",
            assessment_number="ORPHAN-2",
            created_at=datetime(2026, 9, 17, 11, 0, tzinfo=UTC),
        )
        for assessment in (earlier, later):
            assessment.manual_pair_state = MANUAL_STATE_LINKED
            assessment.manual_pair_invoice_id = invoice_a.id
            assessment.manual_pair_actor = HANDLER
        earlier_id, later_id, invoice_a_id = earlier.id, later.id, invoice_a.id
        session.commit()

    sweep = mapping_client.post(f"/api/v1/claims/{REFERENCE}/documents/link-sweep")
    assert sweep.status_code == 200, sweep.text

    with _session(mapping_client) as session:
        assert session.get(EngineerAssessment, earlier_id).paired_invoice_id == invoice_a_id
        loser = session.get(EngineerAssessment, later_id)
        assert loser.paired_invoice_id is None
        assert loser.pair_reasons_json == [MANUAL_CONTESTED_REASON]
        # The instruction is kept on the row so the screen can show that it
        # could not be applied.
        assert loser.manual_pair_state == MANUAL_STATE_LINKED
        assert _row(
            mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json(),
            later_id,
        )["manual_override"]["applied"] is False


def test_an_override_whose_invoice_has_left_the_case_falls_back_to_the_rule(
    mapping_client,
) -> None:
    """An instruction that cannot be carried out is reported, not obeyed.

    The foreign key nulls the chosen invoice when it is deleted, which leaves
    a "linked" override pointing at nothing. Silently treating that as "no
    instruction" would be defensible; saying so on the payload, so the
    handler is asked again, is better.
    """

    _case_with_two_invoices(mapping_client)
    assessment_document = _upload(mapping_client, "DL_Auda_format_2_assessment.docx")
    with _session(mapping_client) as session:
        assessment = session.scalar(
            select(EngineerAssessment).where(
                EngineerAssessment.document_id == assessment_document
            )
        )
        automatic_invoice_id = assessment.paired_invoice_id
        other = next(
            invoice for invoice in _invoices(session) if invoice.id != automatic_invoice_id
        )
        assessment_id, other_id = assessment.id, other.id
        session.commit()

    assert _override(
        mapping_client, assessment_id, "link", invoice_id=other_id
    ).status_code == 200

    with _session(mapping_client) as session:
        session.delete(session.get(Invoice, other_id))
        session.commit()

    sweep = mapping_client.post(f"/api/v1/claims/{REFERENCE}/documents/link-sweep")
    assert sweep.status_code == 200, sweep.text

    with _session(mapping_client) as session:
        assessment = session.get(EngineerAssessment, assessment_id)
        assert assessment.manual_pair_state == MANUAL_STATE_LINKED
        assert assessment.manual_pair_invoice_id is None
        assert assessment.pair_source == "automatic"
        assert assessment.paired_invoice_id == automatic_invoice_id
        assert MANUAL_STALE_REASON in assessment.pair_reasons_json


def test_approving_records_the_decision_and_runs_the_sweep(mapping_client) -> None:
    """Approval is both halves: a recorded fact, and the trigger for gap-fill.

    The assessment below is inserted straight into the database, so nothing
    has paired it. If approving did not run the sweep it would still be
    unpaired afterwards.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        invoice_a = _invoices(session)[0]
        assessment = _add_orphan_assessment(
            session,
            case.id,
            "matching-report.pdf",
            claim_reference=invoice_a.claim_reference,
            policy_number=invoice_a.policy_number,
            registration=invoice_a.vehicle.registration,
        )
        assessment.pair_status = "unpaired"
        invoice_a.vehicle.vin = None
        assessment_id, invoice_a_id = assessment.id, invoice_a.id
        session.commit()

    approved = mapping_client.post(
        f"/api/v1/claims/{REFERENCE}/document-mapping/approve", json={"actor": HANDLER}
    )
    assert approved.status_code == 200, approved.text
    payload = approved.json()
    assert payload["approval"]["approved"] is True
    assert payload["approval"]["approved_by"] == HANDLER
    assert payload["approval"]["approved_at"] is not None
    assert payload["approval"]["approved_pairs"][assessment_id] == invoice_a_id

    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        assert case.mapping_approved_at is not None
        assert case.mapping_approved_by == HANDLER
        # The sweep ran: an assessment nothing had paired is now paired, and
        # its gap-fill is on the invoice.
        assert session.get(EngineerAssessment, assessment_id).pair_status == "paired"
        assert session.get(Invoice, invoice_a_id).vehicle.vin == "VINMANUALOVERRIDE1"
        assert session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "CASE_MAPPING_APPROVED")
        ) is not None

    # Re-running the same sweep must not un-approve an unchanged mapping, or
    # approval could never survive the gap-fill approval itself triggers.
    assert mapping_client.post(
        f"/api/v1/claims/{REFERENCE}/documents/link-sweep"
    ).status_code == 200
    assert (
        mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json()[
            "approval"
        ]["approved"]
        is True
    )


def test_approval_reopens_when_the_mapping_it_approved_changes(mapping_client) -> None:
    """"Approved" is a statement about particular pairs, not a flag.

    So it cannot outlive them. A later override changes the pairs, and the
    approval is dropped with an audit event rather than left standing over a
    mapping it no longer describes.
    """

    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        assessment = _add_orphan_assessment(session, case.id)
        invoice_a, invoice_b = _invoices(session)[:2]
        assessment_id, invoice_a_id, invoice_b_id = (
            assessment.id,
            invoice_a.id,
            invoice_b.id,
        )
        session.commit()

    assert _override(
        mapping_client, assessment_id, "link", invoice_id=invoice_a_id
    ).status_code == 200
    assert mapping_client.post(
        f"/api/v1/claims/{REFERENCE}/document-mapping/approve", json={"actor": HANDLER}
    ).status_code == 200

    assert _override(
        mapping_client, assessment_id, "link", invoice_id=invoice_b_id
    ).status_code == 200
    payload = mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json()
    assert payload["approval"]["approved"] is False
    assert payload["approval"]["approved_by"] is None

    with _session(mapping_client) as session:
        assert session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "CASE_MAPPING_APPROVAL_REOPENED"
            )
        ) is not None

    # And it can be approved again: approval is a gate, never a lock.
    assert mapping_client.post(
        f"/api/v1/claims/{REFERENCE}/document-mapping/approve", json={"actor": HANDLER}
    ).status_code == 200
    assert (
        mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json()[
            "approval"
        ]["approved"]
        is True
    )


def test_a_new_document_reopens_an_approved_mapping(mapping_client) -> None:
    """A document that changes the pairs invalidates the approval of them."""

    _case_with_two_invoices(mapping_client)
    assert mapping_client.post(
        f"/api/v1/claims/{REFERENCE}/document-mapping/approve", json={"actor": HANDLER}
    ).status_code == 200

    _upload(mapping_client, "DL_Auda_format_2_assessment.docx")

    payload = mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json()
    assert payload["approval"]["approved"] is False
    assert payload["paired"] == 1


def test_the_mapping_payload_lists_the_invoices_a_handler_can_choose_from(
    mapping_client,
) -> None:
    """The screen cannot offer a change without the candidates to change to."""

    _case_with_two_invoices(mapping_client)
    payload = mapping_client.get(f"/api/v1/claims/{REFERENCE}/document-mapping").json()
    assert len(payload["invoices"]) == 2
    for invoice in payload["invoices"]:
        assert invoice["invoice_id"]
        assert set(invoice) >= {
            "invoice_number",
            "supplier_name",
            "registration",
            "claim_reference",
            "policy_number",
            "document_filename",
        }


def test_a_link_decision_without_an_invoice_is_refused(mapping_client) -> None:
    _case_with_two_invoices(mapping_client)
    with _session(mapping_client) as session:
        case = session.scalar(select(Case).where(Case.case_reference == REFERENCE))
        assessment_id = _add_orphan_assessment(session, case.id).id
        session.commit()

    response = _override(mapping_client, assessment_id, "link")
    assert response.status_code == 422, response.text


def test_an_unknown_assessment_is_a_404(mapping_client) -> None:
    _case_with_two_invoices(mapping_client)
    response = _override(mapping_client, "missing-assessment", "unlink")
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "ASSESSMENT_NOT_FOUND"
