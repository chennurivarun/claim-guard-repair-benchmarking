"""Deterministic extraction for the governed Engineer Assessment prototype format.

The parser deliberately treats the report as evidence, never as an invoice.  It
accepts visible ``FIELD: value`` labels and pipe-delimited operation rows emitted
by the sample generator, while retaining the source page for every operation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.extraction.schemas import PageAnalysis


@dataclass(frozen=True)
class ParsedOperation:
    sequence_no: int
    category: str
    code: str | None
    description: str
    work_units: Decimal | None
    hours: Decimal | None
    quantity: Decimal | None
    unit_price: Decimal | None
    total: Decimal | None
    page_number: int


@dataclass
class ParsedEngineerAssessment:
    fields: dict[str, object] = field(default_factory=dict)
    operations: list[ParsedOperation] = field(default_factory=list)
    confidence: float = 0.0


FIELD_PATTERNS = {
    "assessment_number": r"Assessment Number\s*:\s*([^\n]+)",
    "claim_reference": r"Claim Reference\s*:\s*([^\n]+)",
    "policy_number": r"Policy Number\s*:\s*([^\n]+)",
    "created_date": r"Created\s*:\s*([^\n]+)",
    "incident_date": r"Date of Incident\s*:\s*([^\n]+)",
    "authorisation_status": r"Authorisation Status\s*:\s*([^\n]+)",
    "registration": r"Registration\s*:\s*([^\n]+)",
    "vin": r"VIN\s*:\s*([^\n]+)",
    "vehicle_make": r"Manufacturer\s*:\s*([^\n]+)",
    "vehicle_model": r"Model\s*:\s*([^\n]+)",
    "vehicle_variant": r"Variant\s*:\s*([^\n]+)",
    "mileage": r"Odometer\s*:\s*([\d,]+)",
    "pre_accident_condition": r"Pre-Accident Condition\s*:\s*([^\n]+)",
    "impact_severity": r"Severity of Impact\s*:\s*([^\n]+)",
    "roadworthiness": r"Vehicle Status on Inspection\s*:\s*([^\n]+)",
    "damage_areas": r"Damage Areas\s*:\s*([^\n]+)",
    "labour_rate": r"Labour Rate\s*:\s*£?([\d,.]+)",
    "paint_rate": r"Paint Rate\s*:\s*£?([\d,.]+)",
    "labour_net": r"Total Labour\s*:\s*£?([\d,.]+)",
    "paint_net": r"Total Paint/Material Costs\s*:\s*£?([\d,.]+)",
    "parts_net": r"Total Parts\s*:\s*£?([\d,.]+)",
    "extras_net": r"Total Additional Costs\s*:\s*£?([\d,.]+)",
    "subtotal_net": r"Grand Total Excl VAT\s*:\s*£?([\d,.]+)",
    "vat_rate": r"VAT Rate\s*:\s*([\d.]+)%",
    "vat_total": r"^VAT\s*:\s*£?([\d,.]+)",
    "gross_total": r"Grand Total Incl VAT\s*:\s*£?([\d,.]+)",
}

MONEY_FIELDS = {
    "labour_rate", "paint_rate", "labour_net", "paint_net", "parts_net",
    "extras_net", "subtotal_net", "vat_rate", "vat_total", "gross_total",
}


def _decimal(value: str | None) -> Decimal | None:
    if not value or value in {"-", "N/A"}:
        return None
    try:
        return Decimal(value.replace(",", "").replace("£", "").strip())
    except InvalidOperation:
        return None


def _date(value: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse_engineer_assessment(pages: list[PageAnalysis]) -> ParsedEngineerAssessment:
    combined = "\n".join(page.text for page in pages)
    # Native PDF extraction commonly places a table label and its value on
    # consecutive lines.  Normalise that representation before applying the
    # same governed field patterns used for colon-delimited reports.
    for pattern in FIELD_PATTERNS.values():
        label = pattern.split(r"\s*", 1)[0]
        combined = re.sub(
            rf"(?im)^({label})[ \t]*$\n[ \t]*([^\n]+)$",
            r"\1: \2",
            combined,
        )
    parsed = ParsedEngineerAssessment()
    for name, pattern in FIELD_PATTERNS.items():
        match = re.search(pattern, combined, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            continue
        value = match.group(1).strip()
        if name in {"created_date", "incident_date"}:
            parsed.fields[name] = _date(value)
        elif name in MONEY_FIELDS:
            parsed.fields[name] = _decimal(value)
        elif name == "mileage":
            parsed.fields[name] = int(value.replace(",", ""))
        elif name == "damage_areas":
            parsed.fields[name] = [part.strip() for part in value.split(",") if part.strip()]
        else:
            parsed.fields[name] = value

    if parsed.fields.get("gross_total") is None:
        subtotal = parsed.fields.get("subtotal_net")
        vat_total = parsed.fields.get("vat_total")
        if isinstance(subtotal, Decimal) and isinstance(vat_total, Decimal):
            parsed.fields["gross_total"] = subtotal + vat_total

    sequence = 0
    for page in pages:
        for line in page.text.splitlines():
            # OP|category|code|description|work units|hours|quantity|unit price|total
            if not line.strip().upper().startswith("OP|"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 9:
                continue
            sequence += 1
            parsed.operations.append(
                ParsedOperation(
                    sequence_no=sequence,
                    category=parts[1].lower(),
                    code=parts[2] or None,
                    description=parts[3],
                    work_units=_decimal(parts[4]),
                    hours=_decimal(parts[5]),
                    quantity=_decimal(parts[6]),
                    unit_price=_decimal(parts[7]),
                    total=_decimal(parts[8]),
                    page_number=page.page_number,
                )
            )
    required = ("assessment_number", "claim_reference", "registration", "gross_total")
    found = sum(1 for field_name in required if parsed.fields.get(field_name) is not None)
    parsed.confidence = min(0.70 + found * 0.05 + min(len(parsed.operations), 5) * 0.02, 0.99)
    if not parsed.fields.get("assessment_number") or not parsed.operations:
        raise ValueError("Engineer assessment is missing its identifier or repair operations.")
    return parsed
