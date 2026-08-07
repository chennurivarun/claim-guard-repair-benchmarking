"""Shared deterministic export calculations and normalized-result accessors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any

MONEY_QUANTUM = Decimal("0.01")
ZERO = Decimal("0")

LIABILITY_STATUSES = {
    "ADMITTED",
    "DENIED",
    "SPLIT LIABILITY",
    "PENDING",
    "HUMAN REVIEW REQUIRED",
}
ISSUABLE_LIABILITY_STATUSES = {"ADMITTED", "SPLIT LIABILITY"}
APPROVED_STATUSES = {
    "ACCEPTED",
    "APPROVED",
    "HANDLER APPROVED",
    "HUMAN APPROVED",
    "FINAL",
}
CHALLENGEABLE_STATUSES = {
    "CHALLENGE",
    "CHALLENGEABLE",
    "INCLUDED",
    "READY",
}


class ExportValidationError(ValueError):
    """Raised when a report cannot be issued safely from the supplied facts."""


def as_decimal(value: Any, *, default: Decimal | None = ZERO) -> Decimal:
    """Convert JSON-friendly money/quantity values without binary float maths."""

    if value is None or value == "":
        if default is None:
            raise ExportValidationError("A required numeric export value is missing")
        return default
    if isinstance(value, bool):
        if default is None:
            raise ExportValidationError("Boolean is not a valid numeric export value")
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace("£", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        if default is None:
            raise ExportValidationError(f"Invalid numeric export value: {value!r}") from exc
        return default


def money(value: Any) -> Decimal:
    return as_decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def money_text(value: Any) -> str:
    return f"{money(value):.2f}"


def money_label(value: Any) -> str:
    return f"£{money(value):,.2f}"


def percentage_label(value: Any) -> str:
    return f"{as_decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}%"


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, Decimal)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "approved"}


def normalized_status(value: Any) -> str:
    raw = value.value if isinstance(value, Enum) else value
    return str(raw or "").replace("_", " ").replace("-", " ").strip().upper()


def first_value(record: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def first_mapping(result: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def collection(result: Mapping[str, Any], keys: Sequence[str]) -> list[dict[str, Any]]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            return [dict(value)]
    return []


def case_record(result: Mapping[str, Any]) -> dict[str, Any]:
    return first_mapping(result, ("claim", "case", "claim_case"))


def liability_record(result: Mapping[str, Any]) -> dict[str, Any]:
    liability = first_mapping(result, ("liability", "liability_assessment"))
    if liability:
        return liability
    claim = case_record(result)
    return {
        key: claim[key]
        for key in (
            "liability_status",
            "status",
            "human_confirmed",
            "confirmed_by",
            "confirmed_at",
        )
        if key in claim
    }


def validate_liability_for_letter(result: Mapping[str, Any]) -> dict[str, Any]:
    """Require an explicit handler-confirmed liability position before issuance."""

    liability = liability_record(result)
    status = normalized_status(first_value(liability, ("status", "liability_status")))
    if status not in LIABILITY_STATUSES:
        allowed = ", ".join(sorted(LIABILITY_STATUSES))
        raise ExportValidationError(
            f"Negotiation letters require a valid liability status ({allowed}); got {status or 'blank'}"
        )
    if not bool_value(first_value(liability, ("human_confirmed", "handler_confirmed"), False)):
        raise ExportValidationError(
            "Negotiation letters require a human-confirmed liability status"
        )
    if status not in ISSUABLE_LIABILITY_STATUSES:
        raise ExportValidationError(
            "Negotiation letters may only be issued for human-confirmed ADMITTED or "
            "SPLIT LIABILITY claims"
        )
    return {**liability, "status": status, "human_confirmed": True}


def _all_invoice_lines(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    lines = collection(result, ("lines", "invoice_lines", "line_items"))
    if lines:
        return lines
    nested: list[dict[str, Any]] = []
    for invoice in collection(result, ("invoices", "invoice_units")):
        invoice_id = first_value(invoice, ("id", "invoice_id", "invoice_number"))
        for key in ("lines", "invoice_lines", "line_items"):
            value = invoice.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                for item in value:
                    if isinstance(item, Mapping):
                        nested.append({"invoice_id": invoice_id, **dict(item)})
                break
    return nested


def _is_approved(record: Mapping[str, Any]) -> bool:
    for key in ("approved", "human_approved", "handler_approved", "accepted"):
        if key in record:
            return bool_value(record[key])
    status = normalized_status(
        first_value(record, ("approval_status", "review_status", "decision", "status"))
    )
    return status in APPROVED_STATUSES


def _is_challengeable(record: Mapping[str, Any]) -> bool:
    for key in ("challengeable", "is_challengeable", "include_in_letter"):
        if key in record:
            return bool_value(record[key])
    status = normalized_status(
        first_value(record, ("challenge_status", "comparison_status", "recommendation"))
    )
    return status in CHALLENGEABLE_STATUSES


def _is_mot(record: Mapping[str, Any]) -> bool:
    if bool_value(first_value(record, ("is_mot", "mot", "mot_test"), False)):
        return True
    category = normalized_status(
        first_value(record, ("kind", "line_kind", "category", "item_type"), "")
    )
    description = normalized_status(
        first_value(record, ("description", "original_description"), "")
    )
    return category in {"MOT", "MOT TEST"} or description.startswith("MOT ") or description == "MOT"


def _rate(record: Mapping[str, Any]) -> Decimal:
    if _is_mot(record) or record.get("vat_applicable") is False:
        return ZERO
    raw = as_decimal(
        first_value(record, ("vat_rate", "applicable_vat_rate", "invoice_vat_rate"), ZERO)
    )
    return raw / Decimal("100") if raw > 1 else raw


@dataclass(frozen=True)
class ChallengeLine:
    line_id: str
    invoice_id: str
    description: str
    invoice_net: Decimal
    challenge_price_net: Decimal
    challenge_amount_net: Decimal
    vat_rate: Decimal
    vat_impact: Decimal
    gross_effect: Decimal
    is_mot: bool
    benchmark_source: str
    ontology_item_id: str
    ontology_price_net: Decimal | None
    historical_median_net: Decimal | None
    historical_count: int
    reason: str
    challenge_score: Decimal | None

    def as_export_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key, value in tuple(result.items()):
            if isinstance(value, Decimal):
                result[key] = money_text(value) if key != "vat_rate" else str(value)
        return result


def approved_challenge_lines(result: Mapping[str, Any]) -> list[ChallengeLine]:
    """Return positive, approved and challengeable lines with code-owned maths.

    Any supplied challenge amount is deliberately ignored.  The disputed amount
    is recomputed as ``max(invoice net - approved benchmark net, 0)``.
    """

    source = collection(result, ("challenges", "challenge_lines"))
    if not source:
        source = collection(result, ("comparisons", "comparison_results"))

    line_index: dict[str, dict[str, Any]] = {}
    for line in _all_invoice_lines(result):
        line_id = str(first_value(line, ("id", "line_id", "invoice_line_id"), ""))
        if line_id:
            line_index[line_id] = line

    output: list[ChallengeLine] = []
    for challenge in source:
        line_id = str(first_value(challenge, ("line_id", "invoice_line_id", "id"), ""))
        merged = {**line_index.get(line_id, {}), **challenge}
        if not (_is_approved(merged) and _is_challengeable(merged)):
            continue

        invoice_value = first_value(
            merged,
            (
                "invoice_net",
                "invoice_comparable_net",
                "current_net",
                "charged_net",
                "net_line_total",
                "line_total_net",
            ),
        )
        benchmark_value = first_value(
            merged,
            (
                "challenge_price_net",
                "benchmark_net",
                "recommended_net",
                "recommended_payable_net",
                "selected_benchmark_net",
            ),
        )
        if invoice_value in (None, "") or benchmark_value in (None, ""):
            continue

        invoice_net = money(invoice_value)
        challenge_price = money(benchmark_value)
        challenge_amount = money(max(invoice_net - challenge_price, ZERO))
        if challenge_amount <= ZERO:
            continue
        vat_rate = _rate(merged)
        vat_impact = money(challenge_amount * vat_rate)

        ontology_raw = first_value(
            merged, ("ontology_price_net", "ontology_reference_net", "reference_price_net")
        )
        historical_raw = first_value(
            merged, ("historical_median_net", "history_median_net", "historical_price_net")
        )
        score_raw = first_value(merged, ("challenge_score", "evidence_strength_score"))
        output.append(
            ChallengeLine(
                line_id=line_id,
                invoice_id=str(first_value(merged, ("invoice_id", "invoice_number"), "")),
                description=str(
                    first_value(
                        merged,
                        ("description", "original_description", "invoice_description"),
                        "Invoice line",
                    )
                ),
                invoice_net=invoice_net,
                challenge_price_net=challenge_price,
                challenge_amount_net=challenge_amount,
                vat_rate=vat_rate,
                vat_impact=vat_impact,
                gross_effect=money(challenge_amount + vat_impact),
                is_mot=_is_mot(merged),
                benchmark_source=str(
                    first_value(
                        merged,
                        ("benchmark_source", "selected_benchmark_source", "evidence_source"),
                        "approved evidence",
                    )
                ),
                ontology_item_id=str(first_value(merged, ("ontology_item_id", "ontology_id"), "")),
                ontology_price_net=money(ontology_raw) if ontology_raw not in (None, "") else None,
                historical_median_net=(
                    money(historical_raw) if historical_raw not in (None, "") else None
                ),
                historical_count=int(
                    as_decimal(first_value(merged, ("historical_count", "comparable_count"), 0))
                ),
                reason=str(first_value(merged, ("reason", "rationale"), "")),
                challenge_score=(as_decimal(score_raw) if score_raw not in (None, "") else None),
            )
        )
    return output


def _invoice_net_total(result: Mapping[str, Any]) -> Decimal:
    summary = first_mapping(result, ("summary", "challenge_summary", "totals"))
    raw = first_value(
        summary,
        ("invoice_price_net", "original_invoice_net", "invoice_net", "net_total"),
    )
    if raw not in (None, ""):
        return money(raw)

    invoices = collection(result, ("invoices", "invoice_units"))
    if invoices:
        total = ZERO
        found = False
        for invoice in invoices:
            value = first_value(
                invoice,
                ("net_total", "invoice_price_net", "original_invoice_net", "invoice_net"),
            )
            if value not in (None, ""):
                total += as_decimal(value)
                found = True
                continue
            subtotal = first_value(invoice, ("net_subtotal", "subtotal_net", "subtotal"))
            if subtotal not in (None, ""):
                total += as_decimal(subtotal) + as_decimal(
                    first_value(invoice, ("non_vat_total", "mot_total"), ZERO)
                )
                found = True
        if found:
            return money(total)

    total = sum(
        (
            as_decimal(
                first_value(
                    line,
                    ("invoice_net", "net_line_total", "line_total_net", "current_net"),
                    ZERO,
                )
            )
            for line in _all_invoice_lines(result)
        ),
        ZERO,
    )
    return money(total)


def _invoice_total(result: Mapping[str, Any], aliases: Sequence[str]) -> Decimal:
    summary = first_mapping(result, ("summary", "challenge_summary", "totals"))
    raw = first_value(summary, aliases)
    if raw not in (None, ""):
        return money(raw)
    total = ZERO
    found = False
    for invoice in collection(result, ("invoices", "invoice_units")):
        raw = first_value(invoice, aliases)
        if raw not in (None, ""):
            total += as_decimal(raw)
            found = True
    return money(total if found else ZERO)


@dataclass(frozen=True)
class FinancialSummary:
    invoice_price_net: Decimal
    challenge_price_net: Decimal
    challenge_amount_net: Decimal
    vat_impact: Decimal
    gross_effect: Decimal
    original_vat: Decimal
    original_gross: Decimal
    proposed_payable_gross: Decimal
    mot_non_vat_total: Decimal
    challenge_percentage: Decimal
    challenged_line_count: int

    def as_export_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key, value in tuple(values.items()):
            if isinstance(value, Decimal):
                values[key] = f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
        return values


def compute_financial_summary(result: Mapping[str, Any]) -> FinancialSummary:
    """Compute invoice-level proposal figures from approved line facts only."""

    lines = approved_challenge_lines(result)
    invoice_price = _invoice_net_total(result)
    challenge_net = money(sum((line.challenge_amount_net for line in lines), ZERO))
    vat_impact = money(sum((line.vat_impact for line in lines), ZERO))
    gross_effect = money(challenge_net + vat_impact)
    challenge_price = money(max(invoice_price - challenge_net, ZERO))
    original_vat = _invoice_total(result, ("vat_total", "original_vat", "invoice_vat"))
    original_gross = _invoice_total(
        result, ("gross_total", "original_gross", "invoice_gross_total")
    )
    if original_gross == ZERO and (invoice_price or original_vat):
        original_gross = money(invoice_price + original_vat)
    proposed_gross = money(max(original_gross - gross_effect, ZERO))
    mot_non_vat = _invoice_total(result, ("non_vat_total", "mot_total", "mot_non_vat_total"))
    if mot_non_vat == ZERO:
        mot_non_vat = money(
            sum(
                (
                    as_decimal(
                        first_value(
                            line,
                            ("invoice_net", "net_line_total", "line_total_net"),
                            ZERO,
                        )
                    )
                    for line in _all_invoice_lines(result)
                    if _is_mot(line)
                ),
                ZERO,
            )
        )
    challenge_pct = (
        (challenge_net / invoice_price * Decimal("100")) if invoice_price > ZERO else ZERO
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return FinancialSummary(
        invoice_price_net=invoice_price,
        challenge_price_net=challenge_price,
        challenge_amount_net=challenge_net,
        vat_impact=vat_impact,
        gross_effect=gross_effect,
        original_vat=original_vat,
        original_gross=original_gross,
        proposed_payable_gross=proposed_gross,
        mot_non_vat_total=mot_non_vat,
        challenge_percentage=challenge_pct,
        challenged_line_count=len(lines),
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        # Preserve source precision in the full result graph.  Only fields that
        # are explicitly monetary are quantized by the financial calculators.
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return json_safe(value.value)
    return value


def full_export_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the full result graph plus an auditable code-computed summary."""

    payload = json_safe(dict(result))
    payload["export_contract_version"] = "claimguard.case-result.v1"
    payload["computed_export_summary"] = compute_financial_summary(result).as_export_dict()
    payload["computed_letter_lines"] = [
        line.as_export_dict() for line in approved_challenge_lines(result)
    ]
    return payload


def join_human(values: Iterable[Any]) -> str:
    return ", ".join(str(value) for value in values if value not in (None, ""))
