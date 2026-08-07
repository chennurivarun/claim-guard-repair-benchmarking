from decimal import Decimal

from app.domain.money import calculate_challenge


def test_positive_only_and_gate() -> None:
    result = calculate_challenge(
        invoice_line_net=Decimal("200.00"),
        benchmark_line_net=Decimal("150.00"),
        vat_rate=Decimal("20"),
        vat_applicable=True,
    )
    assert result.challenge_net == Decimal("50.00")
    assert result.vat_impact == Decimal("10.00")
    assert result.challenge_gross == Decimal("60.00")
    assert result.challenge_price_net == Decimal("150.00")


def test_below_benchmark_never_offsets() -> None:
    result = calculate_challenge(
        invoice_line_net=Decimal("100.00"),
        benchmark_line_net=Decimal("115.00"),
        vat_rate=Decimal("20"),
        vat_applicable=True,
    )
    assert result.challenge_net == Decimal("0.00")


def test_amount_and_percentage_gate_is_and() -> None:
    result = calculate_challenge(
        invoice_line_net=Decimal("200.00"),
        benchmark_line_net=Decimal("194.00"),
        vat_rate=Decimal("20"),
        vat_applicable=True,
    )
    assert result.challenge_percentage == Decimal("0.00")
    assert result.gate_passed is False
