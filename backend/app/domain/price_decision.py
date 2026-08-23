"""Server-side unified operational price decision.

This module is the single, pure-function source of truth for the "supported
price" / challenge decision that was previously computed client-side in
JavaScript floats (``src/features/claim-guard/p90-policy.ts``).  It reproduces
that policy exactly, but in ``Decimal`` arithmetic, and additionally emits an
ordered, machine-readable ``calculation`` breakdown so the workspace, the
result graph, and every export can show (and agree on) the same steps.

The legacy 60/40 comparison-engine results (``PriceComparison`` /
``ChallengeResult`` rows) are untouched by this module — they remain
persisted audit/evidence detail.  This module only decides, at read time,
what the *operational* supported price and challenge are for lines that carry
a P90 benchmark signal.
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
    """Interim P90 policy constants (mirrors ``p90-policy.ts``)."""

    p90_weight: Decimal = Decimal("0.70")
    external_weight: Decimal = Decimal("0.30")
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
    if decimal_value != decimal_value.to_integral_value() or int(
        decimal_value
    ) not in policy.allowed_thresholds:
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


@dataclass(frozen=True)
class LineDecisionInputs:
    """Everything ``decide_line_price`` needs for one invoice line."""

    billed_net: Decimal
    p90: P90Evidence | None
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

    if inputs.p90 is None:
        calculation.append(
            _step(
                2,
                "P90 benchmark",
                None,
                "No P90 benchmark signal is available for this line; the existing "
                "engine-derived evidence is retained unchanged.",
            )
        )
        return PriceDecision(
            has_signal=False,
            historical_count=None,
            supported_price=None,
            challenge_net=ZERO,
            challenge_vat=ZERO,
            comparison_status=None,
            rationale=None,
            evidence_rationale=None,
            calculation=calculation,
        )

    p90_value = money(inputs.p90.value) or ZERO
    count = inputs.p90.historical_count
    contributing = ", ".join(inputs.p90.contributing_invoices) or "none recorded"
    calculation.append(
        _step(
            2,
            "Historical P90 benchmark",
            str(p90_value),
            (
                f"{inputs.p90.method}: £{p90_value:.2f} from {count} earlier matching "
                f"invoice price{'' if count == 1 else 's'} ({contributing}); "
                "the current invoice is excluded."
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
                3,
                "Approved external price",
                str(external_price),
                f"Governed ontology price £{external_price:.2f} ({approval_label}).",
            )
        )
    else:
        calculation.append(
            _step(3, "Approved external price", None, "No approved external price is available.")
        )

    p90_weight_pct = (policy.p90_weight * Decimal("100")).quantize(Decimal("1"))
    external_weight_pct = (policy.external_weight * Decimal("100")).quantize(Decimal("1"))
    if external_price is not None:
        price_explanation = (
            f"The support price applies {p90_weight_pct}% weight to the uploaded-invoice "
            f"P90 (£{p90_value:.2f}) and {external_weight_pct}% to the approved external "
            f"price (£{external_price:.2f})."
        )
        evidence_price = money(
            p90_value * policy.p90_weight + external_price * policy.external_weight
        ) or ZERO
        calculation.append(
            _step(
                4,
                "Weighting applied",
                f"{p90_weight_pct}% P90 / {external_weight_pct}% external",
                price_explanation,
            )
        )
    else:
        price_explanation = (
            f"No approved external price is available, so the uploaded-invoice P90 of "
            f"£{p90_value:.2f} is used."
        )
        evidence_price = p90_value
        calculation.append(_step(4, "Weighting applied", "P90 alone", price_explanation))

    evidence_price = money(evidence_price) or ZERO
    calculation.append(
        _step(
            5,
            "Evidence price",
            str(evidence_price),
            f"Combined evidence price is £{evidence_price:.2f}.",
        )
    )

    supported_price = money(min(billed, evidence_price)) or ZERO
    calculation.append(
        _step(
            6,
            "Supported price",
            str(supported_price),
            (
                f"min(billed £{billed:.2f}, evidence £{evidence_price:.2f}) = "
                f"£{supported_price:.2f}."
            ),
        )
    )

    difference = money(max(billed - supported_price, ZERO)) or ZERO
    threshold = inputs.threshold_pct
    pct_diff = percentage(difference, supported_price) if supported_price > ZERO else ZERO
    pct_gate_passed = pct_diff > threshold
    calculation.append(
        _step(
            7,
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
            8,
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
            9,
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
    calculation.append(_step(10, "VAT impact", str(challenge_vat), vat_detail))

    gate_summary = (
        f"The supported price is £{supported_price:.2f}, so the £{difference:.2f} difference "
        f"exceeds the {threshold:.0f}% and £{policy.minimum_challenge_amount:.2f} review gates."
        if challenged
        else (
            f"The supported price is £{supported_price:.2f} and does not exceed both the "
            f"{threshold:.0f}% and £{policy.minimum_challenge_amount:.2f} review gates."
        )
    )
    rationale = f"{inputs.p90.explanation} {price_explanation} {gate_summary}"
    evidence_rationale = (
        f"{price_explanation} {inputs.p90.method}; {count} earlier matching invoice "
        f"price{'' if count == 1 else 's'}; current invoice excluded. The mapping model "
        "selects a bounded repair category and never supplies a price."
    )

    return PriceDecision(
        has_signal=True,
        historical_count=count,
        supported_price=supported_price,
        challenge_net=challenge_net,
        challenge_vat=challenge_vat,
        comparison_status=status,
        rationale=rationale,
        evidence_rationale=evidence_rationale,
        calculation=calculation,
    )
