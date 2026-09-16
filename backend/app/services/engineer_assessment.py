"""Pair Engineer Assessments with invoices and persist explainable variances."""

from __future__ import annotations

import dataclasses
import re
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session, selectinload

from app.domain.line_item_type import ensure_line_item_type
from app.domain.normalisation import normalise_identifier
from app.models import (
    AssessmentInvoiceVariance,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
)

#: The three printed identities an invoice and an assessment can share, with
#: the wording used in ``pair_reasons_json``.  The invoice number is
#: deliberately absent: formats 1 and 7 print the *same* invoice number
#: ("343653726836/1~3538") for two different claims, so keying on it would
#: cross-link them.  ``metadata_json["assessment_reference"]`` (format 2's
#: "BOY1537") is absent for the same reason -- it matches nothing on the
#: report it accompanies and is display evidence only.
PAIR_KEYS: tuple[tuple[str, str], ...] = (
    ("registration", "registration"),
    ("claim_reference", "claim reference"),
    ("policy_number", "policy number"),
)

#: Fields the assessment can fill on the invoice's vehicle, as
#: ``vehicle attribute -> assessment attribute``.
VEHICLE_FILL_FIELDS: tuple[tuple[str, str], ...] = (
    ("make", "vehicle_make"),
    ("model", "vehicle_model"),
    ("variant", "vehicle_variant"),
    ("registration", "registration"),
    ("vin", "vin"),
    ("mileage", "mileage"),
)

#: Fields the assessment can fill on the invoice itself.
INVOICE_FILL_FIELDS: tuple[tuple[str, str], ...] = (
    ("claim_reference", "claim_reference"),
    ("policy_number", "policy_number"),
)

INVOICE_FILL_NAMES = frozenset(name for name, _ in INVOICE_FILL_FIELDS)

FILL_LABEL = "Filled from engineer assessment"

#: One invoice cannot be two claims' invoice, and one invoice cannot be
#: claimed by two different assessments.  Both ambiguities end the same way:
#: nothing is linked and nothing is filled until a handler says which.
AMBIGUOUS_INVOICES_REASON = (
    "Multiple invoices share the same identifiers; manual linkage required"
)
AMBIGUOUS_ASSESSMENTS_REASON = (
    "Multiple assessments share the same identifiers; manual linkage required"
)
NO_SHARED_IDENTIFIER_REASON = (
    "No invoice shares a printed registration, claim reference or policy number "
    "with this assessment"
)
EXPLICIT_LINK_REASON = "Uploaded together for this invoice"

#: Substring that marks a per-key verdict as a disagreement rather than an
#: absence.  Only a disagreement blocks a link.
CONFLICT_MARKER = " conflict: "

#: The three states a pairing key can be in.  ``NOT_COMPARED`` is neither a
#: match nor a conflict: the client's rule is "match what is there", so a key
#: only one document prints carries no information about the pair at all.
KEY_MATCHED = "matched"
KEY_CONFLICT = "conflict"
KEY_NOT_COMPARED = "not_compared"

#: Prefix on the ``pair_reasons`` entry that says a link rests on a single
#: comparable identity.  Loosening the rule to "compare what is printed" makes
#: one-key links possible -- an invoice printing only a registration now pairs
#: on the registration alone -- so every such link is labelled at the point the
#: reason is read rather than being silently indistinguishable from a
#: three-key agreement.  The contention rule (``_resolve_contention``) is what
#: stops two same-vehicle claims racing for that invoice; this prefix is what
#: stops a handler mistaking the survivor for strong evidence.
WEAK_PAIR_PREFIX = "weak pair: "

#: An invoice section total resolves to one assessment section total.  Note
#: that the assessment's ``paint_net`` is the paint *materials* cost (the
#: "Total Paint & Materials" line), while paintwork *labour* is part of
#: ``labour_net``.
SECTION_TOTAL_FIELDS: dict[str, str] = {
    "parts": "parts_net",
    "paint_materials": "paint_net",
    "extras": "extras_net",
    "labour": "labour_net",
}

#: An invoice "Total Labour" pays for both of the assessment's work-unit
#: sections -- panel/mechanical labour *and* paintwork -- so the breakdown for
#: a labour total is the union of both.  Every other resolvable section maps
#: to the operations carrying its own code.
SECTION_OPERATION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "labour": ("labour", "paint"),
}

#: Section totals are compared to the penny.
SECTION_TOTAL_TOLERANCE = Decimal("0.01")

#: ``difference`` is always the invoice's figure minus the assessment's, so a
#: positive number means the repairer billed more than the engineer assessed.
DIFFERENCE_CONVENTION = "invoice_total - assessment_total"

ALIASES = {
    "front bumper remove refit": "front bumper remove refit",
    "r r front bumper": "front bumper remove refit",
    "front bumper": "front bumper remove refit",
    "radiator grille remove refit": "radiator grille remove refit",
    "r r radiator grille": "radiator grille remove refit",
    "radar sensor calibrate": "radar sensor calibrate",
    "front bumper repair paint plastic": "front bumper paint",
    "paint front bumper": "front bumper paint",
    "vehicle recovery": "vehicle recovery",
    "standard vehicle recovery": "vehicle recovery",
}


def normalise_operation(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    text = re.sub(r"\b(r and r|remove and refit|remove refit)\b", "remove refit", text)
    for alias, canonical in ALIASES.items():
        if alias in text:
            return canonical
    return text


def _match_score(left: str, right: str) -> float:
    left_norm = normalise_operation(left)
    right_norm = normalise_operation(right)
    if left_norm == right_norm:
        return 1.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _fill_holder(invoice: Invoice, field: str):
    """Where a filled field lives: the invoice itself, or its vehicle."""

    return invoice if field in INVOICE_FILL_NAMES else invoice.vehicle


def _revert_assessment_fills(invoice: Invoice, assessment_documents: set[str]) -> None:
    """Undo every gap-fill any assessment in the case made on this invoice.

    This runs once for the whole case *before* a single pairing decision is
    taken.  Reverting only the assessment currently under consideration let
    one assessment's fill become the printed evidence the next assessment was
    judged against, which is how a second claimant was rejected on a
    "conflict" with a value the invoice never printed.

    A value a handler has since changed is left alone -- the attribution is
    dropped, but the correction outranks the assessment and is never reverted.
    """

    metadata = invoice.document.metadata_json or {}
    sources = dict(metadata.get("field_sources", {}))
    for field, source in list(sources.items()):
        if source.get("document_id") not in assessment_documents:
            continue
        holder = _fill_holder(invoice, field)
        if holder is not None and getattr(holder, field, None) == source.get("value"):
            setattr(holder, field, None)
        del sources[field]
    invoice.document.metadata_json = {**metadata, "field_sources": sources}


def _printed_identity(invoice: Invoice) -> dict[str, str | None]:
    """The three identities the invoice itself printed.

    A value an assessment filled into a gap is evidence about the assessment,
    not about the invoice, so it is excluded here even though it is live on
    the row.  ``field_sources`` records every such fill, which is what makes
    the printed value recoverable after the fact.
    """

    sources = (
        (invoice.document.metadata_json or {}).get("field_sources", {})
        if invoice.document is not None
        else {}
    )
    live: dict[str, str | None] = {
        "registration": invoice.vehicle.registration if invoice.vehicle else None,
        "claim_reference": invoice.claim_reference,
        "policy_number": invoice.policy_number,
    }
    return {
        name: None if (sources.get(name) or {}).get("value") == value else value
        for name, value in live.items()
    }


@dataclasses.dataclass(frozen=True)
class _KeyVerdict:
    """One pairing key's outcome, in the three states the UI has to show.

    ``text`` is the sentence the review screens already render; the machine
    readable fields beside it are what let a screen colour a conflict red and
    an absence grey without parsing prose.
    """

    key: str
    label: str
    state: str
    text: str
    #: ``"invoice"``, ``"assessment"`` or ``"both"`` when the key was skipped
    #: for absence; ``None`` when it was actually compared.
    absent_on: str | None = None
    assessment_value: str | None = None
    invoice_value: str | None = None

    @property
    def compared(self) -> bool:
        return self.state in {KEY_MATCHED, KEY_CONFLICT}

    def as_payload(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "compared": self.compared,
            "absent_on": self.absent_on,
            "assessment_value": self.assessment_value,
            "invoice_value": self.invoice_value,
            "text": self.text,
        }


def _compare_pair_keys(
    assessment: EngineerAssessment, printed: dict[str, str | None]
) -> list[_KeyVerdict]:
    """Compare the printed identities the two documents have in common.

    ``printed`` is the invoice's *printed* identity snapshot from
    ``_printed_identity`` -- never the live attributes, which may already
    carry another assessment's gap-fill.

    The client's rule is "claim + policy + registration; in case any one is
    missing, just match what is there".  So a key is *compared* only when both
    documents print it, and a key only one side prints is neither a match nor
    a conflict -- it drops out of the arithmetic entirely.  Two of the three
    client pairs print no policy number on the invoice, and under the previous
    "every printed key must agree, scored out of three" rule they could never
    read as more than two-thirds certain.

    A key printed on both sides that disagrees is still a conflict, and a
    conflict is still fatal however well the other keys read: two different
    claims can share a repairer, a registration or (as formats 1 and 7 do) an
    invoice number, but they cannot share a claim reference.
    """

    verdicts: list[_KeyVerdict] = []
    for key, label in PAIR_KEYS:
        assessment_value = getattr(assessment, key, None)
        invoice_value = printed.get(key)
        left = normalise_identifier(assessment_value)
        right = normalise_identifier(invoice_value)
        common = {
            "key": key,
            "label": label,
            "assessment_value": assessment_value,
            "invoice_value": invoice_value,
        }
        if left and right:
            state = KEY_MATCHED if left == right else KEY_CONFLICT
            text = (
                f"{label} exact match"
                if state == KEY_MATCHED
                else f"{label}{CONFLICT_MARKER}assessment {assessment_value} "
                f"versus invoice {invoice_value}"
            )
            verdicts.append(_KeyVerdict(state=state, text=text, **common))
            continue
        absent_on = "invoice" if left else "assessment" if right else "both"
        text = {
            "invoice": f"{label} not printed on the invoice",
            "assessment": f"{label} not printed on the assessment",
            "both": f"{label} not printed on either document",
        }[absent_on]
        verdicts.append(
            _KeyVerdict(
                state=KEY_NOT_COMPARED, text=text, absent_on=absent_on, **common
            )
        )
    return verdicts


def _matched_reasons(matched: set[str]) -> list[str]:
    """The positive verdicts, in key order -- what justifies a link."""

    return [f"{label} exact match" for key, label in PAIR_KEYS if key in matched]


def _weak_pair_reason(verdicts: list[_KeyVerdict]) -> str | None:
    """Say so, in the reasons, when a link rests on one comparable key.

    A single-key link is a real link -- the client asked for it -- but it is
    the weakest one the rule can produce, so it is never allowed to read like
    a three-key agreement on the screens that join ``pair_reasons`` into a
    sentence.
    """

    compared = [verdict for verdict in verdicts if verdict.compared]
    if len(compared) != 1:
        return None
    skipped = [verdict.label for verdict in verdicts if not verdict.compared]
    return (
        f"{WEAK_PAIR_PREFIX}only the {compared[0].label} was comparable; "
        f"{' and '.join(skipped)} not printed on both documents"
    )


def _assessment_identity(assessment: EngineerAssessment) -> tuple[str | None, ...]:
    return tuple(
        normalise_identifier(getattr(assessment, key, None)) for key, _ in PAIR_KEYS
    )


@dataclasses.dataclass
class _Candidate:
    invoice: Invoice
    confidence: float
    matched: set[str]
    verdicts: list[_KeyVerdict]

    @property
    def strength(self) -> tuple[int, float]:
        """How good this candidate is, best first.

        Confidence alone can no longer rank candidates: every eligible
        candidate now agrees on every key it could compare, so all of them
        score 1.0.  The count of keys that actually agreed is what separates a
        registration-only link from a registration-and-claim link, and the
        confidence stays in the tuple only so a candidate reached through an
        explicit upload association with nothing matched still sorts last.
        """

        return len(self.matched), self.confidence


@dataclasses.dataclass
class _Decision:
    assessment: EngineerAssessment
    invoice: Invoice | None = None
    confidence: float = 0.0
    reasons: list[str] = dataclasses.field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.invoice = None
        self.confidence = 0.0
        self.reasons = [reason]


def _select_invoice(
    assessment: EngineerAssessment,
    invoices: list[Invoice],
    printed: dict[str, dict[str, str | None]],
) -> _Decision:
    """Choose the one invoice this assessment may link to, or none.

    Eligibility, per the client's "match what is there": at least one key is
    compared (printed on both documents) and matches, and no compared key
    disagrees.  A key only one side prints is skipped, so it can neither
    qualify nor disqualify a candidate.  No key is privileged any more --
    the earlier rule demanded a registration *or* claim match, which refused
    the only evidence a document carrying just a policy number can offer.

    Residual risk, deliberately accepted and now labelled: a link resting on
    one comparable key -- a registration on an invoice that prints no claim
    reference, say -- may attach a report to a *different* claim on the same
    vehicle.  That is exactly the shape of the five
    ``sample-data/engineer-invoice-pairs`` fixtures, which is why the rule
    stays.  Three things contain it: two assessments in that position leave
    the invoice unlinked rather than racing for it (``_resolve_contention``),
    a candidate that agrees on more keys always outranks one that agrees on
    fewer (``_Candidate.strength``), and a one-key link says so in its reasons
    (``_weak_pair_reason``).
    """

    metadata = assessment.document.metadata_json or {}
    explicit_document = metadata.get("paired_document_id")
    assessment_group = metadata.get("intake_group")
    candidates: list[_Candidate] = []
    rejected: list[_Candidate] = []
    conflicting: list[_Candidate] = []
    for invoice in invoices:
        invoice_group = (invoice.document.metadata_json or {}).get("intake_group")
        if assessment_group != invoice_group:
            continue
        if explicit_document and invoice.document_id != explicit_document:
            continue
        verdicts = _compare_pair_keys(assessment, printed[invoice.id])
        matched = {verdict.key for verdict in verdicts if verdict.state == KEY_MATCHED}
        compared = sum(1 for verdict in verdicts if verdict.compared)
        conflict = any(verdict.state == KEY_CONFLICT for verdict in verdicts)
        # An explicit upload association buys no confidence it has not earned:
        # the number is always the share of the *comparable* keys that agree,
        # and the association itself is carried as a reason instead.  Nothing
        # comparable at all is 0.0 rather than a division by zero, which only
        # an explicitly associated pair can reach.
        candidate = _Candidate(
            invoice, len(matched) / compared if compared else 0.0, matched, verdicts
        )
        if conflict:
            # An explicit upload association must not override conflicting
            # identities, so this drops the candidate even when the two
            # documents were uploaded together. The verdicts are kept so an
            # unpaired assessment can still say what disagreed.
            conflicting.append(dataclasses.replace(candidate, confidence=0.0))
            continue
        if explicit_document:
            candidates.append(candidate)
            continue
        (candidates if matched else rejected).append(candidate)

    candidates.sort(key=lambda row: row.strength, reverse=True)
    rejected.sort(key=lambda row: row.strength, reverse=True)
    # Two candidates agreeing on the same number of keys are equally good
    # evidence, and guessing between them is what the contention rule exists
    # to refuse.  More agreeing keys wins outright.
    ambiguous = len(candidates) > 1 and candidates[0].strength == candidates[1].strength
    if candidates and not ambiguous:
        chosen = candidates[0]
        reasons = _matched_reasons(chosen.matched)
        weak = _weak_pair_reason(chosen.verdicts)
        if weak:
            reasons = [*reasons, weak]
        if explicit_document:
            reasons = [EXPLICIT_LINK_REASON, *reasons]
        return _Decision(assessment, chosen.invoice, min(chosen.confidence, 1.0), reasons)

    if ambiguous:
        return _Decision(assessment, None, 0.0, [AMBIGUOUS_INVOICES_REASON])
    fallback = next(iter(rejected or conflicting), None)
    if fallback is None:
        return _Decision(assessment, None, 0.0, [NO_SHARED_IDENTIFIER_REASON])
    conflicts = [
        verdict.text for verdict in fallback.verdicts if verdict.state == KEY_CONFLICT
    ]
    return _Decision(assessment, None, 0.0, conflicts or [NO_SHARED_IDENTIFIER_REASON])


def _resolve_contention(decisions: list[_Decision]) -> None:
    """Refuse the links where two assessments both reach for one invoice."""

    by_invoice: dict[str, list[_Decision]] = {}
    for decision in decisions:
        if decision.invoice is not None:
            by_invoice.setdefault(decision.invoice.id, []).append(decision)
    for claimants in by_invoice.values():
        if len(claimants) < 2:
            continue
        if len({_assessment_identity(row.assessment) for row in claimants}) == 1:
            # The same identity uploaded twice: the first report keeps the
            # link, and refusing the duplicate changes nothing on the invoice.
            for duplicate in claimants[1:]:
                duplicate.reject(AMBIGUOUS_ASSESSMENTS_REASON)
            continue
        # Two *different* identities cannot both be this invoice's. Linking
        # either would write a claim reference the invoice never printed, so
        # neither is linked and the invoice keeps only what it printed.
        for claimant in claimants:
            claimant.reject(AMBIGUOUS_ASSESSMENTS_REASON)


def _fill_invoice_gaps(invoice: Invoice, assessment: EngineerAssessment) -> None:
    """Fill the invoice's mandatory gaps, recording where each value came from.

    Only nulls are filled and nothing is overwritten: a handler correction
    made after an earlier pass survives because ``_revert_assessment_fills``
    only reverts a value it still recognises as its own.
    """

    metadata = invoice.document.metadata_json or {}
    sources = dict(metadata.get("field_sources", {}))
    fills: list[tuple[object, str, str]] = [
        (invoice, field, assessment_field)
        for field, assessment_field in INVOICE_FILL_FIELDS
    ]
    if invoice.vehicle:
        fills += [
            (invoice.vehicle, field, assessment_field)
            for field, assessment_field in VEHICLE_FILL_FIELDS
        ]
    for holder, field, assessment_field in fills:
        value = getattr(assessment, assessment_field)
        if getattr(holder, field) in (None, "") and value not in (None, ""):
            setattr(holder, field, value)
            sources[field] = {
                "document_id": assessment.document_id,
                "label": FILL_LABEL,
                "value": value,
            }
    invoice.document.metadata_json = {**metadata, "field_sources": sources}


def _record_variances(
    session: Session, assessment: EngineerAssessment, invoice: Invoice
) -> None:
    used_lines: set[str] = set()
    for operation in assessment.operations:
        ranked = sorted(
            (
                (_match_score(operation.raw_description, line.raw_description), line)
                for line in invoice.line_items
                if line.id not in used_lines
            ),
            key=lambda row: row[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < 0.34:
            continue
        match_confidence, line = ranked[0]
        used_lines.add(line.id)
        engineer = Decimal(operation.total_net) if operation.total_net is not None else None
        billed = Decimal(line.line_total_net) if line.line_total_net is not None else None
        difference = billed - engineer if engineer is not None and billed is not None else None
        percentage = (
            difference / engineer * Decimal("100")
            if difference is not None and engineer not in {None, Decimal("0")}
            else None
        )
        threshold = (
            "above_10_percent"
            if difference is not None and percentage is not None
            and difference >= Decimal("5") and percentage > Decimal("10")
            else "above_5_percent"
            if difference is not None and percentage is not None
            and difference >= Decimal("5") and percentage > Decimal("5")
            else "within_threshold"
        )
        session.add(
            AssessmentInvoiceVariance(
                assessment_operation_id=operation.id,
                invoice_id=invoice.id,
                invoice_line_item_id=line.id,
                matching_method="canonical_description",
                match_confidence=match_confidence,
                engineer_amount=engineer,
                invoice_amount=billed,
                difference_amount=difference,
                difference_percentage=percentage,
                threshold_status=threshold,
                explanation=(
                    f"Invoice £{billed:.2f} versus engineer assessment £{engineer:.2f}; "
                    f"variance £{difference:.2f} ({percentage:.1f}%)."
                    if None not in {engineer, billed, difference, percentage}
                    else "Comparable descriptions matched; monetary comparison unavailable."
                ),
            )
        )


def pair_case_assessments(session: Session, case_id: str) -> None:
    """Re-evaluate every assessment/invoice link in one case, from scratch.

    The pass is deliberately whole-case and ordered:

    * assessments are read oldest first, so the outcome does not depend on the
      order the database happens to hand rows back;
    * every gap-fill any of them made is reverted *before* the first decision,
      and each invoice's printed identity is snapshotted, so no assessment is
      ever judged against another assessment's fill;
    * contention between two assessments reaching for one invoice is resolved
      after all of them have chosen, not by whoever got there first.

    ``pair_reasons_json`` carries the reasons for the outcome, never the raw
    per-key verdicts: a linked assessment lists the keys that matched (the
    review screen renders them as "paired ... using <reasons>") plus a
    ``weak pair:`` note when only one key could be compared, an unlinked one
    lists what blocked it.  The full per-key verdicts reach the UI on the
    payload as ``pair_key_verdicts``.

    ``pair_confidence`` is matched keys over *compared* keys, so the two
    client pairs whose invoices print no policy number read 2/2 rather than
    2/3: the number answers "how much of the available evidence agrees", and
    how many identities the repairer chose to print is not evidence about
    whether these two documents describe the same repair.
    """

    assessments = session.scalars(
        select(EngineerAssessment)
        .where(EngineerAssessment.case_id == case_id)
        .options(selectinload(EngineerAssessment.operations))
        .order_by(EngineerAssessment.created_at, EngineerAssessment.id)
    ).all()
    invoices = session.scalars(
        select(Invoice)
        .where(Invoice.case_id == case_id)
        .options(selectinload(Invoice.vehicle), selectinload(Invoice.line_items))
    ).all()

    operation_ids = [
        operation.id for assessment in assessments for operation in assessment.operations
    ]
    if operation_ids:
        session.execute(
            delete(AssessmentInvoiceVariance).where(
                AssessmentInvoiceVariance.assessment_operation_id.in_(operation_ids)
            )
        )

    assessment_documents = {assessment.document_id for assessment in assessments}
    for invoice in invoices:
        _revert_assessment_fills(invoice, assessment_documents)
    printed = {invoice.id: _printed_identity(invoice) for invoice in invoices}

    decisions = [
        _select_invoice(assessment, list(invoices), printed) for assessment in assessments
    ]
    _resolve_contention(decisions)

    for decision in decisions:
        assessment = decision.assessment
        assessment.paired_invoice_id = decision.invoice.id if decision.invoice else None
        assessment.pair_status = "paired" if decision.invoice else "unpaired"
        assessment.pair_confidence = decision.confidence
        assessment.pair_reasons_json = decision.reasons
        if decision.invoice is None:
            continue
        _fill_invoice_gaps(decision.invoice, assessment)
        _record_variances(session, assessment, decision.invoice)


def run_case_gap_fill(session: Session, case_id: str) -> None:
    """Re-pair every assessment in a case once all of its documents are loaded.

    ``process_document`` already pairs after each upload, but an assessment
    that arrives last can only fill the invoice it arrives after.  This is the
    "after all documents are loaded" sweep the spec asks for; it is idempotent
    because the fill reverses its own earlier fills before re-evaluating.
    """

    pair_case_assessments(session, case_id)


def _decimal(value: str | None) -> Decimal | None:
    return None if value in (None, "") else Decimal(value)


def _section_categories(line_item_type: str) -> tuple[str, ...]:
    """Assessment operation categories that make up one invoice section.

    Only a section total that resolves to an assessment total gets a
    breakdown.  Falling back to the section's own code for anything else made
    an unresolved "Total ..." heading (``line_item_type == "unknown"``) scoop
    up every operation the parser could not categorise -- a different set of
    rows that merely shares a name.
    """

    if line_item_type in SECTION_OPERATION_CATEGORIES:
        return SECTION_OPERATION_CATEGORIES[line_item_type]
    if line_item_type in SECTION_TOTAL_FIELDS:
        return (line_item_type,)
    return ()


def section_breakdown_for_invoice(
    session: Session,
    invoice: Invoice,
    assessment: EngineerAssessment | None = None,
) -> list[dict]:
    """Resolve each rolled-up invoice total to its assessment section.

    Computed at read time and persisted nowhere.  A difference is *reported*,
    never enforced: nothing here raises, changes a queue or blocks pricing.
    An assessment that does not print a section total leaves ``matches`` as
    ``None`` -- "not captured" is not the same answer as "does not match".

    ``difference`` is ``invoice_total - assessment_total`` throughout, so a
    positive figure means the repairer billed more than the engineer assessed.
    ``rows_total`` sums the breakdown rows beside ``assessment_total`` because
    the two can disagree: format 2's ``labour_net`` is panel labour only, so
    the invoice's "Total Labour" pays for work the report's rows never price,
    and that gap is only visible with both numbers printed.
    ``breakdown_available`` says whether there are any rows to show at all.

    Pass ``assessment`` when the caller already holds it.  Only when it is
    omitted is the paired assessment looked up, and that query returns an
    arbitrary row if two assessments somehow point at one invoice.
    """

    if assessment is None:
        assessment = session.scalar(
            select(EngineerAssessment)
            .where(EngineerAssessment.paired_invoice_id == invoice.id)
            .options(selectinload(EngineerAssessment.operations))
        )
    totals = session.scalars(
        select(InvoiceLineItem)
        .where(
            InvoiceLineItem.invoice_id == invoice.id,
            InvoiceLineItem.is_section_total.is_(True),
        )
        .order_by(InvoiceLineItem.sequence_no)
    ).all()

    breakdowns: list[dict] = []
    for line in totals:
        line_item_type = line.line_item_type or ensure_line_item_type(line.raw_category)
        billed = _decimal(line.line_total_net)
        section_field = SECTION_TOTAL_FIELDS.get(line_item_type)
        assessed = (
            _decimal(getattr(assessment, section_field, None))
            if assessment is not None and section_field
            else None
        )
        difference = billed - assessed if billed is not None and assessed is not None else None
        categories = _section_categories(line_item_type)
        rows = [
            {
                "id": operation.id,
                "category": operation.category,
                "raw_category": operation.raw_category,
                "description": operation.raw_description,
                "work_units": operation.work_units,
                "hours": operation.hours,
                "unit_price_net": operation.unit_price_net,
                "total_net": operation.total_net,
            }
            for operation in (assessment.operations if assessment is not None else [])
            if categories and operation.category in categories
        ]
        rows_total = sum(
            (_decimal(row["total_net"]) or Decimal("0") for row in rows), Decimal("0")
        )
        breakdowns.append(
            {
                "invoice_line_item_id": line.id,
                "line_item_type": line_item_type,
                "raw_category": line.raw_category,
                "description": line.raw_description,
                "invoice_total": line.line_total_net,
                "assessment_id": assessment.id if assessment is not None else None,
                "assessment_total": (
                    getattr(assessment, section_field, None)
                    if assessment is not None and section_field
                    else None
                ),
                "matches": (
                    None if difference is None else abs(difference) <= SECTION_TOTAL_TOLERANCE
                ),
                "difference": None if difference is None else f"{difference:.2f}",
                "difference_convention": DIFFERENCE_CONVENTION,
                "breakdown_source": "engineer assessment",
                "breakdown_available": bool(rows),
                "rows_total": f"{rows_total:.2f}" if rows else None,
                "rows": rows,
            }
        )
    return breakdowns


def engineer_assessment_payload(
    assessment: EngineerAssessment, session: Session | None = None
) -> dict:
    session = session or object_session(assessment)
    invoice = assessment.paired_invoice
    return {
        "id": assessment.id,
        "document_id": assessment.document_id,
        "assessment_number": assessment.assessment_number,
        "claim_reference": assessment.claim_reference,
        "registration": assessment.registration,
        "vehicle_make": assessment.vehicle_make,
        "vehicle_model": assessment.vehicle_model,
        "vin": assessment.vin,
        "mileage": assessment.mileage,
        "field_sources": (
            (invoice.document.metadata_json or {}).get("field_sources", {})
            if invoice else {}
        ),
        "section_breakdowns": (
            # The caller already holds the assessment, so the breakdown never
            # re-queries for "an" assessment paired to this invoice.
            section_breakdown_for_invoice(session, invoice, assessment)
            if invoice is not None and session is not None
            else []
        ),
        "pair_status": assessment.pair_status,
        "pair_confidence": assessment.pair_confidence,
        "pair_reasons": assessment.pair_reasons_json or [],
        # The per-key detail behind the link, kept out of ``pair_reasons`` so
        # the review screen's "paired ... using <reasons>" sentence never
        # reads back an absent or conflicting key as a justification.  Each
        # entry carries ``state`` (matched / conflict / not_compared),
        # ``compared``, ``absent_on`` and both printed values alongside the
        # ``text`` the screens render, so a key skipped for absence can be
        # shown as skipped rather than as a silent failure to match.
        "pair_key_verdicts": (
            [
                verdict.as_payload()
                for verdict in _compare_pair_keys(assessment, _printed_identity(invoice))
            ]
            if invoice is not None
            else []
        ),
        "paired_invoice_id": assessment.paired_invoice_id,
        "totals": {
            "labour_net": assessment.labour_net,
            "paint_net": assessment.paint_net,
            "parts_net": assessment.parts_net,
            "extras_net": assessment.extras_net,
            "subtotal_net": assessment.subtotal_net,
            "vat_total": assessment.vat_total,
            "gross_total": assessment.gross_total,
        },
        "operations": [
            {
                "id": operation.id,
                "category": operation.category,
                "code": operation.operation_code,
                "description": operation.raw_description,
                "total_net": operation.total_net,
                "source_page_id": operation.source_page_id,
                "variances": [
                    {
                        "invoice_id": variance.invoice_id,
                        "invoice_line_item_id": variance.invoice_line_item_id,
                        "engineer_amount": variance.engineer_amount,
                        "invoice_amount": variance.invoice_amount,
                        "difference_amount": variance.difference_amount,
                        "difference_percentage": variance.difference_percentage,
                        "threshold_status": variance.threshold_status,
                        "explanation": variance.explanation,
                    }
                    for variance in operation.variances
                ],
            }
            for operation in assessment.operations
        ],
    }
