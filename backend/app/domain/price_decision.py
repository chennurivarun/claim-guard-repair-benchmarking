"""Server-side unified operational price decision.

This module is the single, pure-function source of truth for the "supported
price" / challenge decision that was previously computed client-side in
JavaScript floats (``src/features/claim-guard/p90-policy.ts``).  It reproduces
that policy exactly, but in ``Decimal`` arithmetic, and additionally emits an
ordered, machine-readable ``calculation`` breakdown so the workspace, the
result graph, and every export can show (and agree on) the same steps.

Persisted comparison-engine rows remain audit detail. This module decides, at
read time, the operational supported price and challenge for every line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.domain.money import ZERO, money, percentage

__all__ = [
    "P90Policy",
    "DEFAULT_POLICY",
    "P90Evidence",
    "LineDecisionInputs",
    "PriceDecision",
    "decide_line_price",
    "resolve_threshold_pct",
]


@dataclass(frozen=True)
class P90Policy:
    """Operational three-source evidence policy."""

    in_house_weight: Decimal = Decimal("0.50")
    historical_weight: Decimal = Decimal("0.30")
    external_weight: Decimal = Decimal("0.20")
    minimum_challenge_amount: Decimal = Decimal("5.00")
    allowed_thresholds: frozenset[int] = field(default_factory=lambda: frozenset({5, 10}))
    default_threshold_pct: int = 10


DEFAULT_POLICY = P90Policy()


def resolve_threshold_pct(
    value: int | str | Decimal | None, policy: P90Policy = DEFAULT_POLICY
) -> Decimal:
    """Validate and normalise a ``p90_threshold_pct`` query/parameter value."""

    if value is None or value == "":
        return Decimal(policy.default_threshold_pct)
    try:
        decimal_value = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - re-raised as a clear ValueError
        raise ValueError(f"Invalid p90_threshold_pct: {value!r}") from exc
    if (
        decimal_value != decimal_value.to_integral_value()
        or int(decimal_value) not in policy.allowed_thresholds
    ):
        allowed = ", ".join(str(item) for item in sorted(policy.allowed_thresholds))
        raise ValueError(f"p90_threshold_pct must be one of: {allowed}")
    return decimal_value


@dataclass(frozen=True)
class P90Evidence:
    """The uploaded-invoice-batch P90 benchmark signal for one line."""

    value: Decimal
    historical_count: int
    method: str
    explanation: str
    contributing_invoices: tuple[str, ...] = ()
    contributing_prices: tuple[Decimal, ...] = ()


@dataclass(frozen=True)
class LineDecisionInputs:
    """Everything ``decide_line_price`` needs for one invoice line."""

    billed_net: Decimal
    p90: P90Evidence | None
    historical: P90Evidence | None
    external_price: Decimal | None
    external_approval_status: str | None
    vat_rate: Decimal
    is_mot: bool
    threshold_pct: Decimal


@dataclass(frozen=True)
class PriceDecision:
    """The unified operational decision for one line."""

    has_signal: bool
    historical_count: int | None
    in_house_price: Decimal | None
    historical_price: Decimal | None
    external_price: Decimal | None
    supported_price: Decimal | None
    challenge_net: Decimal
    challenge_vat: Decimal
    comparison_status: str | None
    rationale: str | None
    evidence_rationale: str | None
    calculation: list[dict[str, Any]]


def _step(step: int, label: str, value: Any, detail: str, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"step": step, "label": label, "value": value, "detail": detail}
    entry.update(extra)
    return entry


def decide_line_price(
    inputs: LineDecisionInputs, policy: P90Policy = DEFAULT_POLICY
) -> PriceDecision:
    """Decide the operational supported price / challenge for one line.

    Pure function, all ``Decimal`` arithmetic.  Mirrors
    ``applyP90PolicyToLine`` in ``src/features/claim-guard/p90-policy.ts``
    exactly, while additionally emitting the C3 structured ``calculation``
    breakdown that the prose rationale is generated from (so they can never
    disagree).
    """

    billed = money(inputs.billed_net) or ZERO
    calculation: list[dict[str, Any]] = [
        _step(1, "Billed net", str(billed), f"Line billed net amount is £{billed:.2f}."),
    ]

    if inputs.p90 is None and inputs.historical is None:
        calculation.append(
            _step(
                2,
                "P90 benchmark",
                None,
                "No verified in-house or historical benchmark is available; "
                "external evidence alone cannot create an automatic challenge.",
            )
        )
        return PriceDecision(
            has_signal=False,
            historical_count=None,
            in_house_price=None,
            historical_price=None,
            external_price=None,
            supported_price=None,
            challenge_net=ZERO,
            challenge_vat=ZERO,
            comparison_status=None,
            rationale=None,
            evidence_rationale=None,
            calculation=calculation,
        )

    in_house_value = money(inputs.p90.value) if inputs.p90 else None
    in_house_count = inputs.p90.historical_count if inputs.p90 else 0
    in_house_refs = (
        ", ".join(inputs.p90.contributing_invoices) or "none recorded" if inputs.p90 else ""
    )
    calculation.append(
        _step(
            2,
            "In-house P90 benchmark",
            str(in_house_value) if in_house_value is not None else None,
            (
                f"{inputs.p90.method}: £{in_house_value:.2f} from {in_house_count} validated "
                f"synthetic in-house price{'' if in_house_count == 1 else 's'} "
                f"({in_house_refs})."
                if inputs.p90 and in_house_value is not None
                else "No eligible synthetic in-house benchmark price is available."
            ),
        )
    )

    historical_value = money(inputs.historical.value) if inputs.historical else None
    historical_count = inputs.historical.historical_count if inputs.historical else 0
    calculation.append(
        _step(
            3,
            "Historical claims P90",
            str(historical_value) if historical_value is not None else None,
            (
                f"{inputs.historical.method}: £{historical_value:.2f} from "
                f"{historical_count} eligible previous claim price"
                f"{'' if historical_count == 1 else 's'}."
                if inputs.historical and historical_value is not None
                else "No eligible previous-claim benchmark is available."
            ),
        )
    )

    external_price = (
        money(inputs.external_price)
        if inputs.external_price is not None and inputs.external_price > ZERO
        else None
    )
    if external_price is not None:
        approval_label = inputs.external_approval_status or "approved"
        calculation.append(
            _step(
                4,
                "External reference price",
                str(external_price),
                f"Verified external reference price £{external_price:.2f} ({approval_label}).",
            )
        )
    else:
        calculation.append(
            _step(
                4,
                "External reference price",
                None,
                "No verified, traceable external reference price is available.",
            )
        )

    sources = [
        ("in-house P90", in_house_value, policy.in_house_weight),
        ("historical claims P90", historical_value, policy.historical_weight),
        ("verified external", external_price, policy.external_weight),
    ]
    available = [(label, value, weight) for label, value, weight in sources if value is not None]
    available_weight = sum((weight for _, _, weight in available), ZERO)
    evidence_price = (
        money(sum((value * weight for _, value, weight in available), ZERO) / available_weight)
        or ZERO
    )
    applied = " / ".join(
        f"{(weight / available_weight * Decimal('100')).quantize(Decimal('1'))}% {label}"
        for label, _, weight in available
    )
    price_explanation = (
        f"Available verified evidence is reweighted proportionally: {applied}. "
        "The full policy is 50% in-house P90, 30% historical claims P90 and "
        "20% verified external price."
    )
    calculation.append(_step(5, "Weighting applied", applied, price_explanation))

    evidence_price = money(evidence_price) or ZERO
    calculation.append(
        _step(
            6,
            "Evidence price",
            str(evidence_price),
            f"Combined evidence price is £{evidence_price:.2f}.",
        )
    )

    supported_price = evidence_price
    calculation.append(
        _step(
            7,
            "Supported price",
            str(supported_price),
            (f"The proportionally weighted evidence price is £{supported_price:.2f}."),
        )
    )

    difference = money(max(billed - supported_price, ZERO)) or ZERO
    threshold = inputs.threshold_pct
    pct_diff = percentage(difference, supported_price) if supported_price > ZERO else ZERO
    pct_gate_passed = pct_diff > threshold
    calculation.append(
        _step(
            8,
            "Percentage gate",
            f"{pct_diff:.2f}% vs {threshold:.0f}% threshold",
            (
                f"{'PASS' if pct_gate_passed else 'FAIL'}: the £{difference:.2f} difference is "
                f"{pct_diff:.2f}% of the supported price, which is "
                f"{'above' if pct_gate_passed else 'not above'} the {threshold:.0f}% threshold."
            ),
            passed=pct_gate_passed,
        )
    )

    amount_gate_passed = difference >= policy.minimum_challenge_amount
    calculation.append(
        _step(
            9,
            "Absolute gate",
            f"£{difference:.2f} vs £{policy.minimum_challenge_amount:.2f} minimum",
            (
                f"{'PASS' if amount_gate_passed else 'FAIL'}: the £{difference:.2f} difference "
                f"is {'at least' if amount_gate_passed else 'below'} the "
                f"£{policy.minimum_challenge_amount:.2f} minimum."
            ),
            passed=amount_gate_passed,
        )
    )

    challenged = pct_gate_passed and amount_gate_passed
    status = "CHALLENGE" if challenged else "WITHIN"
    calculation.append(
        _step(
            10,
            "Status",
            status,
            (
                f"Both gates passed; the line is challenged for £{difference:.2f}."
                if challenged
                else "One or both review gates did not pass; the line stands within benchmark."
            ),
        )
    )

    challenge_net = difference if challenged else ZERO
    if inputs.is_mot:
        challenge_vat = ZERO
        vat_detail = "MOT — outside VAT."
    elif challenged:
        challenge_vat = money(challenge_net * inputs.vat_rate / Decimal("100")) or ZERO
        vat_detail = f"VAT impact £{challenge_vat:.2f} at {inputs.vat_rate:.0f}%."
    else:
        challenge_vat = ZERO
        vat_detail = "No VAT impact; the line is not challenged."
    calculation.append(_step(11, "VAT impact", str(challenge_vat), vat_detail))

    gate_summary = (
        f"The supported price is £{supported_price:.2f}, so the £{difference:.2f} difference "
        f"exceeds the {threshold:.0f}% and £{policy.minimum_challenge_amount:.2f} review gates."
        if challenged
        else (
            f"The supported price is £{supported_price:.2f} and does not exceed both the "
            f"{threshold:.0f}% and £{policy.minimum_challenge_amount:.2f} review gates."
        )
    )
    evidence_explanations = " ".join(
        evidence.explanation for evidence in (inputs.p90, inputs.historical) if evidence
    )
    rationale = f"{evidence_explanations} {price_explanation} {gate_summary}".strip()
    evidence_rationale = (
        f"{price_explanation} {in_house_count} validated synthetic in-house price"
        f"{'' if in_house_count == 1 else 's'} and {historical_count} uploaded historical-claim "
        f"price{'' if historical_count == 1 else 's'} contributed. The mapping model "
        "selects a bounded repair category and never supplies a price."
    )

    return PriceDecision(
        has_signal=True,
        historical_count=in_house_count + historical_count,
        in_house_price=in_house_value,
        historical_price=historical_value,
        external_price=external_price,
        supported_price=supported_price,
        challenge_net=challenge_net,
        challenge_vat=challenge_vat,
        comparison_status=status,
        rationale=rationale,
        evidence_rationale=evidence_rationale,
        calculation=calculation,
    )
