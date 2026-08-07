"""Fact-only negotiation-letter context shared by DOCX and PDF builders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.exports.common import (
    ChallengeLine,
    ExportValidationError,
    FinancialSummary,
    approved_challenge_lines,
    case_record,
    collection,
    compute_financial_summary,
    first_value,
    money_label,
    validate_liability_for_letter,
)


@dataclass(frozen=True)
class LetterFacts:
    case_reference: str
    claim_number: str
    recipient: str
    paying_insurer: str
    invoice_references: str
    invoice_dates: str
    vehicle_registration: str
    repairer: str
    report_date: str
    liability_status: str
    liability_confirmed_by: str
    liability_confirmed_at: str
    summary: FinancialSummary
    lines: tuple[ChallengeLine, ...]


def _display_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def build_letter_facts(result: Mapping[str, Any]) -> LetterFacts:
    liability = validate_liability_for_letter(result)
    lines = tuple(approved_challenge_lines(result))
    if not lines:
        raise ExportValidationError(
            "Negotiation letters require at least one approved, challengeable line with a positive difference"
        )
    claim = case_record(result)
    invoices = collection(result, ("invoices", "invoice_units"))
    references = [
        str(first_value(invoice, ("invoice_number", "reference", "id"), "")) for invoice in invoices
    ]
    invoice_dates = [
        _display_date(first_value(invoice, ("invoice_date", "date"), "")) for invoice in invoices
    ]
    repairers = [
        str(first_value(invoice, ("repairer", "garage", "supplier_name"), ""))
        for invoice in invoices
    ]
    registrations = [
        str(first_value(invoice, ("vehicle_registration", "registration", "vrm"), ""))
        for invoice in invoices
    ]
    report_date = _display_date(
        first_value(result, ("report_date", "generated_at", "exported_at"), date.today())
    )
    case_reference = str(
        first_value(claim, ("case_reference", "reference", "claim_number", "id"), "Unassigned")
    )
    claim_number = str(first_value(claim, ("claim_number", "case_reference"), case_reference))
    recipient = str(
        first_value(
            claim,
            (
                "claiming_insurer_name",
                "claiming_insurer",
                "claiming_party",
                "third_party_name",
            ),
            first_value(invoices[0], ("customer", "bill_to"), "Claims Team")
            if invoices
            else "Claims Team",
        )
    )
    return LetterFacts(
        case_reference=case_reference,
        claim_number=claim_number,
        recipient=recipient,
        paying_insurer=str(
            first_value(claim, ("paying_insurer_name", "paying_insurer"), "Paying insurer")
        ),
        invoice_references=", ".join(item for item in references if item) or "Not supplied",
        invoice_dates=", ".join(item for item in invoice_dates if item) or "Not supplied",
        vehicle_registration=", ".join(dict.fromkeys(item for item in registrations if item))
        or "Not supplied",
        repairer=", ".join(dict.fromkeys(item for item in repairers if item)) or "Not supplied",
        report_date=report_date,
        liability_status=str(liability["status"]),
        liability_confirmed_by=str(
            first_value(liability, ("confirmed_by", "human_confirmed_by"), "Claims handler")
        ),
        liability_confirmed_at=_display_date(
            first_value(liability, ("confirmed_at", "human_confirmed_at"), "")
        ),
        summary=compute_financial_summary(result),
        lines=lines,
    )


def deterministic_line_sentence(line: ChallengeLine) -> str:
    """Create negotiation wording from immutable numeric facts only."""

    clauses = [
        f"The invoice charges {money_label(line.invoice_net)} net for {line.description}.",
        (
            f"The approved Challenge Price for this line is "
            f"{money_label(line.challenge_price_net)} net, based on {line.benchmark_source}."
        ),
    ]
    if line.ontology_price_net is not None:
        clauses.append(
            f"The approved ontology observation is {money_label(line.ontology_price_net)} net."
        )
    if line.historical_median_net is not None and line.historical_count:
        clauses.append(
            f"The median across {line.historical_count} comparable previous repair and service "
            f"observations is {money_label(line.historical_median_net)} net."
        )
    clauses.append(
        f"The resulting Challenge Amount is {money_label(line.challenge_amount_net)} net."
    )
    if line.is_mot:
        clauses.append("This MOT line is outside the VAT-impact computation.")
    return " ".join(clauses)
