"""The challenge email draft: deterministic figures, optional AI prose, no new £.

Every £ figure in the draft must come from the analysis.  AI may write the
prose around the deterministic figures list; if its text introduces a £ figure
the analysis does not contain, the whole AI draft is discarded for the
template.  Nothing here sends anything.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.services.source_benchmarks import (
    analysis_money_figures,
    compose_challenge_email,
    money_figures_in_text,
)


def _line(line_id: str, description: str, amount: str, justified: str, challenge: str) -> dict:
    return {
        "line_id": line_id,
        "origin": "invoice",
        "line_item_type": "parts",
        "description": description,
        "repair_item": description.title(),
        "amount": amount,
        "benchmarks": {
            "third_party": {
                "available": True, "p90": justified, "observations": 2,
                "above_p90": True, "violated": True, "difference": challenge,
                "difference_pct": "13.77", "evidence": [],
            },
            "aviva_dlg": {
                "available": False, "p90": None, "observations": 0,
                "above_p90": False, "violated": False, "difference": None,
                "difference_pct": None, "evidence": [],
            },
        },
        "challenge": {
            "is_challenge": True, "level": "medium", "justified_amount": justified,
            "challenge_amount": challenge,
            "reason": f"Exceeds the third-party P90 (£{justified}, n=2) by 13.77%.",
        },
    }


ANALYSIS = {
    "invoice": {
        "id": "inv-1", "invoice_number": "INV-42", "vehicle_make": "HYUNDAI",
        "vehicle_model": "i30", "vehicle_category": "Hatchback",
        "vehicle_category_source": "lookup", "registration": "AB12XYZ",
        "paired_assessment_number": "D1",
    },
    "threshold_pct": "10",
    "minimum_challenge_amount": "5.00",
    "lines": [
        _line("l1", "L/R DOOR", "1000.00", "878.84", "121.16"),
        _line("l2", "L/SILL PANEL COVER", "345.00", "309.55", "35.45"),
    ],
    "section_breakdowns": [],
    "totals": {"line_count": 2, "challenge_count": 2,
               "by_level": {"high": 0, "medium": 2, "low": 0},
               "total_challenge_amount": "156.61"},
}


class _Writer:
    provider = "fake"
    model_id = "fake-1"

    def __init__(self, response: dict) -> None:
        self.response = response
        self.payloads: list[dict] = []

    def write(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.response


def test_money_figures_are_read_with_and_without_thousands_separators() -> None:
    assert money_figures_in_text("£1,000.00 and £ 35.45 and £7") == {
        Decimal("1000.00"), Decimal("35.45"), Decimal("7.00"),
    }


def test_template_draft_uses_only_figures_from_the_analysis() -> None:
    draft = compose_challenge_email(
        ANALYSIS, ANALYSIS["lines"][:1], recipient="Acme Insurance", writer=None
    )

    assert draft["generated_by"] == "template"
    assert draft["total_challenge_amount"] == "121.16"
    assert [line["line_id"] for line in draft["lines"]] == ["l1"]
    figures = money_figures_in_text(draft["subject"] + draft["body"])
    assert figures, "the draft must carry the figures it argues from"
    assert figures <= analysis_money_figures(ANALYSIS)
    assert "Acme Insurance" in draft["body"]
    for figure in ("1,000.00", "878.84", "121.16"):
        assert figure in draft["body"]
    # The unselected line is not argued.
    assert "SILL" not in draft["body"]


def test_ai_prose_is_used_when_it_introduces_no_new_figure() -> None:
    writer = _Writer({
        "subject": "Invoice INV-42: two items above benchmark",
        "opening": "We have reviewed the invoice against our repair benchmarks.",
        "closing": "Please confirm the revised figures, which total £156.61.",
        "rationales": [{"line_id": "l1", "rationale": "The door is priced above peers."}],
    })

    draft = compose_challenge_email(ANALYSIS, ANALYSIS["lines"], recipient=None, writer=writer)

    assert draft["generated_by"] == "ai"
    assert "We have reviewed the invoice" in draft["body"]
    assert "The door is priced above peers." in draft["body"]
    # The figures list is still the deterministic one.
    assert "878.84" in draft["body"] and "309.55" in draft["body"]
    assert money_figures_in_text(draft["subject"] + draft["body"]) <= analysis_money_figures(
        ANALYSIS
    )
    assert writer.payloads and writer.payloads[0]["lines"]


def test_ai_prose_with_an_invented_figure_falls_back_to_the_template() -> None:
    writer = _Writer({
        "subject": "Invoice INV-42",
        "opening": "We will only pay £750.00 for the door.",
        "closing": "Regards.",
        "rationales": [],
    })

    draft = compose_challenge_email(ANALYSIS, ANALYSIS["lines"], recipient=None, writer=writer)

    assert draft["generated_by"] == "template"
    assert "750.00" not in draft["body"]


def test_ai_failure_falls_back_to_the_template() -> None:
    class _Broken:
        def write(self, payload: dict) -> dict:
            raise RuntimeError("provider down")

    draft = compose_challenge_email(ANALYSIS, ANALYSIS["lines"], recipient=None, writer=_Broken())

    assert draft["generated_by"] == "template"
    assert re.search(r"£156\.61", draft["body"])
