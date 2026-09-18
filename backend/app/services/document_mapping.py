"""The handler's review of which invoice each engineer assessment belongs to.

The pairing rule in ``app.services.engineer_assessment`` deliberately refuses
to guess: two assessments that fit one invoice equally well leave it unlinked,
and conflicting printed identities refuse the pair outright.  That is the
right call and it stays -- but it left those documents with no way out, because
nothing in the product could perform the "manual linkage required" the reasons
kept asking for.  This module is that way out:

* a handler sets, changes or clears the invoice an assessment is paired to;
* the instruction is stored apart from the rule's outcome, so the next upload
  re-applies it instead of overwriting it (see ``_apply_manual_overrides``);
* the handler approves the mapping, which is recorded against the exact pairs
  approved and runs the case-wide gap-fill sweep over them.

Nothing here weakens an automatic rule.  The rule still refuses to guess; the
human is the escape hatch, not a reason to lower the bar.

Not to be confused with ``app.services.mapping_review``, which reviews the
*ontology* mapping of one invoice line to a priced repair item.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db_types import utc_now
from app.enums import AuditActorType, CaseStatus
from app.models import AuditEvent, Case, EngineerAssessment, Invoice
from app.services.engineer_assessment import (
    MANUAL_STATE_CLEARED,
    MANUAL_STATE_LINKED,
    PAIR_SOURCE_MANUAL,
    _compare_pair_keys,
    _printed_identity,
    group_pair_map,
    manual_override_payload,
    run_case_gap_fill,
)

#: What a handler may do to one assessment's pairing.  ``reset`` is not the
#: same as ``unlink``: it withdraws the instruction and hands the decision
#: back to the rule, where ``unlink`` is an instruction in its own right that
#: the rule must not overturn on the next upload.
DECISION_LINK = "link"
DECISION_UNLINK = "unlink"
DECISION_RESET = "reset"
DECISIONS = frozenset({DECISION_LINK, DECISION_UNLINK, DECISION_RESET})


class DocumentMappingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _finalised_guard(case: Case) -> None:
    if case.status == CaseStatus.FINALISED:
        raise DocumentMappingError(
            "CASE_ALREADY_FINALISED",
            "Create a new case revision before changing the document mapping.",
        )


def _load_assessments(session: Session, case: Case) -> list[EngineerAssessment]:
    return list(
        session.scalars(
            select(EngineerAssessment)
            .where(EngineerAssessment.case_id == case.id)
            .options(
                selectinload(EngineerAssessment.paired_invoice).selectinload(Invoice.vehicle),
                selectinload(EngineerAssessment.manual_pair_invoice),
                selectinload(EngineerAssessment.document),
            )
            .order_by(EngineerAssessment.created_at, EngineerAssessment.id)
        ).all()
    )


def _load_invoices(session: Session, case: Case) -> list[Invoice]:
    return list(
        session.scalars(
            select(Invoice)
            .where(Invoice.case_id == case.id)
            .options(selectinload(Invoice.vehicle), selectinload(Invoice.document))
            .order_by(Invoice.created_at, Invoice.id)
        )
        .unique()
        .all()
    )


def _intake_group(document: Any) -> str | None:
    return (getattr(document, "metadata_json", None) or {}).get("intake_group")


def _invoice_row(invoice: Invoice) -> dict[str, Any]:
    return {
        "invoice_id": invoice.id,
        "document_id": invoice.document_id,
        "document_filename": (
            invoice.document.original_filename if invoice.document is not None else None
        ),
        "invoice_number": invoice.invoice_number,
        "supplier_name": invoice.supplier_name,
        "registration": invoice.vehicle.registration if invoice.vehicle else None,
        "claim_reference": invoice.claim_reference,
        "policy_number": invoice.policy_number,
        "intake_group": _intake_group(invoice.document),
    }


def _assessment_row(assessment: EngineerAssessment) -> dict[str, Any]:
    """One row of the mapping screen: the identity, the pair, and the why.

    ``pair_key_verdicts`` is computed against whichever invoice the assessment
    is actually paired to, by the same function the pairing rule uses, so a
    handler's link is evidenced on the screen exactly as an automatic one is
    -- including when the handler linked two documents whose printed
    identities disagree.  That is their decision to take; it is not hidden.
    """

    invoice = assessment.paired_invoice
    return {
        "assessment_id": assessment.id,
        "document_id": assessment.document_id,
        "document_filename": (
            assessment.document.original_filename if assessment.document is not None else None
        ),
        "assessment_number": assessment.assessment_number,
        "registration": assessment.registration,
        "claim_reference": assessment.claim_reference,
        "policy_number": assessment.policy_number,
        "vehicle_make": assessment.vehicle_make,
        "vehicle_model": assessment.vehicle_model,
        "intake_group": _intake_group(assessment.document),
        "pair_status": assessment.pair_status,
        "pair_source": assessment.pair_source,
        "pair_confidence": assessment.pair_confidence,
        "pair_reasons": assessment.pair_reasons_json or [],
        "pair_key_verdicts": (
            [
                verdict.as_payload()
                for verdict in _compare_pair_keys(assessment, _printed_identity(invoice))
            ]
            if invoice is not None
            else []
        ),
        "paired_invoice_id": assessment.paired_invoice_id,
        "paired_invoice_number": invoice.invoice_number if invoice is not None else None,
        "manual_override": manual_override_payload(assessment),
    }


def _approval_payload(case: Case) -> dict[str, Any]:
    return {
        "approved": case.mapping_approved_at is not None,
        "approved_by": case.mapping_approved_by,
        "approved_at": (
            case.mapping_approved_at.isoformat() if case.mapping_approved_at else None
        ),
        "approved_pairs": case.mapping_approved_pairs_json or {},
    }


def _group_approval_payload(case: Case, intake_group: str) -> dict[str, Any]:
    """The same shape as ``_approval_payload``, for one upload source."""

    approval = (case.mapping_group_approvals_json or {}).get(intake_group) or {}
    return {
        "approved": bool(approval),
        "approved_by": approval.get("approved_by"),
        "approved_at": approval.get("approved_at"),
        "approved_pairs": approval.get("pairs") or {},
    }


def case_mapping_payload(
    session: Session, case: Case, intake_group: str | None = None
) -> dict[str, Any]:
    """Everything the mapping review screen needs, in one read.

    With ``intake_group`` the screen is one upload source: only its invoices
    and assessments, and that source's own approval.  Without it the payload
    is exactly what it has always been, case-level approval included.
    """

    assessments = _load_assessments(session, case)
    invoices = _load_invoices(session, case)
    if intake_group is not None:
        assessments = [row for row in assessments if _intake_group(row.document) == intake_group]
        invoices = [row for row in invoices if _intake_group(row.document) == intake_group]
    rows = [_assessment_row(assessment) for assessment in assessments]
    payload = {
        "case_reference": case.case_reference,
        "approval": (
            _approval_payload(case)
            if intake_group is None
            else _group_approval_payload(case, intake_group)
        ),
        "invoices": [_invoice_row(invoice) for invoice in invoices],
        "assessments": rows,
        "assessments_total": len(rows),
        "paired": sum(1 for row in rows if row["pair_status"] == "paired"),
        "unpaired": sum(1 for row in rows if row["pair_status"] != "paired"),
        "manual": sum(1 for row in rows if row["pair_source"] == PAIR_SOURCE_MANUAL),
    }
    if intake_group is not None:
        payload["intake_group"] = intake_group
    return payload


def override_assessment_pairing(
    session: Session,
    *,
    case: Case,
    assessment_id: str,
    decision: str,
    invoice_id: str | None,
    actor: str,
    reason: str | None,
) -> dict[str, Any]:
    """Record a handler's decision about one assessment's invoice.

    The write is only to the ``manual_pair_*`` columns; the pairing pass is
    then re-run in full, which is what turns the instruction into an outcome
    -- and, because that pass reverts and re-applies every gap-fill in the
    case, is also what undoes the values filled from the old partner and
    fills them from the new one.  Doing it this way rather than by patching
    ``paired_invoice_id`` directly is what keeps one code path responsible
    for the invoice's field attribution.
    """

    _finalised_guard(case)
    if decision not in DECISIONS:
        raise DocumentMappingError(
            "UNSUPPORTED_MAPPING_DECISION",
            f"Unsupported mapping decision {decision!r}.",
        )
    assessment = session.scalar(
        select(EngineerAssessment).where(
            EngineerAssessment.id == assessment_id,
            EngineerAssessment.case_id == case.id,
        )
    )
    if assessment is None:
        raise DocumentMappingError(
            "ASSESSMENT_NOT_FOUND", "Engineer assessment not found in this claim."
        )

    invoice: Invoice | None = None
    if decision == DECISION_LINK:
        if not invoice_id:
            raise DocumentMappingError(
                "INVOICE_REQUIRED", "Choose the invoice this engineer assessment belongs to."
            )
        invoice = session.scalar(
            select(Invoice).where(Invoice.id == invoice_id, Invoice.case_id == case.id)
        )
        if invoice is None:
            raise DocumentMappingError(
                "INVOICE_NOT_FOUND", "Invoice not found in this claim."
            )
        # One invoice belongs to one claim, so two handler links on one
        # invoice cannot both stand. Refusing here, where the handler can see
        # which assessment already holds it, is better than accepting the
        # write and silently dropping one of the two in the pairing pass.
        holder = session.scalar(
            select(EngineerAssessment).where(
                EngineerAssessment.case_id == case.id,
                EngineerAssessment.id != assessment.id,
                EngineerAssessment.manual_pair_state == MANUAL_STATE_LINKED,
                EngineerAssessment.manual_pair_invoice_id == invoice.id,
            )
        )
        if holder is not None:
            raise DocumentMappingError(
                "INVOICE_ALREADY_LINKED",
                (
                    "Another engineer assessment is already linked to this "
                    "invoice by hand. Clear that link first."
                ),
            )

    before = {
        "manual_pair_state": assessment.manual_pair_state,
        "manual_pair_invoice_id": assessment.manual_pair_invoice_id,
        "paired_invoice_id": assessment.paired_invoice_id,
        "pair_status": assessment.pair_status,
        "pair_source": assessment.pair_source,
    }

    if decision == DECISION_RESET:
        assessment.manual_pair_state = None
        assessment.manual_pair_invoice_id = None
        assessment.manual_pair_actor = None
        assessment.manual_pair_at = None
        assessment.manual_pair_reason = None
    else:
        assessment.manual_pair_state = (
            MANUAL_STATE_LINKED if decision == DECISION_LINK else MANUAL_STATE_CLEARED
        )
        assessment.manual_pair_invoice_id = invoice.id if invoice is not None else None
        assessment.manual_pair_actor = actor
        assessment.manual_pair_at = utc_now()
        assessment.manual_pair_reason = reason
    session.flush()

    # Re-decide the whole case rather than this one assessment: the invoice
    # the handler has just taken may have been another assessment's automatic
    # pair, and that assessment's gap-fill has to come back off the invoice.
    run_case_gap_fill(session, case.id)
    session.flush()

    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type=f"ASSESSMENT_MAPPING_{decision.upper()}",
            entity_type="engineer_assessment",
            entity_id=assessment.id,
            before_json=before,
            after_json={
                "manual_pair_state": assessment.manual_pair_state,
                "manual_pair_invoice_id": assessment.manual_pair_invoice_id,
                "paired_invoice_id": assessment.paired_invoice_id,
                "pair_status": assessment.pair_status,
                "pair_source": assessment.pair_source,
                "reason": reason,
            },
            event_payload_json={
                "decision": decision,
                # The printed evidence at the moment of the decision, so a
                # reader of the trail can see what the handler overruled --
                # including a conflict they chose to link across.
                "pair_reasons": assessment.pair_reasons_json or [],
                "gap_fill_reapplied": True,
            },
        )
    )
    return case_mapping_payload(session, case)


def approve_case_mapping(
    session: Session, *, case: Case, actor: str, intake_group: str | None = None
) -> dict[str, Any]:
    """Approve the mapping, and run the case-wide sweep over what was approved.

    The sweep runs *first* and the approval is recorded against its result.
    That order matters: the handler is approving the pairs they were shown,
    and running the sweep afterwards could change those pairs under an
    approval that had already been written.  Running it first also means
    approval is the moment gap-fill is applied over the confirmed pairs,
    which is what the step is for.

    Approval is not a lock.  It is reopened automatically the moment the
    mapping it describes stops being true -- a new document, a later override
    -- by ``_expire_mapping_approval``.  Locking it would recreate the
    dead-end this whole feature exists to remove.
    """

    _finalised_guard(case)
    run_case_gap_fill(session, case.id)
    session.flush()

    if intake_group is not None:
        return _approve_group_mapping(session, case=case, actor=actor, intake_group=intake_group)

    assessments = _load_assessments(session, case)
    pairs: dict[str, str | None] = {
        assessment.id: assessment.paired_invoice_id for assessment in assessments
    }
    unpaired = [
        assessment.id for assessment in assessments if assessment.paired_invoice_id is None
    ]
    case.mapping_approved_at = utc_now()
    case.mapping_approved_by = actor
    case.mapping_approved_pairs_json = pairs
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type="CASE_MAPPING_APPROVED",
            entity_type="case",
            entity_id=case.id,
            before_json=None,
            after_json={
                "approved_at": case.mapping_approved_at.isoformat(),
                "pairs": pairs,
            },
            event_payload_json={
                # An approval that leaves assessments unpaired is a real
                # decision -- some reports genuinely have no invoice in the
                # claim yet -- so it is recorded rather than refused.
                "unpaired_assessments": unpaired,
                "gap_fill_ran": True,
            },
        )
    )
    return case_mapping_payload(session, case)


def _approve_group_mapping(
    session: Session, *, case: Case, actor: str, intake_group: str
) -> dict[str, Any]:
    """Approve one upload source's mapping; every other source is untouched.

    Recorded against that source's pairs only, so
    ``engineer_assessment._expire_group_mapping_approvals`` can reopen it
    alone when those pairs change.  The sweep has already run in
    ``approve_case_mapping``, exactly as for a case-level approval.
    """

    assessments = _load_assessments(session, case)
    pairs = group_pair_map(assessments, intake_group)
    approved_at = utc_now().isoformat()
    approvals = dict(case.mapping_group_approvals_json or {})
    approvals[intake_group] = {
        "approved_at": approved_at,
        "approved_by": actor,
        "pairs": pairs,
    }
    # A new dict, so the JSON column registers the change.
    case.mapping_group_approvals_json = approvals
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type="CASE_MAPPING_APPROVED",
            entity_type="case",
            entity_id=case.id,
            before_json=None,
            after_json={"intake_group": intake_group, "approved_at": approved_at, "pairs": pairs},
            event_payload_json={
                "intake_group": intake_group,
                "unpaired_assessments": [
                    assessment_id
                    for assessment_id, invoice_id in pairs.items()
                    if invoice_id is None
                ],
                "gap_fill_ran": True,
            },
        )
    )
    return case_mapping_payload(session, case, intake_group)
