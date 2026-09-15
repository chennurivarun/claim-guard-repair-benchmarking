"""Shared label/value reader for Audatex-style assessment and invoice headers.

Both parsers need to recover the same identity and total fields from documents
that print them in four different shapes:

1. ``Label: value`` on one line;
2. a two-column grid on one line, cells separated by 2+ spaces, with up to two
   label/value pairs per line — ``Claim Reference   245338996/1   Reference
   Name   John Doe`` (this is what ``docx_ingest._table_row_text`` emits);
3. the label on one line and its value on the next;
4. a label carrying trailing punctuation followed by an amount —
   ``VAT 20%   982.52``, ``Total Parts   1,237.50``.

Reading them in one place is the whole point of this module: the divergence
between ``engineer_assessment_parser.FIELD_PATTERNS`` and
``invoice_parser._header`` is what this replaces.  Values are returned raw so
callers keep full control of coercion; ``parse_money`` and ``parse_date`` are
offered here so the two parsers share one implementation.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from app.domain.money import as_decimal

FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "claim_reference": (
        "Claim Number",
        "Claim Reference",
        "DL Claim number",
        "Claim No",
        "Claim Ref",
    ),
    "policy_number": ("Policy Number", "Policy No", "DL Policy number"),
    "registration": (
        "Registration Number",
        "Vehicle Registration",
        "Reg. No",
        "Reg No",
        "Registration",
    ),
    "assessment_number": (
        "Assessment Number",
        "Assessment Ref",
        "Assessment Reference",
        "Estimate ID",
    ),
    "vehicle_make": ("Manufacturer", "Vehicle Make", "Make"),
    "vehicle_model": ("Model", "Vehicle Model"),
    "vin": ("VIN Number", "VIN", "Chassis Number"),
    "invoice_number": ("Invoice Number", "Invoice No", "Invoice #"),
    "invoice_date": ("Invoice Date",),
    "incident_date": ("Date of accident", "Date of Incident", "Accident Date"),
    "authorisation_status": ("Authorisation Status", "Authorization Status"),
    "customer_name": ("DL policyholder", "Reference Name", "Insured"),
    "mileage": ("Odometer", "Mileage"),
    "labour_rate": ("Labour Rate",),
    "paint_rate": ("Paint Rate",),
    "labour_net": ("Total Labour", "Total Labour Amount", "TOTAL PANEL/MECHANICAL LABOUR"),
    "paint_net": (
        "Total Paint / Materials Costs",
        "Total Paint & Materials Amount",
        "Total Paint & materials",
        "Total Paint and Materials",
    ),
    "parts_net": ("Total Parts", "Total Parts Amount", "Parts Total"),
    "extras_net": (
        "Total Extras",
        "Total Additional Costs",
        "Additional charges",
        "Additional Items",
        "Additional Total Items",
    ),
    # ponytail: the bare label "Total" is deliberately NOT a subtotal synonym; it
    # heads every schedule ("Total   136.32" under Specialist Operation) and the
    # parsers own section totals themselves.
    "subtotal_net": ("Grand Total Excl. VAT", "Repair Grand Total Excl. VAT", "Subtotal"),
    "vat_total": (
        "VAT 20%",
        "An amount equivalent to VAT @20%",
        "Sum Equivalent to VAT @20%",
        "VAT",
    ),
    "gross_total": (
        "Grand Total Incl. VAT",
        "Invoice Total",
        "Invoice total",
        "Total Due",
        "Grand Total",
    ),
}

#: Fields whose value is an amount.  For these a candidate that looks like an
#: amount is preferred over a candidate that merely sits in the next cell.
MONEY_FIELDS = frozenset(
    {
        "labour_rate",
        "paint_rate",
        "labour_net",
        "paint_net",
        "parts_net",
        "extras_net",
        "subtotal_net",
        "vat_total",
        "gross_total",
    }
)

# ponytail: an amount is recognised only with two decimal places (optionally
# £-prefixed).  A money total printed without pence falls back to the generic
# "first non-empty candidate" rule rather than being preferred.
_AMOUNT_PATTERN = re.compile(r"£?\s*\d[\d,]*\.\d{2}\b")
_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_DATE_PATTERN = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_CELL_SPLIT = re.compile(r"\s{2,}")
_SUMMARY_HEADING = re.compile(r"(?i)^\s*summary information\b")


def _normalise_label(value: str) -> str:
    """Case-fold, drop full stops, collapse whitespace, shed trailing punctuation.

    Dropping full stops lets one synonym cover both ``Grand Total Excl. VAT``
    and ``Grand Total Excl VAT`` (and ``Reg. No`` / ``Reg No``).  The trailing
    strip covers ``Claim Reference:``, ``VAT 20%`` and ``... VAT @20%``; it is
    applied identically to the synonym table and to text, so only consistency
    matters.
    """

    collapsed = " ".join(value.replace(".", "").split()).lower()
    return collapsed.rstrip(": -–—%@").strip()


_LABEL_INDEX: dict[str, str] = {}
for _field, _labels in FIELD_SYNONYMS.items():
    for _label in _labels:
        _LABEL_INDEX.setdefault(_normalise_label(_label), _field)

_MAX_LABEL_WORDS = max(len(key.split()) for key in _LABEL_INDEX)


def _read_cell(cell: str) -> tuple[str | None, str, bool]:
    """Match a label at the head of ``cell``.

    Returns ``(field, remainder, strict)``.  A strict match is one where the
    whole cell is the label, or the cell is ``Label: value`` — the shapes a
    real grid produces.  A loose match is a longest-label-first prefix of a
    single run-on cell, used only when nothing stricter claimed the field.
    """

    label, separator, remainder = cell.partition(":")
    if separator:
        field = _LABEL_INDEX.get(_normalise_label(label))
        if field:
            return field, remainder.strip(), True
    field = _LABEL_INDEX.get(_normalise_label(cell))
    if field:
        return field, "", True
    words = cell.split()
    # Longest label first, so "Total Paint & Materials Amount" is never eaten
    # by "Total".
    for size in range(min(len(words), _MAX_LABEL_WORDS), 0, -1):
        field = _LABEL_INDEX.get(_normalise_label(" ".join(words[:size])))
        if field:
            return field, " ".join(words[size:]).strip(), False
    return None, "", False


def _is_label(value: str) -> bool:
    return _LABEL_INDEX.get(_normalise_label(value)) is not None


def _next_line_value(rows: list[list[str]], index: int) -> str | None:
    """The value of a label printed on its own line (layout 3)."""

    for cells in rows[index + 1 :]:
        populated = [cell for cell in cells if cell]
        if not populated:
            continue
        if len(populated) == 1 and not _is_label(populated[0]):
            return populated[0]
        return None
    return None


def _pick_value(field: str, remainder: str, candidates: list[str]) -> str | None:
    options = [value for value in ([remainder, *candidates]) if value and not _is_label(value)]
    if not options:
        return None
    if field in MONEY_FIELDS:
        for option in options:
            if _AMOUNT_PATTERN.search(option):
                return option
    return options[0]


def read_label_values(text: str) -> dict[str, str]:
    """Recover canonical field values from a label/value document.

    Values are returned exactly as printed apart from surrounding whitespace,
    so ``KAROQ SE TSI 115]`` keeps its stray bracket and ``£38.00`` keeps its
    currency sign.  A label with a blank value yields no key at all.

    Precedence, highest first: a value under a ``Summary Information`` heading;
    a strict (whole-cell or ``Label: value``) match; earliest occurrence.  That
    is what makes Format 1 report ``assessment_number = "D7576879"`` from the
    summary grid rather than ``L0987892222`` from the page-1 header band.
    """

    lines = (text or "").splitlines()
    rows = [[cell.strip() for cell in _CELL_SPLIT.split(line.strip())] for line in lines]
    summary_at = next(
        (index for index, line in enumerate(lines) if _SUMMARY_HEADING.match(line)), None
    )
    values: dict[str, str] = {}
    ranks: dict[str, tuple[int, int, int]] = {}
    order = 0
    for index, cells in enumerate(rows):
        # ponytail: the summary block is treated as running to the end of the
        # text.  Later running-header bands therefore share its tier, but lose
        # on occurrence order to the grid, which is the behaviour required.
        tier = 0 if summary_at is not None and index >= summary_at else 1
        for position, cell in enumerate(cells):
            order += 1
            if not cell:
                continue
            field, remainder, strict = _read_cell(cell)
            if field is None:
                continue
            tail = [value for value in cells[position + 1 :] if value]
            if not tail and not remainder:
                following = _next_line_value(rows, index)
                tail = [following] if following else []
            value = _pick_value(field, remainder, tail)
            if value is None:
                continue
            rank = (tier, 0 if strict else 1, order)
            if field not in ranks or rank < ranks[field]:
                ranks[field] = rank
                values[field] = value
    return values


def parse_money(value: str) -> Decimal | None:
    """Coerce a printed amount — ``£38.00``, ``1,237.50`` — to a Decimal."""

    match = _NUMBER_PATTERN.search(value or "")
    if not match:
        return None
    try:
        return as_decimal(match.group(0))
    except ValueError:
        return None


def parse_date(value: str) -> date | None:
    """Coerce ``dd/mm/yyyy`` or ``d/m/yyyy`` to a date.

    # ponytail: day-first only.  Every client document prints UK dates, and
    # guessing between 2/3/2023 and 3/2/2023 from content is not decidable.
    """

    match = _DATE_PATTERN.search(value or "")
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
