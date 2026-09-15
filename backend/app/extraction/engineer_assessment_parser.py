"""Deterministic extraction for Audatex-style engineer assessment reports.

The parser deliberately treats the report as evidence, never as an invoice.
Identity and totals come from :mod:`app.extraction.label_grid`, the one shared
label/value reader; the repair schedule is read section by section so every
operation carries the printed heading it sat under.

Two governing rules:

* **Printed totals are never reconciled against the rows.** Format 1 prints
  ``Total Work Units 218`` against 101 work units of rows and Format 7 prints
  ``300``/``113.2`` against ``101``/``151``.  Both are persisted exactly as
  printed; row sums are exposed separately (``row_work_units``/``row_totals``)
  so the calculation checks can raise the disagreement as a finding.
* **A price is never guessed.** Work units persist with ``unit_price``/``total``
  of ``None`` unless a rate was actually printed, in which case the row is
  flagged ``price_derived``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.domain.line_item_type import ensure_line_item_type
from app.extraction.invoice_parser import PARTS_SCHEDULE_ROW_PATTERN
from app.extraction.label_grid import parse_date, parse_money, read_label_values
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
    line_item_type: str = "unknown"
    raw_category: str | None = None
    # ponytail: ``part_number_raw`` keeps the literal printed in the part-number
    # column ("Renew") that ``part_number`` deliberately drops.  It is payload
    # only -- ``assessment_operations`` has no column for it.
    part_number: str | None = None
    part_number_raw: str | None = None
    price_derived: bool = False


@dataclass
class ParsedEngineerAssessment:
    fields: dict[str, object] = field(default_factory=dict)
    operations: list[ParsedOperation] = field(default_factory=list)
    confidence: float = 0.0
    #: Work-unit totals exactly as printed, keyed by ``line_item_type``.
    printed_work_units: dict[str, Decimal] = field(default_factory=dict)
    #: Money totals exactly as printed ("Sub Total", "Sundry Parts", ...).
    printed_totals: dict[str, Decimal] = field(default_factory=dict)
    #: Sum of the parsed rows, for comparison against the printed figures.
    row_work_units: dict[str, Decimal] = field(default_factory=dict)
    row_totals: dict[str, Decimal] = field(default_factory=dict)


#: Fields written straight onto ``EngineerAssessment``; anything else
#: ``read_label_values`` recovers (invoice number, customer name, ...) belongs
#: to the invoice side and is dropped here.
ASSESSMENT_FIELDS: tuple[str, ...] = (
    "assessment_number",
    "claim_reference",
    "policy_number",
    "created_date",
    "incident_date",
    "authorisation_status",
    "registration",
    "vin",
    "vehicle_make",
    "vehicle_model",
    "vehicle_variant",
    "mileage",
    "pre_accident_condition",
    "impact_severity",
    "roadworthiness",
    "damage_areas",
    "labour_rate",
    "paint_rate",
    "labour_net",
    "paint_net",
    "parts_net",
    "extras_net",
    "subtotal_net",
    "vat_rate",
    "vat_total",
    "gross_total",
)

MONEY_FIELDS = {
    "labour_rate", "paint_rate", "labour_net", "paint_net", "parts_net",
    "extras_net", "subtotal_net", "vat_rate", "vat_total", "gross_total",
}

DATE_FIELDS = {"created_date", "incident_date"}

# ponytail: labels the shared ``FIELD_SYNONYMS`` table does not carry, because
# only the governed prototype report prints them.  Read as a fallback so the
# older fixture keeps populating the same columns.
RESIDUAL_LABELS: dict[str, tuple[str, ...]] = {
    "created_date": ("Created",),
    "vehicle_variant": ("Variant",),
    "pre_accident_condition": ("Pre-Accident Condition", "Pre accident"),
    "impact_severity": ("Severity of Impact",),
    "roadworthiness": ("Vehicle Status on Inspection",),
    "damage_areas": ("Damage Areas",),
    "vat_rate": ("VAT Rate",),
}

# Heading -> the section a row sits in.  An unrecognised heading that is
# followed by a column header becomes a new code via ``ensure_line_item_type``;
# that is how "add ABC when a new section appears" works without a code change.
_SECTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)^paint\s*work\b"), "paint"),
    (re.compile(r"(?i)^paint\s*(?:and|&)\s*materials\b"), "paint_materials"),
    (re.compile(r"(?i)^labour\b"), "labour"),
    (re.compile(r"(?i)^parts\b"), "parts"),
    (re.compile(r"(?i)^extras\b"), "extras"),
    (re.compile(r"(?i)^additional\s+items\b"), "extras"),
    (re.compile(r"(?i)^specialist\s+operation"), "specialist_operation"),
)

_WORK_UNIT_TYPES = {"labour", "paint"}

_CELL_SPLIT = re.compile(r"\s{2,}")
_COLUMN_HEADER = re.compile(
    r"(?i)^(?:guide\s*(?:no\.?|number)|number|description)\b.*\b(?:wu|price)\s*$"
)
_BARE_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_PRICE_CELL = re.compile(r"^£?\s*\d[\d,]*(?:\.\d{1,2})?$")
_TOTAL_LABEL = re.compile(r"(?i)^(?:total|sub[ -]?total|sundry|deduction)\b")
_TOTAL_WORK_UNITS = re.compile(r"(?i)^total\s+work\s+units$")
_HOURS_SUFFIX = re.compile(r"(?i)^(.*?)\s+[\d.]+\s*hours$")
_NO_NUMBER = re.compile(r"(?i)^no\s*[nm][uo]mber$")
_TIME_BASIS = re.compile(r"(?i)time\s*basis\s*(\d+)\s*wu\s*=\s*1\s*hr")
_INLINE_RATE = re.compile(
    r"(?i)time\s*basis\s*(\d+)\s*wu\s*=\s*1\s*hr\.?\s*price\s*£?\s*([\d,.]+)\s*/\s*hr"
)
# ponytail: reuses ``PARTS_SCHEDULE_ROW_PATTERN`` for the numeric part-number
# case and only adds the "Renew" placeholder the client files print.
_PARTS_RENEW_ROW_PATTERN = re.compile(
    r"^(?P<guide>\d{3,5})\s+(?P<description>[A-Za-z].*?)\s+"
    r"(?P<part_number>Renew)\s+(?P<discount>\d{1,3}(?:\.\d+)?)\s*%\s+"
    r"£?(?P<price>\d[\d,]*\.\d{2})\s*$",
    re.IGNORECASE,
)

_PENNY = Decimal("0.01")


@dataclass
class _Section:
    heading: str
    line_item_type: str
    kind: str
    wu_per_hour: Decimal = Decimal("10")
    rate: Decimal | None = None


def _next_non_blank(lines: list[str], index: int) -> str | None:
    for candidate in lines[index + 1 :]:
        if candidate.strip():
            return candidate.strip()
    return None


def _residual_fields(text: str) -> dict[str, str]:
    """Read the labels the shared synonym table does not cover.

    Native PDF extraction commonly places a table label and its value on
    consecutive lines; the pre-pass folds that back into ``Label: value`` before
    the label patterns run.
    """

    values: dict[str, str] = {}
    for name, labels in RESIDUAL_LABELS.items():
        for label in labels:
            escaped = re.escape(label)
            folded = re.sub(
                rf"(?im)^({escaped})[ \t]*$\n[ \t]*([^\n]+)$", r"\1: \2", text
            )
            match = re.search(
                rf"(?im)^[ \t]*{escaped}[ \t]*:[ \t]*([^\n]+?)[ \t]*$", folded
            )
            if match:
                values[name] = match.group(1).strip()
                break
    return values


def _coerce(name: str, value: str) -> object | None:
    if name in DATE_FIELDS:
        return parse_date(value)
    if name in MONEY_FIELDS:
        return parse_money(value)
    if name == "mileage":
        amount = parse_money(value)
        return int(amount) if amount is not None else None
    if name == "damage_areas":
        return [part.strip() for part in value.split(",") if part.strip()] or None
    return value


def _read_fields(combined: str) -> dict[str, object]:
    raw = {**_residual_fields(combined), **read_label_values(combined)}
    fields: dict[str, object] = {}
    for name in ASSESSMENT_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        coerced = _coerce(name, value)
        if coerced is not None:
            fields[name] = coerced
    return fields


def _open_section(heading: str, code: str, header: str | None) -> _Section:
    if header:
        lowered = header.lower()
        if re.search(r"\bwu\b", lowered):
            kind = "work_unit"
        elif "part number" in lowered:
            kind = "parts"
        else:
            kind = "priced"
    elif code in _WORK_UNIT_TYPES:
        kind = "work_unit"
    else:
        kind = "parts" if code == "parts" else "priced"
    return _Section(heading=heading, line_item_type=code, kind=kind)


def _section_start(stripped: str, cells: list[str], lines: list[str], index: int) -> _Section | None:
    """A heading is a short, single-cell, colon-free line of words."""

    if len(cells) != 1 or ":" in stripped or len(stripped.split()) > 5:
        return None
    if not re.search(r"[A-Za-z]", stripped):
        return None
    header = _next_non_blank(lines, index)
    for pattern, code in _SECTIONS:
        if pattern.match(stripped):
            return _open_section(stripped, code, header)
    if header and _COLUMN_HEADER.match(header):
        return _open_section(stripped, ensure_line_item_type(stripped), header)
    return None


def _rate_for(section: _Section, fields: dict[str, object]) -> Decimal | None:
    """Inline section rate first, then the Calculation block, then nothing."""

    if section.rate is not None:
        return section.rate
    name = "paint_rate" if section.line_item_type == "paint" else "labour_rate"
    rate = fields.get(name)
    return rate if isinstance(rate, Decimal) else None


def _accumulate(bucket: dict[str, Decimal], key: str, value: Decimal) -> None:
    bucket[key] = bucket.get(key, Decimal("0")) + value


def parse_engineer_assessment(pages: list[PageAnalysis]) -> ParsedEngineerAssessment:
    combined = "\n".join(page.text for page in pages)
    parsed = ParsedEngineerAssessment(fields=_read_fields(combined))

    if parsed.fields.get("gross_total") is None:
        subtotal = parsed.fields.get("subtotal_net")
        vat_total = parsed.fields.get("vat_total")
        if isinstance(subtotal, Decimal) and isinstance(vat_total, Decimal):
            parsed.fields["gross_total"] = subtotal + vat_total

    sequence = 0
    section: _Section | None = None
    for page in pages:
        lines = page.text.splitlines()
        # A wrapped description is only ever the line directly under its row.
        pending: tuple[int, int] | None = None
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.upper().startswith("OP|"):
                operation = _governed_operation(stripped, sequence + 1, page.page_number)
                if operation is not None:
                    sequence += 1
                    parsed.operations.append(operation)
                pending = None
                continue

            # Before heading detection: "Time Basis 10 WU=1HR." sits directly
            # under its section heading and above the column header, so it
            # would otherwise read as a heading of its own.
            basis = _INLINE_RATE.search(stripped) or _TIME_BASIS.search(stripped)
            if basis is not None and section is not None:
                section.wu_per_hour = Decimal(basis.group(1)) or Decimal("10")
                if basis.re is _INLINE_RATE:
                    section.rate = parse_money(basis.group(2))
                pending = None
                continue

            cells = [cell.strip() for cell in _CELL_SPLIT.split(stripped)]
            started = _section_start(stripped, cells, lines, index)
            if started is not None:
                section = started
                pending = None
                continue
            if section is None:
                continue

            if len(cells) >= 2 and _TOTAL_LABEL.match(cells[0]):
                _record_printed_total(parsed, section, cells)
                pending = None
                continue

            operation = _schedule_operation(
                parsed, section, cells, stripped, sequence + 1, page.page_number
            )
            if operation is not None:
                sequence += 1
                parsed.operations.append(operation)
                pending = (index, len(parsed.operations) - 1)
                continue

            if pending is not None and pending[0] == index - 1 and len(cells) == 1:
                parsed.operations[pending[1]] = _with_continuation(
                    parsed.operations[pending[1]], stripped
                )
                pending = (index, pending[1])

    required = ("assessment_number", "claim_reference", "registration", "gross_total")
    found = sum(1 for field_name in required if parsed.fields.get(field_name) is not None)
    parsed.confidence = min(0.70 + found * 0.05 + min(len(parsed.operations), 5) * 0.02, 0.99)
    if not any(
        parsed.fields.get(name)
        for name in ("assessment_number", "claim_reference", "registration")
    ):
        raise ValueError("Engineer assessment is missing every identifying reference.")
    return parsed


def _governed_operation(line: str, sequence: int, page_number: int) -> ParsedOperation | None:
    # OP|category|code|description|work units|hours|quantity|unit price|total
    parts = [part.strip() for part in line.split("|")]
    if len(parts) != 9:
        return None
    return ParsedOperation(
        sequence_no=sequence,
        category=parts[1].lower(),
        code=parts[2] or None,
        description=parts[3],
        work_units=parse_money(parts[4]),
        hours=parse_money(parts[5]),
        quantity=parse_money(parts[6]),
        unit_price=parse_money(parts[7]),
        total=parse_money(parts[8]),
        page_number=page_number,
        # ponytail: the governed format's singular "extra" has no synonym, so it
        # slugs to its own code rather than joining "extras".
        line_item_type=ensure_line_item_type(parts[1]),
        raw_category=parts[1],
    )


def _record_printed_total(
    parsed: ParsedEngineerAssessment, section: _Section, cells: list[str]
) -> None:
    value = parse_money(cells[-1])
    if value is None:
        return
    label = cells[0]
    if _TOTAL_WORK_UNITS.match(label):
        parsed.printed_work_units[section.line_item_type] = value
        return
    hours = _HOURS_SUFFIX.match(label)
    parsed.printed_totals[ensure_line_item_type(hours.group(1) if hours else label)] = value


def _schedule_operation(
    parsed: ParsedEngineerAssessment,
    section: _Section,
    cells: list[str],
    line: str,
    sequence: int,
    page_number: int,
) -> ParsedOperation | None:
    if section.kind == "parts":
        return _parts_operation(parsed, section, line, sequence, page_number)
    if section.kind == "work_unit":
        return _work_unit_operation(parsed, section, cells, sequence, page_number)
    return _priced_operation(parsed, section, cells, sequence, page_number)


def _work_unit_operation(
    parsed: ParsedEngineerAssessment,
    section: _Section,
    cells: list[str],
    sequence: int,
    page_number: int,
) -> ParsedOperation | None:
    if len(cells) < 2 or not _BARE_NUMBER.match(cells[-1]):
        return None
    if len(cells) >= 3:
        code: str | None = cells[0]
        description = " ".join(cells[1:-1])
    else:
        code = None
        description = cells[0]
    if not re.search(r"[A-Za-z]", description):
        return None
    if code and _NO_NUMBER.match(code):
        code = None
    work_units = parse_money(cells[-1])
    if work_units is None:
        return None
    rate = _rate_for(section, parsed.fields)
    hours: Decimal | None = None
    total: Decimal | None = None
    if rate is not None:
        hours = (work_units / section.wu_per_hour).quantize(_PENNY, rounding=ROUND_HALF_UP)
        total = (hours * rate).quantize(_PENNY, rounding=ROUND_HALF_UP)
        _accumulate(parsed.row_totals, section.line_item_type, total)
    _accumulate(parsed.row_work_units, section.line_item_type, work_units)
    return ParsedOperation(
        sequence_no=sequence,
        category=section.line_item_type,
        code=code or None,
        description=description,
        work_units=work_units,
        hours=hours,
        quantity=None,
        unit_price=rate,
        total=total,
        page_number=page_number,
        line_item_type=section.line_item_type,
        raw_category=section.heading,
        price_derived=rate is not None,
    )


def _parts_operation(
    parsed: ParsedEngineerAssessment,
    section: _Section,
    line: str,
    sequence: int,
    page_number: int,
) -> ParsedOperation | None:
    match = PARTS_SCHEDULE_ROW_PATTERN.match(line) or _PARTS_RENEW_ROW_PATTERN.match(line)
    if match is None:
        return None
    price = parse_money(match.group("price"))
    raw_part_number = match.group("part_number")
    part_number = None if raw_part_number.casefold() == "renew" else raw_part_number
    if price is not None:
        _accumulate(parsed.row_totals, section.line_item_type, price)
    return ParsedOperation(
        sequence_no=sequence,
        category=section.line_item_type,
        code=match.group("guide"),
        description=match.group("description").strip(),
        work_units=None,
        hours=None,
        quantity=Decimal("1"),
        unit_price=price,
        total=price,
        page_number=page_number,
        line_item_type=section.line_item_type,
        raw_category=section.heading,
        part_number=part_number,
        part_number_raw=raw_part_number,
    )


def _priced_operation(
    parsed: ParsedEngineerAssessment,
    section: _Section,
    cells: list[str],
    sequence: int,
    page_number: int,
) -> ParsedOperation | None:
    if len(cells) < 2 or not _PRICE_CELL.match(cells[-1]):
        return None
    description = cells[0]
    if not re.search(r"[A-Za-z]", description):
        return None
    price = parse_money(cells[-1])
    if price is None:
        return None
    _accumulate(parsed.row_totals, section.line_item_type, price)
    return ParsedOperation(
        sequence_no=sequence,
        category=section.line_item_type,
        code=None,
        description=description,
        work_units=None,
        hours=None,
        quantity=Decimal("1"),
        unit_price=price,
        total=price,
        page_number=page_number,
        line_item_type=section.line_item_type,
        raw_category=section.heading,
    )


def _with_continuation(operation: ParsedOperation, tail: str) -> ParsedOperation:
    """Fold a wrapped description line back onto the row it belongs to."""

    return ParsedOperation(
        **{
            **operation.__dict__,
            "description": f"{operation.description} {tail}".strip(),
        }
    )
