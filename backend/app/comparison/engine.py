from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal

from app.domain.money import ZERO, as_decimal, calculate_challenge, money
from app.domain.normalisation import normalise_description, normalise_unit

from .history import historical_statistics
from .models import (
    BenchmarkSource,
    ChallengeSeverity,
    ComparisonPolicy,
    CurrentInvoiceLine,
    ExpectedLineAmount,
    HistoryObservation,
    InvoiceChallengeSummary,
    LineComparison,
    OntologyPriceEvidence,
)
from .scoring import challenge_score

_ONCE_SCOPES = {"job", "test", "set"}
_MULTIPLIED_SCOPES = {"each", "litre", "hour"}


def expected_line_amount(
    *,
    price_net: Decimal,
    price_scope: str,
    invoice_quantity: Decimal | None,
    invoice_unit: str | None,
) -> ExpectedLineAmount:
    """Expand an ontology price only where quantity and scope are known.

    A job, test or set price applies once. Each, litre and hour prices are
    multiplied only when both the compatible unit and a positive quantity are
    explicit. Unknown or incompatible inputs are review work, never guesses.
    """

    amount = money(price_net)
    scope = (price_scope or "").strip().lower()
    if amount is None or amount < 0:
        return ExpectedLineAmount(None, True, ("INVALID_ONTOLOGY_PRICE",))
    if scope in _ONCE_SCOPES:
        return ExpectedLineAmount(amount, False)
    if scope not in _MULTIPLIED_SCOPES:
        return ExpectedLineAmount(None, True, ("UNSUPPORTED_PRICE_SCOPE",))
    if invoice_quantity is None:
        return ExpectedLineAmount(None, True, ("EXPECTED_QUANTITY_UNKNOWN",))
    quantity = as_decimal(invoice_quantity)
    if quantity is None or quantity <= 0:
        return ExpectedLineAmount(None, True, ("EXPECTED_QUANTITY_INVALID",))
    if invoice_unit is None or not invoice_unit.strip():
        return ExpectedLineAmount(None, True, ("INVOICE_UNIT_UNKNOWN",))
    actual_unit = normalise_unit(invoice_unit)
    if actual_unit != scope:
        return ExpectedLineAmount(
            None,
            True,
            (f"UNIT_MISMATCH:{actual_unit or 'unknown'}!={scope}",),
        )
    return ExpectedLineAmount(money(amount * quantity), False)


def _is_mot(line: CurrentInvoiceLine) -> bool:
    return line.is_mot or bool(re.search(r"\bmot\b", normalise_description(line.description)))


def _difference(invoice_price: Decimal, evidence_price: Decimal | None) -> Decimal | None:
    if evidence_price is None:
        return None
    return money(invoice_price - evidence_price)


def _lineage_independence(
    ontology: OntologyPriceEvidence | None,
    history_lineage_ids: tuple[str, ...],
) -> tuple[bool, bool, str, tuple[str, ...]]:
    ontology_lineage = ontology.source_lineage_id if ontology else None
    all_lineage_ids = tuple(
        sorted({lineage for lineage in (ontology_lineage, *history_lineage_ids) if lineage})
    )
    if ontology is None or not history_lineage_ids:
        return False, False, "Only one benchmark source has lineage.", all_lineage_ids
    if ontology_lineage is None:
        return False, False, "Ontology lineage is unknown.", all_lineage_ids
    independent = ontology_lineage not in set(history_lineage_ids)
    if independent:
        return True, True, "Ontology and history use distinct source lineages.", all_lineage_ids
    return False, True, "Ontology and history share a source lineage.", all_lineage_ids


def _source_agreement(
    ontology_net: Decimal | None,
    history_net: Decimal | None,
    *,
    independent: bool,
) -> Decimal:
    if not independent or ontology_net is None or history_net is None:
        return Decimal("0")
    denominator = max(ontology_net, history_net)
    if denominator <= 0:
        return Decimal("0")
    return max(
        Decimal("0"),
        Decimal("1") - (abs(ontology_net - history_net) / denominator),
    )


def _validate_policy(policy: ComparisonPolicy) -> None:
    if policy.ontology_weight < 0 or policy.history_weight < 0:
        raise ValueError("benchmark weights cannot be negative")
    if policy.ontology_weight + policy.history_weight != Decimal("1"):
        raise ValueError("ontology and history weights must sum to 1")
    if policy.minimum_history_count < 1:
        raise ValueError("minimum_history_count must be at least 1")


def _requires_review(flags: tuple[str, ...]) -> bool:
    """Weak history is informational when approved ontology safely takes over."""

    return any(flag != "HISTORY_SAMPLE_WEAK" for flag in flags)


def compare_line(
    *,
    line: CurrentInvoiceLine,
    ontology: OntologyPriceEvidence | None,
    history_observations: Iterable[HistoryObservation] = (),
    mapping_confidence: Decimal = Decimal("0"),
    price_evidence_confidence: Decimal = Decimal("0"),
    fit_confidence: Decimal = Decimal("1"),
    recency_confidence: Decimal = Decimal("1"),
    penalty_points: Decimal = Decimal("0"),
    policy: ComparisonPolicy | None = None,
) -> LineComparison:
    """Compare a quantity-adjusted invoice net line using v1.4 policy."""

    policy = policy or ComparisonPolicy()
    _validate_policy(policy)
    invoice_price = money(line.invoice_line_net) or ZERO
    history = historical_statistics(
        history_observations,
        as_of_date=line.invoice_date,
        minimum_count=policy.minimum_history_count,
        half_life_days=policy.history_half_life_days,
    )

    flags: list[str] = []
    expected = ExpectedLineAmount(None, False)
    ontology_expected: Decimal | None = None
    ontology_reliable = False
    if ontology is not None:
        expected = expected_line_amount(
            price_net=ontology.amount_net,
            price_scope=ontology.price_scope,
            invoice_quantity=line.quantity,
            invoice_unit=line.unit,
        )
        ontology_expected = expected.expected_line_net
        flags.extend(expected.review_flags)
        ontology_reliable = (
            ontology.approved
            and ontology.reliable
            and ontology_expected is not None
            and not expected.requires_review
        )
        if not ontology.approved:
            flags.append("ONTOLOGY_EVIDENCE_NOT_APPROVED")
        elif not ontology.reliable:
            flags.append("ONTOLOGY_EVIDENCE_UNRELIABLE")

    history_expected = history.weighted_median_line_net
    history_reliable = (
        history_expected is not None and history.eligible_count >= policy.minimum_history_count
    )
    if history.eligible_count and history.weak_sample:
        flags.append("HISTORY_SAMPLE_WEAK")

    quantity_comparability_failed = any(
        flag.startswith(("EXPECTED_QUANTITY_", "INVOICE_UNIT_", "UNIT_MISMATCH"))
        for flag in expected.review_flags
    )
    if quantity_comparability_failed:
        history_reliable = False
        flags.append("HISTORY_QUANTITY_NOT_VERIFIABLE")

    (
        sources_independent,
        independence_known,
        lineage_note,
        lineage_ids,
    ) = _lineage_independence(ontology, history.source_lineage_ids)
    if independence_known and not sources_independent:
        flags.append("SOURCE_LINEAGE_NOT_INDEPENDENT")

    benchmark: Decimal | None = None
    benchmark_source = BenchmarkSource.NONE
    benchmark_formula = "no reliable approved benchmark"
    if ontology_reliable and history_reliable:
        benchmark = money(
            ontology_expected * policy.ontology_weight + history_expected * policy.history_weight
        )
        benchmark_source = BenchmarkSource.WEIGHTED_CONSENSUS
        benchmark_formula = (
            f"{policy.ontology_weight} × ontology + "
            f"{policy.history_weight} × historical weighted median"
        )
    elif ontology_reliable:
        benchmark = ontology_expected
        benchmark_source = BenchmarkSource.ONTOLOGY
        benchmark_formula = "100% approved ontology (history weak or ineligible)"
    elif history_reliable and policy.allow_history_without_ontology:
        benchmark = history_expected
        benchmark_source = BenchmarkSource.HISTORY
        benchmark_formula = "100% eligible historical weighted median"
        flags.append("HISTORY_ONLY_REVIEW_REQUIRED")
    else:
        flags.append("NO_RELIABLE_APPROVED_BENCHMARK")

    if benchmark is not None and policy.benchmark_floor_net is not None:
        floor = money(policy.benchmark_floor_net) or ZERO
        if benchmark < floor:
            benchmark = floor
            benchmark_formula += f"; floor £{floor:.2f} applied"

    benchmark_for_math = benchmark if benchmark is not None else invoice_price
    amounts = calculate_challenge(
        invoice_line_net=invoice_price,
        benchmark_line_net=benchmark_for_math,
        vat_rate=line.vat_rate,
        vat_applicable=line.vat_applicable and not _is_mot(line),
        minimum_amount=policy.minimum_challenge_amount,
        minimum_percent=policy.minimum_challenge_percent,
    )

    if not amounts.gate_passed:
        severity = ChallengeSeverity.NEUTRAL
    elif (
        amounts.challenge_net >= policy.red_amount
        or amounts.challenge_percentage >= policy.red_percent
    ):
        severity = ChallengeSeverity.RED
    else:
        severity = ChallengeSeverity.AMBER

    history_strength = min(
        Decimal(history.eligible_count) / Decimal(max(policy.strong_history_count, 1)),
        Decimal("1"),
    )
    agreement = _source_agreement(
        ontology_expected,
        history_expected,
        independent=sources_independent,
    )
    score = challenge_score(
        mapping_confidence=mapping_confidence,
        price_evidence_confidence=price_evidence_confidence,
        fit_confidence=fit_confidence,
        history_sample_strength=history_strength,
        recency_confidence=recency_confidence,
        independent_source_agreement=agreement,
        sources_independent=sources_independent,
        penalty_points=penalty_points,
    )

    review_flags = tuple(dict.fromkeys(flags))
    return LineComparison(
        line_id=line.line_id,
        policy_version=policy.version,
        invoice_price_net=invoice_price,
        ontology_expected_net=ontology_expected,
        historical_expected_net=history_expected,
        difference_from_ontology_net=_difference(invoice_price, ontology_expected),
        difference_from_history_net=_difference(invoice_price, history_expected),
        selected_benchmark_net=benchmark,
        benchmark_source=benchmark_source,
        benchmark_formula=benchmark_formula,
        challenge_price_net=amounts.challenge_price_net,
        challenge_amount_net=amounts.challenge_net,
        challenge_percentage=amounts.challenge_percentage,
        vat_impact=amounts.vat_impact,
        challenge_gross=amounts.challenge_gross,
        gate_passed=amounts.gate_passed,
        severity=severity,
        mapping_confidence=min(max(as_decimal(mapping_confidence) or ZERO, ZERO), Decimal("1")),
        price_evidence_confidence=min(
            max(as_decimal(price_evidence_confidence) or ZERO, ZERO), Decimal("1")
        ),
        challenge_score=score.score,
        challenge_score_label=score.label,
        ontology_reliable=ontology_reliable,
        history_reliable=history_reliable,
        sources_independent=sources_independent,
        source_lineage_independence_known=independence_known,
        source_lineage_note=lineage_note,
        source_lineage_ids=lineage_ids,
        history=history,
        review_required=_requires_review(review_flags),
        review_flags=review_flags,
    )


def aggregate_challenges(
    comparisons: Iterable[LineComparison],
) -> InvoiceChallengeSummary:
    """Sum positive gated challenges; underpriced lines can never offset them."""

    rows = tuple(comparisons)
    invoice_price = money(sum((row.invoice_price_net for row in rows), Decimal("0"))) or ZERO
    challenge_net = (
        money(sum((max(row.challenge_amount_net, ZERO) for row in rows), Decimal("0"))) or ZERO
    )
    vat_impact = money(sum((max(row.vat_impact, ZERO) for row in rows), Decimal("0"))) or ZERO
    severity_counts = {
        severity.value: sum(row.severity == severity for row in rows)
        for severity in ChallengeSeverity
    }
    return InvoiceChallengeSummary(
        invoice_price_net=invoice_price,
        challenge_price_net=money(invoice_price - challenge_net) or ZERO,
        challenge_amount_net=challenge_net,
        vat_impact=vat_impact,
        challenge_gross=money(challenge_net + vat_impact) or ZERO,
        challenged_line_count=sum(row.gate_passed for row in rows),
        severity_counts=severity_counts,
    )
