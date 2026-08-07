from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PENNY = Decimal("0.01")
ZERO = Decimal("0.00")


def as_decimal(value: Decimal | str | int | float | None) -> Decimal | None:
    """Parse external numeric input without allowing binary-float arithmetic downstream."""

    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").replace("£", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def money(value: Decimal | str | int | float | None) -> Decimal | None:
    parsed = as_decimal(value)
    return parsed.quantize(PENNY, rounding=ROUND_HALF_UP) if parsed is not None else None


def money_text(value: Decimal | str | int | float | None) -> str | None:
    parsed = money(value)
    return f"{parsed:.2f}" if parsed is not None else None


def percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= ZERO:
        return ZERO
    return ((numerator / denominator) * Decimal("100")).quantize(PENNY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ChallengeAmounts:
    challenge_net: Decimal
    challenge_percentage: Decimal
    vat_impact: Decimal
    challenge_gross: Decimal
    challenge_price_net: Decimal
    gate_passed: bool


def calculate_challenge(
    *,
    invoice_line_net: Decimal,
    benchmark_line_net: Decimal,
    vat_rate: Decimal,
    vat_applicable: bool,
    minimum_amount: Decimal = Decimal("5.00"),
    minimum_percent: Decimal = Decimal("5.00"),
) -> ChallengeAmounts:
    """Calculate the v1.4 positive-only, quantity-adjusted net line challenge."""

    invoice_line_net = money(invoice_line_net) or ZERO
    benchmark_line_net = money(benchmark_line_net) or ZERO
    raw = max(invoice_line_net - benchmark_line_net, ZERO)
    challenge_pct = percentage(raw, invoice_line_net)
    gate_passed = raw >= minimum_amount and challenge_pct >= minimum_percent
    challenge_net = money(raw if gate_passed else ZERO) or ZERO
    vat_impact = (
        money(challenge_net * vat_rate / Decimal("100")) or ZERO if vat_applicable else ZERO
    )
    return ChallengeAmounts(
        challenge_net=challenge_net,
        challenge_percentage=percentage(challenge_net, invoice_line_net),
        vat_impact=vat_impact,
        challenge_gross=money(challenge_net + vat_impact) or ZERO,
        challenge_price_net=money(invoice_line_net - challenge_net) or ZERO,
        gate_passed=gate_passed,
    )
