from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.domain.money import as_decimal

from .models import ChallengeScore


def _confidence(value: Decimal | str | int | float) -> Decimal:
    parsed = as_decimal(value) or Decimal("0")
    return min(max(parsed, Decimal("0")), Decimal("1"))


def challenge_score(
    *,
    mapping_confidence: Decimal,
    price_evidence_confidence: Decimal,
    fit_confidence: Decimal,
    history_sample_strength: Decimal,
    recency_confidence: Decimal,
    independent_source_agreement: Decimal,
    sources_independent: bool,
    penalty_points: Decimal = Decimal("0"),
) -> ChallengeScore:
    """Score evidence strength without accepting any financial-magnitude input."""

    mapping_component = _confidence(mapping_confidence) * Decimal("25")
    price_component = _confidence(price_evidence_confidence) * Decimal("25")
    fit_component = _confidence(fit_confidence) * Decimal("15")
    history_component = _confidence(history_sample_strength) * Decimal("15")
    recency_component = _confidence(recency_confidence) * Decimal("10")
    agreement_component = (
        _confidence(independent_source_agreement) * Decimal("10")
        if sources_independent
        else Decimal("0")
    )
    penalties = max(as_decimal(penalty_points) or Decimal("0"), Decimal("0"))
    raw = (
        mapping_component
        + price_component
        + fit_component
        + history_component
        + recency_component
        + agreement_component
        - penalties
    )
    score = min(max(raw, Decimal("0")), Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if score < 40:
        label = "Insufficient"
    elif score < 60:
        label = "Weak"
    elif score < 75:
        label = "Moderate"
    elif score < 90:
        label = "Strong"
    else:
        label = "Very strong"
    return ChallengeScore(
        score=score,
        label=label,
        mapping_component=mapping_component,
        price_evidence_component=price_component,
        fit_component=fit_component,
        history_component=history_component,
        recency_component=recency_component,
        independent_agreement_component=agreement_component,
        penalty_points=penalties,
    )
