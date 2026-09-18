"""Spec D3: violation, level, justified figure and challenge amount per line.

The rule is the existing valuation rule unchanged -- a benchmark is violated
when the line exceeds its P90 by *more than* the threshold (10% default) *and*
by at least the £5 minimum -- read from ``price_decision.DEFAULT_POLICY``
rather than restated.  High = both violated, Medium = one, Low = above at
least one P90 but inside the rule, none otherwise.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.price_decision import DEFAULT_POLICY
from app.services.source_benchmarks import challenge_for_line, compare_to_benchmark

TEN = Decimal(DEFAULT_POLICY.default_threshold_pct)


def _compare(amount: str | None, p90: str | None, n: int = 3) -> dict:
    return compare_to_benchmark(
        None if amount is None else Decimal(amount),
        None if p90 is None else Decimal(p90),
        n,
        threshold_pct=TEN,
    )


def test_policy_values_come_from_the_frozen_price_decision_module() -> None:
    assert DEFAULT_POLICY.minimum_challenge_amount == Decimal("5.00")
    assert DEFAULT_POLICY.default_threshold_pct == 10


def test_no_observations_is_unavailable_never_zero_and_never_violated() -> None:
    compared = _compare("500.00", None, 0)

    assert compared == {
        "available": False,
        "p90": None,
        "observations": 0,
        "above_p90": False,
        "violated": False,
        "difference": None,
        "difference_pct": None,
    }


def test_above_p90_within_threshold_is_not_violated() -> None:
    compared = _compare("847.73", "800.00")

    assert compared["available"] is True
    assert compared["above_p90"] is True
    assert compared["violated"] is False
    assert compared["difference"] == "47.73"
    assert compared["difference_pct"] == "5.97"


def test_threshold_is_strict_and_minimum_is_inclusive() -> None:
    # Exactly 10% above is not "more than" the threshold.
    assert _compare("110.00", "100.00")["violated"] is False
    assert _compare("110.01", "100.00")["violated"] is True
    # 20% above but only £4.99: below the £5 minimum challenge.
    assert _compare("29.94", "24.95")["violated"] is False
    # Exactly £5 and more than 10%: violated.
    assert _compare("30.00", "25.00")["violated"] is True


def test_high_when_both_benchmarks_are_violated_and_justified_is_the_higher_p90() -> None:
    comparisons = {
        "third_party": _compare("1000.00", "878.84"),
        "aviva_dlg": _compare("1000.00", "827.46"),
    }

    challenge = challenge_for_line(Decimal("1000.00"), comparisons, threshold_pct=TEN)

    assert challenge["level"] == "high"
    assert challenge["is_challenge"] is True
    assert challenge["justified_amount"] == "878.84"
    assert challenge["challenge_amount"] == "121.16"
    assert "878.84" in challenge["reason"] and "827.46" in challenge["reason"]


def test_medium_when_only_one_benchmark_is_violated() -> None:
    comparisons = {
        "third_party": _compare("345.00", "328.93"),
        "aviva_dlg": _compare("345.00", "309.55"),
    }

    challenge = challenge_for_line(Decimal("345.00"), comparisons, threshold_pct=TEN)

    assert challenge["level"] == "medium"
    assert challenge["is_challenge"] is True
    assert challenge["justified_amount"] == "309.55"
    assert challenge["challenge_amount"] == "35.45"


def test_medium_when_the_only_available_benchmark_is_violated() -> None:
    comparisons = {
        "third_party": _compare("345.00", None, 0),
        "aviva_dlg": _compare("345.00", "200.00"),
    }

    challenge = challenge_for_line(Decimal("345.00"), comparisons, threshold_pct=TEN)

    assert challenge["level"] == "medium"
    assert challenge["justified_amount"] == "200.00"


def test_low_is_above_a_p90_but_within_the_rule_and_never_counts() -> None:
    comparisons = {
        "third_party": _compare("31.50", "31.10"),
        "aviva_dlg": _compare("31.50", "29.28"),
    }

    challenge = challenge_for_line(Decimal("31.50"), comparisons, threshold_pct=TEN)

    assert challenge["level"] == "low"
    assert challenge["is_challenge"] is False
    assert challenge["justified_amount"] is None
    assert challenge["challenge_amount"] == "0.00"
    assert "within the 10% threshold" in challenge["reason"]


def test_none_at_or_below_every_p90_and_when_nothing_is_available() -> None:
    below = challenge_for_line(
        Decimal("5.00"),
        {"third_party": _compare("5.00", "10.00"), "aviva_dlg": _compare("5.00", "5.00")},
        threshold_pct=TEN,
    )
    unavailable = challenge_for_line(
        Decimal("5.00"),
        {"third_party": _compare("5.00", None, 0), "aviva_dlg": _compare("5.00", None, 0)},
        threshold_pct=TEN,
    )

    assert below["level"] is None and below["is_challenge"] is False
    assert unavailable["level"] is None
    assert "no observations" in unavailable["reason"].lower()
