"""Unit tests for the server-side unified price decision (backend/app/domain/price_decision.py).

The golden-parity cases mirror ``src/features/claim-guard/p90-policy.test.ts``
exactly (same inputs, same expected £ results) so the Decimal port and the
former JS-float overlay can never silently diverge.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.price_decision import (
    DEFAULT_POLICY,
    LineDecisionInputs,
    P90Evidence,
    decide_line_price,
    resolve_threshold_pct,
)


def _p90(value: str = "100", count: int = 4) -> P90Evidence:
    return P90Evidence(
        value=Decimal(value),
        historical_count=count,
        method="Interpolated percentile (PERCENTILE.INC)",
        explanation="Earlier matching invoices establish P90.",
        contributing_invoices=("INV-100", "INV-101", "INV-102", "INV-103"),
    )


def _inputs(**overrides: object) -> LineDecisionInputs:
    defaults: dict[str, object] = {
        "billed_net": Decimal("200"),
        "p90": _p90(),
        "historical": None,
        "external_price": None,
        "external_approval_status": None,
        "vat_rate": Decimal("20"),
        "is_mot": False,
        "threshold_pct": Decimal("5"),
    }
    defaults.update(overrides)
    return LineDecisionInputs(**defaults)  # type: ignore[arg-type]


# --- Golden parity with p90-policy.test.ts -------------------------------


def test_weights_in_house_historical_and_external_at_50_30_20() -> None:
    decision = decide_line_price(
        _inputs(
            billed_net=Decimal("200"),
            historical=_p90("120", count=6),
            external_price=Decimal("160"),
        )
    )

    assert decision.supported_price == Decimal("118.00")
    assert decision.challenge_net == Decimal("82.00")
    assert decision.challenge_vat == Decimal("16.40")
    assert decision.comparison_status == "CHALLENGE"
    assert "50% in-house" in decision.evidence_rationale
    assert "30% historical" in decision.evidence_rationale
    assert "20% verified external" in decision.evidence_rationale


def test_uses_p90_alone_when_external_evidence_is_unavailable() -> None:
    decision = decide_line_price(_inputs(billed_net=Decimal("200"), external_price=None))

    assert decision.supported_price == Decimal("100.00")
    assert decision.challenge_net == Decimal("100.00")
    assert "100% in-house" in decision.evidence_rationale


def test_does_not_challenge_unless_both_policy_gates_are_exceeded() -> None:
    decision = decide_line_price(
        _inputs(
            billed_net=Decimal("122"),
            historical=_p90("120", count=6),
            external_price=Decimal("160"),
        )
    )

    assert decision.supported_price == Decimal("118.00")
    assert decision.challenge_net == Decimal("0.00")
    assert decision.comparison_status == "WITHIN"


# --- Threshold parameter ---------------------------------------------------


def test_same_line_is_challenged_at_5_percent_and_within_at_10_percent() -> None:
    inputs = _inputs(
        billed_net=Decimal("108"),
        p90=_p90("100"),
        external_price=None,
    )

    at_5 = decide_line_price(
        LineDecisionInputs(**{**inputs.__dict__, "threshold_pct": Decimal("5")})
    )
    at_10 = decide_line_price(
        LineDecisionInputs(**{**inputs.__dict__, "threshold_pct": Decimal("10")})
    )

    assert at_5.comparison_status == "CHALLENGE"
    assert at_5.challenge_net == Decimal("8.00")
    assert at_10.comparison_status == "WITHIN"
    assert at_10.challenge_net == Decimal("0.00")


@pytest.mark.parametrize("value", [5, "5", "10", 10, Decimal("5")])
def test_resolve_threshold_pct_accepts_allowed_values(value: object) -> None:
    resolved = resolve_threshold_pct(value)
    assert resolved in (Decimal("5"), Decimal("10"))


def test_resolve_threshold_pct_defaults_to_ten_when_absent() -> None:
    assert resolve_threshold_pct(None) == Decimal(DEFAULT_POLICY.default_threshold_pct)


@pytest.mark.parametrize("value", [7, "0", "15", "abc"])
def test_resolve_threshold_pct_rejects_disallowed_values(value: object) -> None:
    with pytest.raises(ValueError):
        resolve_threshold_pct(value)


# --- MOT VAT suppression ----------------------------------------------------


def test_mot_line_suppresses_challenge_vat() -> None:
    decision = decide_line_price(
        _inputs(
            billed_net=Decimal("150"),
            p90=_p90("100"),
            external_price=None,
            vat_rate=Decimal("20"),
            is_mot=True,
            threshold_pct=Decimal("10"),
        )
    )

    assert decision.comparison_status == "CHALLENGE"
    assert decision.challenge_net == Decimal("50.00")
    assert decision.challenge_vat == Decimal("0.00")
    vat_step = next(step for step in decision.calculation if step["label"] == "VAT impact")
    assert "MOT" in vat_step["detail"]


# --- No P90 signal -----------------------------------------------------------


def test_no_p90_signal_leaves_decision_unset() -> None:
    decision = decide_line_price(_inputs(p90=None, historical=None))

    assert decision.has_signal is False
    assert decision.supported_price is None
    assert decision.challenge_net == Decimal("0")
    assert decision.comparison_status is None
    assert decision.rationale is None


def test_historical_claims_can_support_a_decision_without_in_house_history() -> None:
    decision = decide_line_price(
        _inputs(p90=None, historical=_p90("110", count=5), external_price=Decimal("130"))
    )

    assert decision.has_signal is True
    assert decision.supported_price == Decimal("118.00")
    assert "60% historical claims" in decision.evidence_rationale
    assert "40% verified external" in decision.evidence_rationale


def test_external_price_alone_never_creates_an_automatic_challenge() -> None:
    decision = decide_line_price(_inputs(p90=None, historical=None, external_price=Decimal("80")))

    assert decision.has_signal is False
    assert decision.challenge_net == Decimal("0")


# --- Breakdown completeness (C3) --------------------------------------------


def test_calculation_breakdown_includes_both_gates_and_the_min_step() -> None:
    decision = decide_line_price(
        _inputs(
            billed_net=Decimal("200"),
            historical=_p90("120", count=6),
            external_price=Decimal("160"),
        )
    )

    labels = [step["label"] for step in decision.calculation]
    assert "Billed net" in labels
    assert "In-house P90 benchmark" in labels
    assert "Historical claims P90" in labels
    assert "Verified external price" in labels
    assert "Weighting applied" in labels
    assert "Evidence price" in labels
    assert "Supported price" in labels
    assert "Percentage gate" in labels
    assert "Absolute gate" in labels
    assert "Status" in labels
    assert "VAT impact" in labels

    supported_step = next(
        step for step in decision.calculation if step["label"] == "Supported price"
    )
    assert "min(" in supported_step["detail"]

    pct_step = next(step for step in decision.calculation if step["label"] == "Percentage gate")
    amount_step = next(step for step in decision.calculation if step["label"] == "Absolute gate")
    assert pct_step["passed"] is True
    assert amount_step["passed"] is True
    assert "82.00" in amount_step["detail"] or "82" in amount_step["value"]


def test_calculation_breakdown_reports_failed_gates() -> None:
    decision = decide_line_price(_inputs(billed_net=Decimal("122"), external_price=Decimal("160")))

    amount_step = next(step for step in decision.calculation if step["label"] == "Absolute gate")
    assert amount_step["passed"] is False


def test_rationale_and_evidence_rationale_are_generated_from_the_same_steps() -> None:
    decision = decide_line_price(
        _inputs(
            billed_net=Decimal("200"),
            historical=_p90("120", count=6),
            external_price=Decimal("160"),
        )
    )

    supported_step = next(
        step for step in decision.calculation if step["label"] == "Supported price"
    )
    assert str(decision.supported_price) in supported_step["value"]
    assert "50% in-house" in decision.rationale
    assert "82.00" in decision.rationale
