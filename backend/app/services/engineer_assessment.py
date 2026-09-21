"""Pair Engineer Assessments with invoices and persist explainable variances."""

from __future__ import annotations

import dataclasses
import re
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session, selectinload

from app.domain.line_item_type import ensure_line_item_type
from app.domain.normalisation import normalise_identifier
from app.enums import AuditActorType
from app.models import (
    AssessmentInvoiceVariance,
    AuditEvent,
    Case,
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

#: One invoice cannot be two claims' invoice: nothing is linked and nothing
#: is filled until a handler says which.
AMBIGUOUS_INVOICES_REASON = (
    "Multiple invoices share the same identifiers; manual linkage required"
)

#: The three ways an invoice claimed by two assessments can end.  They are
#: worded apart because they are different facts about the paperwork and a
#: handler resolves them differently: one report was uploaded twice, two
#: different reports fit the invoice equally well, or one report fits it
#: better than this one.  A single "share the same identifiers" sentence was
#: used for all of them and was untrue of every case but the first.
DUPLICATE_ASSESSMENT_REASON = (
    "The same assessment identity was uploaded more than once; the earliest "
    "copy keeps the link and manual linkage is required for this one"
)
CONTESTED_ASSESSMENTS_REASON = (
    "Two assessments agree with this invoice equally well; manual linkage required"
)
OUTRANKED_ASSESSMENT_REASON = (
    "Another assessment agrees with this invoice on more printed identities; "
    "manual linkage required"
)
NO_SHARED_IDENTIFIER_REASON = (
    "No invoice shares a printed registration, claim reference or policy number "
    "with this assessment"
)
EXPLICIT_LINK_REASON = "Uploaded together for this invoice"

#: How a link came about.  ``pair_source`` carries this onto the row and onto
#: every payload built from it, so a screen never has to infer whether a
#: person or the rule chose a pair.
PAIR_SOURCE_AUTOMATIC = "automatic"
PAIR_SOURCE_MANUAL = "manual"

UNMATCHED_INVOICE_MANUAL_REVIEW_REASON = (
    "This invoice is not mapped to an engineer assessment; manual review is required."
)

#: The handler's standing instruction, as stored in ``manual_pair_state``.
#: ``None`` is the third state and means "the handler has said nothing"; it is
#: not the same as ``MANUAL_STATE_CLEARED``, which is a person saying this
#: assessment pairs with no invoice at all.  Collapsing the two would let the
#: next upload re-link something a handler had deliberately unlinked.
MANUAL_STATE_LINKED = "linked"
MANUAL_STATE_CLEARED = "cleared"

MANUAL_LINK_REASON = "Linked to this invoice by hand by the claims handler"
MANUAL_CLEAR_REASON = "Unlinked by hand by the claims handler"
#: A handler's link takes the invoice off every automatic claimant: the rule
#: refuses to guess, and a person who has said which report belongs to this
#: invoice has answered the question the rule could not.
MANUAL_OUTRANKS_REASON = (
    "A handler linked another assessment to this invoice by hand; "
    "manual linkage required for this one"
)
#: Two handler links on one invoice cannot both stand.  The API refuses to
#: create this, so reaching it means the rows were written another way; the
#: earliest instruction keeps the invoice and the later one is reported rather
#: than silently applied.
MANUAL_CONTESTED_REASON = (
    "Two assessments are linked to this invoice by hand; the earlier link "
    "stands and this one must be re-pointed"
)
#: The invoice a handler chose is no longer in the case (it was deleted, and
#: the foreign key nulled the choice).  The instruction cannot be carried out,
#: so the rule decides again and the stale override stays visible on the
#: payload for the handler to re-take.
MANUAL_STALE_REASON = (
    "The invoice a handler linked this assessment to is no longer in this claim"
)

#: Substring that marks a per-key verdict as a disagreement rather than an
#: absence.  Only a disagreement blocks a link.
CONFLICT_MARKER = " conflict: "

#: The states a pairing key can be in.  Only ``MATCHED`` and ``CONFLICT`` are
#: *compared*: the client's rule is "match what is there", so a key one
#: document does not usefully print carries no information about the pair at
#: all.  ``NOT_COMPARED`` and ``PLACEHOLDER`` are both "not compared", kept
#: apart because a reader has to be able to tell an empty box ("not printed")
#: from a filled-in one that identifies nothing ("printed but meaningless").
KEY_MATCHED = "matched"
KEY_CONFLICT = "conflict"
KEY_NOT_COMPARED = "not_compared"
KEY_PLACEHOLDER = "placeholder"

#: What a printed token has to clear before it is allowed to be *comparable*:
#: it must not be one of the things a form prints where an identity is
#: unknown, and it must be long enough to single out one claim.
#:
#: Demoting a token to "not printed" is deliberately the safe direction.
#: Absence is neutral under the client's rule -- it neither links a pair nor
#: blocks one -- so the worst a false demotion can do is leave a pair for a
#: handler to make by hand.  Believing the token is the unsafe direction:
#: format 1's assessment prints the policy number "PH", and before this floor
#: existed two unrelated documents both printing "PH" agreed on a key, linked
#: at confidence 1.0, and let the assessment's claim reference, policy number
#: and vehicle identity be gap-filled onto somebody else's invoice.  Worse, a
#: placeholder could make the *wrong* invoice outrank the right one, because
#: agreeing on two keys beats agreeing on one.
#:
#: A demoted key is therefore never a match and never a conflict -- it is
#: reported as ``KEY_PLACEHOLDER``, which is not compared.
#:
#: This lives here rather than in ``normalise_identifier`` on purpose: it is a
#: pairing judgement, not a normalisation one.  ``vehicle_classification``
#: normalises registrations through the same function and must keep every
#: value it is handed.
IDENTIFIER_PLACEHOLDERS = frozenset(
    {
        "PH",
        "N/A",
        "NA",
        "N/K",
        "NK",
        "NONE",
        "NIL",
        "TBC",
        "TBA",
        "TBD",
        "UNKNOWN",
        "X",
        "XX",
        "XXX",
        "XXXX",
        "0",
        "00",
        "000",
        "0000",
    }
)

#: Fewer alphanumeric characters than this cannot pick one claim out of a book
#: of them, whatever the token spells.  The shortest real identifier in the
#: corpus is a seven-character registration.
MINIMUM_IDENTIFIER_LENGTH = 4

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


def _comparable_identifier(value: str | None) -> tuple[str | None, str | None]:
    """Split a printed identifier into "what to compare" and "what was printed".

    Returns ``(comparable, printed)``.  ``comparable`` is the value the pairing
    rule may compare and is ``None`` in two different situations: the document
    printed nothing, or it printed something that cannot identify a claim (see
    ``IDENTIFIER_PLACEHOLDERS``).  ``printed`` is what tells the two apart --
    the normalised token the document carried, ``None`` only when there was
    none.  The second case is a placeholder, and the caller reports it as one.
    """

    normalised = normalise_identifier(value)
    if normalised is None:
        return None, None
    alphanumeric = sum(1 for character in normalised if character.isalnum())
    if normalised in IDENTIFIER_PLACEHOLDERS or alphanumeric < MINIMUM_IDENTIFIER_LENGTH:
        return None, normalised
    return normalised, normalised


def _side(sides: tuple[str, ...]) -> str | None:
    """Name the document(s) a fact is true of, in the ``absent_on`` vocabulary."""

    if not sides:
        return None
    return "both" if len(sides) == 2 else sides[0]


@dataclasses.dataclass(frozen=True)
class _KeyVerdict:
    """One pairing key's outcome, in the four states the UI has to show.

    ``text`` is the sentence the review screens already render; the machine
    readable fields beside it are what let a screen colour a conflict red and
    a skipped key grey without parsing prose -- and say, of a skipped key,
    whether the document left the box empty or filled it with "N/A".
    """

    key: str
    label: str
    state: str
    text: str
    #: ``"invoice"``, ``"assessment"`` or ``"both"`` for the document(s) that
    #: printed nothing for this key; ``None`` when both printed something.
    absent_on: str | None = None
    #: ``"invoice"``, ``"assessment"`` or ``"both"`` for the document(s) that
    #: printed a placeholder instead of an identity; ``None`` otherwise.  The
    #: two fields are independent facts and can both be set: format 1's
    #: assessment prints "PH" for a policy number its invoice does not print
    #: at all.
    placeholder_on: str | None = None
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
            "placeholder_on": self.placeholder_on,
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

    "Printed" means "printed something that identifies a claim".  A
    placeholder -- "PH", "N/A", "TBC" -- is demoted to not-printed rather than
    compared, because a token every claim's paperwork can carry is evidence
    about neither this pair nor any other; see ``IDENTIFIER_PLACEHOLDERS`` for
    why demotion is the safe direction.
    """

    verdicts: list[_KeyVerdict] = []
    for key, label in PAIR_KEYS:
        assessment_value = getattr(assessment, key, None)
        invoice_value = printed.get(key)
        left, left_printed = _comparable_identifier(assessment_value)
        right, right_printed = _comparable_identifier(invoice_value)
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
        sides = (("assessment", left, left_printed), ("invoice", right, right_printed))
        absent_on = _side(tuple(side for side, _, token in sides if token is None))
        placeholders = tuple(
            (side, token) for side, comparable, token in sides
            if comparable is None and token is not None
        )
        placeholder_on = _side(tuple(side for side, _ in placeholders))
        if placeholder_on is None:
            text = {
                "invoice": f"{label} not printed on the invoice",
                "assessment": f"{label} not printed on the assessment",
                "both": f"{label} not printed on either document",
            }[absent_on]
            state = KEY_NOT_COMPARED
        else:
            tokens = " and ".join(
                dict.fromkeys(token for _, token in placeholders)
            )
            where = (
                "both documents" if placeholder_on == "both" else f"the {placeholder_on}"
            )
            text = f"{label} is a placeholder on {where} ({tokens})"
            state = KEY_PLACEHOLDER
        verdicts.append(
            _KeyVerdict(
                state=state,
                text=text,
                absent_on=absent_on,
                placeholder_on=placeholder_on,
                **common,
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

    Each skipped key states its own verdict rather than being folded into one
    "not printed on both documents" clause, which was false whenever only one
    side was missing the key -- and one side missing it is the common case.
    """

    compared = [verdict for verdict in verdicts if verdict.compared]
    if len(compared) != 1:
        return None
    skipped = [verdict.text for verdict in verdicts if not verdict.compared]
    return (
        f"{WEAK_PAIR_PREFIX}only the {compared[0].label} was comparable; "
        + "; ".join(skipped)
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
    #: ``None`` on a handler's decision.  Confidence is the share of the
    #: comparable printed identities that agree -- a property of the rule.  A
    #: person who has read both documents is not 100% confident, they are
    #: simply right, and printing a number beside their name would invite a
    #: reader to compare it with the rule's.
    confidence: float | None = 0.0
    reasons: list[str] = dataclasses.field(default_factory=list)
    #: How many pairing keys actually agreed.  ``_Candidate.strength`` ranks
    #: invoices within one assessment; this is the same evidence carried out
    #: of the choice so ``_resolve_contention`` can rank *assessments* against
    #: each other when two of them reach for one invoice.  ``0`` is a link
    #: that rests on an explicit upload association alone.
    matched_keys: int = 0
    #: True when this decision is the handler's, not the rule's.  It becomes
    #: ``pair_source`` on the row.  Kept last and never passed positionally:
    #: ``_select_invoice`` builds a ``_Decision`` with positional arguments,
    #: so a field inserted above ``matched_keys`` silently takes its value.
    manual: bool = False

    def reject(self, reason: str) -> None:
        self.invoice = None
        self.confidence = 0.0
        self.reasons = [reason]
        self.matched_keys = 0
        # ``pair_source`` describes how the *outcome* was reached, and this
        # outcome was reached by the contention rule.  A handler's link that
        # lost to another handler's link is not a handler's outcome; the
        # instruction stays on ``manual_pair_state`` for the screen to show.
        self.manual = False


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
    stays.  Four things contain it: a candidate that agrees on more keys
    always outranks one that agrees on fewer (``_Candidate.strength``), two
    assessments fitting one invoice equally well leave it unlinked rather than
    racing for it (``_resolve_contention``), a token that identifies nothing
    is never one of those agreeing keys (``IDENTIFIER_PLACEHOLDERS``), and a
    one-key link says so in its reasons (``_weak_pair_reason``).
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
    # ``rejected`` is deliberately not sorted: a rejected candidate matched no
    # key and had no conflict, so its confidence is 0/compared and its
    # strength is always ``(0, 0.0)``.  Sorting a list whose every key is
    # equal decided nothing; the invoices arrive in a stable order
    # (``pair_case_assessments`` orders the query), which is what actually
    # makes the fallback reason below reproducible.
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
        return _Decision(
            assessment,
            chosen.invoice,
            min(chosen.confidence, 1.0),
            reasons,
            len(chosen.matched),
        )

    if ambiguous:
        return _Decision(assessment, None, 0.0, [AMBIGUOUS_INVOICES_REASON])
    fallback = next(iter(rejected or conflicting), None)
    if fallback is None:
        return _Decision(assessment, None, 0.0, [NO_SHARED_IDENTIFIER_REASON])
    conflicts = [
        verdict.text for verdict in fallback.verdicts if verdict.state == KEY_CONFLICT
    ]
    return _Decision(assessment, None, 0.0, conflicts or [NO_SHARED_IDENTIFIER_REASON])


def _apply_manual_overrides(
    decisions: list[_Decision], invoices: dict[str, Invoice]
) -> None:
    """Let the handler's standing instruction replace the rule's proposal.

    This is the answer to the sharpest problem in the manual-linkage feature:
    ``pair_case_assessments`` re-decides every link from scratch on every
    document upload, so a link written into ``paired_invoice_id`` by a person
    would be silently thrown away by the next file to arrive.

    The fix is not to make the pass skip overridden assessments -- it cannot,
    because the pass also reverts and re-applies every gap-fill in the case,
    and skipping an assessment would leave its fills reverted.  The fix is to
    keep the *decision* and the *outcome* in different places.  The rule owns
    ``paired_invoice_id``; the handler owns ``manual_pair_*``.  Every pass
    re-runs the rule in full and is then overruled here, so a manual link is
    re-applied by the very pass that would have overwritten it, and its
    gap-fill is re-applied with it.  The instruction is durable; the outcome
    is always freshly computed from it.

    Three states, and the third is the one that is easy to miss.  ``None`` is
    "the handler has said nothing" and leaves the rule's proposal alone.
    ``linked`` points at an invoice.  ``cleared`` is a person saying this
    assessment pairs with nothing -- which must be recorded, because
    collapsing it into "no instruction" would let the next upload re-propose
    exactly the link the handler had just removed.
    """

    for decision in decisions:
        assessment = decision.assessment
        state = assessment.manual_pair_state
        if state is None:
            continue
        if state == MANUAL_STATE_CLEARED:
            decision.invoice = None
            decision.confidence = None
            decision.reasons = [MANUAL_CLEAR_REASON]
            decision.matched_keys = 0
            decision.manual = True
            continue
        invoice = invoices.get(assessment.manual_pair_invoice_id or "")
        if invoice is None:
            # The chosen invoice has left the case and the foreign key nulled
            # the choice with it.  An instruction that cannot be carried out
            # is not carried out: the rule's proposal stands, the stale
            # override stays on the row, and the payload says so, so the
            # handler is asked again rather than told something untrue.
            decision.reasons = [*decision.reasons, MANUAL_STALE_REASON]
            continue
        decision.invoice = invoice
        decision.confidence = None
        decision.reasons = [MANUAL_LINK_REASON]
        decision.matched_keys = 0
        decision.manual = True


def _resolve_contention(decisions: list[_Decision]) -> None:
    """Decide, or refuse, the invoices two assessments both reach for.

    One invoice belongs to one claim, so at most one assessment may keep the
    link -- but which one is a question of evidence, not of arrival order.  A
    claimant agreeing with the invoice on strictly more printed identities
    than every rival *is* the invoice's assessment, and the rivals are
    refused.  Only a genuine tie is unresolvable, and then nothing is linked
    and nothing is filled.

    Refusing every claimant unconditionally was affordable while a claimant
    had to agree on a registration or a claim reference.  Under "match what is
    there" it is not: an invoice that prints a policy number attracts any
    report sharing it, so a one-key lookalike destroyed three-of-three exact
    pairs -- and told the handler the two assessments "share the same
    identifiers", when the lookalike in fact shared none.

    ``claimants`` is in ``decisions`` order, which ``pair_case_assessments``
    fixes as oldest assessment first, so the duplicate branch below always
    leaves the *first* copy linked.
    """

    by_invoice: dict[str, list[_Decision]] = {}
    for decision in decisions:
        if decision.invoice is not None:
            by_invoice.setdefault(decision.invoice.id, []).append(decision)
    for claimants in by_invoice.values():
        if len(claimants) < 2:
            continue
        manual = [claimant for claimant in claimants if claimant.manual]
        if manual:
            # A handler has said which report this invoice belongs to, which
            # is the question the rule refused to guess at.  Their link takes
            # the invoice off every automatic claimant outright -- ranking a
            # person's decision against printed-key counts would be reasoning
            # about evidence they have already weighed.
            keeper = manual[0]
            for claimant in claimants:
                if claimant is keeper:
                    continue
                claimant.reject(
                    MANUAL_CONTESTED_REASON if claimant.manual else MANUAL_OUTRANKS_REASON
                )
            continue
        if len({_assessment_identity(row.assessment) for row in claimants}) == 1:
            # The same identity uploaded twice: the first report keeps the
            # link, and refusing the duplicate changes nothing on the invoice.
            for duplicate in claimants[1:]:
                duplicate.reject(DUPLICATE_ASSESSMENT_REASON)
            continue
        strongest = max(claimant.matched_keys for claimant in claimants)
        leaders = [
            claimant for claimant in claimants if claimant.matched_keys == strongest
        ]
        if strongest and len(leaders) == 1:
            for claimant in claimants:
                if claimant is not leaders[0]:
                    claimant.reject(OUTRANKED_ASSESSMENT_REASON)
            continue
        # Two different identities that fit equally well cannot both be this
        # invoice's. Linking either would write a claim reference the invoice
        # never printed, so neither is linked and the invoice keeps only what
        # it printed.  ``strongest == 0`` lands here too: claimants holding
        # nothing but an upload association are not ranked against each other.
        for claimant in claimants:
            claimant.reject(CONTESTED_ASSESSMENTS_REASON)


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

    * assessments *and* invoices are read oldest first, so the outcome does
      not depend on the order the database happens to hand rows back -- an
      unpaired assessment's stated reason is read off the first candidate
      invoice, so an unordered query made the sentence vary between runs;
    * every gap-fill any of them made is reverted *before* the first decision,
      and each invoice's printed identity is snapshotted, so no assessment is
      ever judged against another assessment's fill;
    * contention between two assessments reaching for one invoice is resolved
      after all of them have chosen, on the evidence each one holds, not by
      whoever got there first.

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
        .options(
            selectinload(Invoice.vehicle),
            selectinload(Invoice.line_items),
            selectinload(Invoice.document),
        )
        .order_by(Invoice.created_at, Invoice.id)
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
    _apply_manual_overrides(decisions, {invoice.id: invoice for invoice in invoices})
    _resolve_contention(decisions)

    paired_invoice_ids = {
        decision.invoice.id for decision in decisions if decision.invoice is not None
    }
    for invoice in invoices:
        document = invoice.document
        if document is None:
            continue
        metadata = dict(document.metadata_json or {})
        if invoice.id in paired_invoice_ids:
            if metadata.get("manual_review_reason") == UNMATCHED_INVOICE_MANUAL_REVIEW_REASON:
                metadata.pop("manual_review", None)
                metadata.pop("manual_review_reason", None)
        else:
            metadata["manual_review"] = True
            metadata["manual_review_reason"] = UNMATCHED_INVOICE_MANUAL_REVIEW_REASON
        document.metadata_json = metadata

    for decision in decisions:
        assessment = decision.assessment
        assessment.paired_invoice_id = decision.invoice.id if decision.invoice else None
        assessment.pair_status = "paired" if decision.invoice else "unpaired"
        assessment.pair_source = (
            PAIR_SOURCE_MANUAL if decision.manual else PAIR_SOURCE_AUTOMATIC
        )
        assessment.pair_confidence = decision.confidence
        assessment.pair_reasons_json = decision.reasons
        if decision.invoice is None:
            continue
        _fill_invoice_gaps(decision.invoice, assessment)
        _record_variances(session, assessment, decision.invoice)

    _expire_mapping_approval(session, case_id, _pair_map(decisions))
    _expire_group_mapping_approvals(session, case_id, decisions)


def _assessment_intake_group(assessment: EngineerAssessment) -> str | None:
    document = assessment.document
    return (getattr(document, "metadata_json", None) or {}).get("intake_group")


def group_pair_map(
    assessments: list[EngineerAssessment], intake_group: str
) -> dict[str, str | None]:
    """``{assessment id: invoice id or None}`` for one upload source only."""

    return {
        assessment.id: assessment.paired_invoice_id
        for assessment in assessments
        if _assessment_intake_group(assessment) == intake_group
    }


def _expire_group_mapping_approvals(
    session: Session, case_id: str, decisions: list[_Decision]
) -> None:
    """``_expire_mapping_approval``, per upload source.

    Each source's approval is a statement about that source's pairs only, so
    a new Aviva DLG document reopens the Aviva DLG approval and leaves the
    third-party one standing.  Same comparison, same audit trail.
    """

    case = session.get(Case, case_id)
    if case is None or not case.mapping_group_approvals_json:
        return
    pairs = _pair_map(decisions)
    groups = {
        decision.assessment.id: _assessment_intake_group(decision.assessment)
        for decision in decisions
    }
    approvals = dict(case.mapping_group_approvals_json)
    changed = False
    for intake_group, approval in list(approvals.items()):
        current = {
            assessment_id: invoice_id
            for assessment_id, invoice_id in pairs.items()
            if groups.get(assessment_id) == intake_group
        }
        if (approval.get("pairs") or {}) == current:
            continue
        session.add(
            AuditEvent(
                case_id=case.id,
                processing_run_id=case.current_processing_run_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id="claimguard.pairing",
                event_type="CASE_MAPPING_APPROVAL_REOPENED",
                entity_type="case",
                entity_id=case.id,
                before_json={"intake_group": intake_group, **approval},
                after_json={"intake_group": intake_group, "approved": False, "pairs": current},
                event_payload_json={
                    "intake_group": intake_group,
                    "reason": (
                        "The invoice/assessment mapping of this source changed "
                        "after it was approved, so the approval no longer describes it."
                    ),
                },
            )
        )
        del approvals[intake_group]
        changed = True
    if changed:
        case.mapping_group_approvals_json = approvals or None


def _pair_map(decisions: list[_Decision]) -> dict[str, str | None]:
    """``{assessment id: invoice id or None}`` -- the mapping, as a value.

    Approval is recorded against one of these, so the two are compared rather
    than trusted: see ``_expire_mapping_approval``.
    """

    return {
        decision.assessment.id: decision.invoice.id if decision.invoice else None
        for decision in decisions
    }


def _expire_mapping_approval(
    session: Session, case_id: str, pairs: dict[str, str | None]
) -> None:
    """Drop the handler's approval when the mapping it approved has changed.

    "Approved" is a statement about a *particular* set of pairs, not a flag on
    the case, so it cannot be allowed to outlive them.  Every path that can
    change a pair -- a new document, a handler override, a sweep -- runs
    through ``pair_case_assessments``, so this one comparison covers all of
    them without any caller having to remember.

    It is deliberately a comparison and not an unconditional clear: re-running
    the sweep over an unchanged case must not silently un-approve a mapping
    the handler has already signed off, or approval would never survive the
    gap-fill that approval itself triggers.
    """

    case = session.get(Case, case_id)
    if case is None or case.mapping_approved_at is None:
        return
    if (case.mapping_approved_pairs_json or {}) == pairs:
        return
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id="claimguard.pairing",
            event_type="CASE_MAPPING_APPROVAL_REOPENED",
            entity_type="case",
            entity_id=case.id,
            before_json={
                "approved_by": case.mapping_approved_by,
                "approved_at": case.mapping_approved_at.isoformat(),
                "pairs": case.mapping_approved_pairs_json or {},
            },
            after_json={"approved": False, "pairs": pairs},
            event_payload_json={
                "reason": (
                    "The invoice/assessment mapping changed after it was "
                    "approved, so the approval no longer describes it."
                )
            },
        )
    )
    case.mapping_approved_at = None
    case.mapping_approved_by = None
    case.mapping_approved_pairs_json = None


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


def manual_override_payload(assessment: EngineerAssessment) -> dict | None:
    """The handler's standing instruction, or ``None`` when there is none.

    Carried on every payload that carries ``pair_status`` so a screen can tell
    a link a person chose from one the rule proposed -- and can tell an
    instruction that was applied from one that could not be (``applied`` is
    false when the chosen invoice has left the case, or when another handler
    link already holds it).
    """

    state = assessment.manual_pair_state
    if state is None:
        return None
    invoice = assessment.manual_pair_invoice
    return {
        "state": state,
        "invoice_id": assessment.manual_pair_invoice_id,
        "invoice_number": invoice.invoice_number if invoice is not None else None,
        "actor": assessment.manual_pair_actor,
        "at": assessment.manual_pair_at.isoformat() if assessment.manual_pair_at else None,
        "reason": assessment.manual_pair_reason,
        "applied": assessment.pair_source == PAIR_SOURCE_MANUAL,
    }


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
        # "automatic" or "manual": which of the two decided the link that is
        # on the row now.  A handler's link carries no ``pair_confidence`` --
        # confidence is the share of comparable printed identities that agree,
        # which is a property of the rule and not of a person's judgement.
        "pair_source": assessment.pair_source,
        "manual_override": manual_override_payload(assessment),
        "pair_confidence": assessment.pair_confidence,
        "pair_reasons": assessment.pair_reasons_json or [],
        # The per-key detail behind the link, kept out of ``pair_reasons`` so
        # the review screen's "paired ... using <reasons>" sentence never
        # reads back an absent or conflicting key as a justification.  Each
        # entry carries ``state`` (matched / conflict / not_compared /
        # placeholder), ``compared``, ``absent_on``, ``placeholder_on`` and
        # both printed values alongside the ``text`` the screens render, so a
        # key skipped can be shown as skipped -- and shown *why* it was
        # skipped -- rather than as a silent failure to match.
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
