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
    # Bare "Claim" is a section heading. Only the explicit "Claim:" form
    # is read as an identifier in _read_cell; printed conflicts must remain
    # visible to the pairing engine rather than being hidden by extraction.
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
    # "Insured Name" is listed beside the bare "Insured" because the loose
    # prefix match in ``_read_cell`` takes the longest label it knows: without
    # it the EXL invoice's run-on cell "Insured Name John Smith" matches
    # "Insured" and leaves the label's own second word on the value
    # ("Name John Smith").
    "customer_name": ("DL policyholder", "Reference Name", "Insured Name", "Insured"),
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

# ponytail: WHERE A FIELD VALUE ENDS.
#
# A grid row normally reaches this module with its columns intact, and the
# value is simply the first cell after the label -- ``Registration Number``,
# ``AB12XYZ``, ``WITH A/C`` are three cells and only the second is the value.
# Some renderers collapse the gap between two columns to a single space, and
# the reader is then handed one run-on cell carrying the label, its value and
# whatever the neighbouring column printed on the same row.  That is how the
# running app stored registration ``AB12XYZ WITH A/C`` and model ``140 SE Nav
# FROM 06/2017`` for Format 1, whose Vehicle Details grid is printed beside
# the free-text Model Options list (``FROM 06/2017 · MODEL i30 · HEAT
# ABSORBING GLASS · WITH A/C · ...``, one item per grid row).
#
# A shape says what the printed value looks like.  It is NOT licence to cut
# wherever it happens to stop: truncating an identifier is worse than leaving
# a visible tail on it, because a truncated key still compares.  Two real
# examples from this corpus: ``245338996 / 1`` cut to ``245338996`` conflicts
# with the invoice's ``245338996/1`` and refuses a correct pair, and
# ``245338996 / 1`` and ``245338996 / 2`` -- two claims on one policy, per
# ``domain.normalisation`` -- cut to the same string and pair *each other* at
# full confidence.
#
# So a shape may cut only where there is positive evidence that a column break
# was lost, and ``_trim_to_value`` demands both:
#
#   1. the cut falls on a whitespace boundary.  A shape that stops in the
#      middle of a printed token has found nothing -- ``MH12AB1234`` is one
#      registration, not ``MH12AB``; ``WF0AXXWPMA BR12345`` is one VIN.
#   2. the discarded tail opens with an alphabetic word.  Free text from a
#      neighbouring column starts with a word (``WITH A/C``, ``DRIVER SEAT
#      HEIGHT``, ``Repairs Authorised?: TBA``); the continuation of an
#      identifier does not (``/ 1``, ``12 34``, ``BR12345``).
#
# Where the evidence is absent the whole remainder is kept.  That leaves
# visible garbage rather than a plausible wrong key, which is the trade this
# module wants: a value normalised into agreement is worse than no value.
#
# The shapes themselves describe what the client documents print, not an
# assumption that identifiers have no spaces -- ``normalisation.py`` exists
# precisely because they do (``"245338996 / 1" -> "245338996/1"``).
#
# Fields with no fixed shape -- make, model, customer names, addresses, notes
# -- declare none and keep the whole remainder.  There is nothing to cut them
# on, and a guess would silently truncate a genuine multi-word value
# (``140 SE Nav``, ``KAROQ SE TSI 115]``) or a two-line address.  Multi-line
# values are never affected either way: the reader takes at most one line for
# a value and never concatenates two.
#: An identifier is one token, or several joined by ``/`` or ``~`` with the
#: spacing the client's documents print around the separator.
_IDENTIFIER_SHAPE = re.compile(r"\S+(?:\s*[/~]\s*\S+)*")
#: UK registrations, longest form first: current ``AB12 XYZ`` / ``AB12XYZ``,
#: prefix ``ABC1234`` / ``A30DRY``, Northern Irish ``GAZ 1234``, and dateless
#: ``1 ABC`` / ``JB 007``.
_REGISTRATION_SHAPE = re.compile(
    r"[A-Za-z]{2}[0-9]{2}\s?[A-Za-z]{3}"
    r"|[A-Za-z]{1,3}[0-9]{1,4}[A-Za-z]{0,3}"
    r"|[A-Za-z]{1,3}\s[0-9]{1,4}"
    r"|[0-9]{1,4}\s[A-Za-z]{1,3}"
)
VALUE_SHAPES: dict[str, re.Pattern[str]] = {
    "registration": _REGISTRATION_SHAPE,
    "vin": re.compile(r"[A-Za-z0-9]{8,20}"),
    "claim_reference": _IDENTIFIER_SHAPE,
    "policy_number": _IDENTIFIER_SHAPE,
    "assessment_number": _IDENTIFIER_SHAPE,
    "invoice_number": _IDENTIFIER_SHAPE,
}

#: Printed column and section headings that are never half of a label/value
#: pair.  Every DL Auda report prints ``Model Options`` as the heading of the
#: free-text column beside Vehicle Details, and ``Model Sheet Number`` as a
#: label in that grid; both begin with the ``Model`` synonym, so without this
#: set a collapsed render reads ``Model Options`` as model ``Options`` and a
#: blank ``Model Sheet Number:`` (format 4 prints one) as model
#: ``Sheet Number:``.  They are also never a value for the label above them.
COLUMN_HEADINGS = frozenset(
    {
        "model options",
        "model sheet number",
        "vehicle details",
        "vehicle condition",
        "summary information",
        "repair information",
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
#: A token of letters only -- how free text from a neighbouring column opens.
_WORD_PATTERN = re.compile(r"[A-Za-z]+")
#: A single English-looking word: ``Are``, ``Options``, ``the``.  Capitalised
#: or lower case, never all capitals, because the identifiers this corpus
#: prints are capitalised throughout (``PH``, ``TBA``, ``PL-739284``).
_PROSE_WORD_PATTERN = re.compile(r"[A-Z][a-z]+|[a-z]+")


def _is_prose_word(value: str) -> bool:
    return _PROSE_WORD_PATTERN.fullmatch(value) is not None


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

    if _normalise_label(cell) in COLUMN_HEADINGS:
        return None, "", False
    label, separator, remainder = cell.partition(":")
    if separator and _normalise_label(label) == "claim":
        return "claim_reference", remainder.strip(), True
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


def _trim_to_value(field: str, remainder: str) -> str:
    """Cut a run-on cell's remainder where a lost column break can be proved.

    Only the remainder is cut, never a neighbouring cell: a cell boundary is
    already a value boundary, and a document that prints ``Policy Number`` and
    ``AB 12 34`` in two cells means all of it.  The two conditions a cut must
    satisfy, and why, are documented on ``VALUE_SHAPES``.
    """

    shape = VALUE_SHAPES.get(field)
    if shape is None or not remainder:
        return remainder
    match = shape.match(remainder)
    if match is None:
        return remainder
    tail = remainder[match.end() :]
    if not tail.strip():
        return match.group(0)
    if not tail[:1].isspace():
        # The shape stopped inside a printed token, so it has not found the
        # end of anything.
        return remainder
    if _WORD_PATTERN.fullmatch(tail.split()[0].strip(",.;:")) is None:
        # The tail could be the rest of this value rather than the next
        # column, so there is no evidence to cut on.
        return remainder
    return match.group(0)


def _borrows_another_label(cell: str) -> bool:
    """True when ``cell`` is another field's label/value cell, not a value.

    ``Policy Number:`` printed with a blank value and ``VAT Status: Non
    Taxable`` in the next column is one grid row with two pairs on it, not a
    policy number of ``VAT Status: Non Taxable``.  A loose match counts only
    when the cell prints a colon, so a genuine value that merely opens with a
    label word (``Model X``) is still read as a value.
    """

    if _normalise_label(cell) in COLUMN_HEADINGS:
        return True
    field, _remainder, strict = _read_cell(cell)
    if field is None:
        return False
    return strict or ":" in cell


def _pick_value(field: str, remainder: str, candidates: list[str]) -> str | None:
    options = [
        value
        for value in (_trim_to_value(field, remainder), *candidates)
        if value and not _is_label(value) and not _borrows_another_label(value)
    ]
    if field in VALUE_SHAPES:
        # A shaped field's value is an identifier, and an identifier is never
        # a bare English word.  Format 1's Summary grid prints ``Policy Number
        # | (blank) | Are the repairs authorized | Yes``; collapsed, that
        # offers ``Are``, which normalises and compares like a redacted
        # reference and would pair any two format-1 assessments on a policy
        # number neither document prints.  All-capital tokens are kept: format
        # 1's policy number really is printed ``PH``.
        options = [value for value in options if not _is_prose_word(value)]
    if not options:
        return None
    if field in MONEY_FIELDS:
        # An amount has digits in it.  ``VAT Status: Non Taxable`` sits beside
        # the VAT total on every DL Auda grid and is not one.
        options = [value for value in options if any(char.isdigit() for char in value)]
        if not options:
            return None
        for option in options:
            amount = _AMOUNT_PATTERN.search(option)
            if amount:
                # The amount itself, not the words printed around it.  Client
                # formats 3 and 4 print "VAT at 20%: £400.14", whose label is
                # only a loose "VAT" match, so this reader is handed "at 20%:
                # £400.14" -- and the first number in that string is the rate,
                # not the total.
                return amount.group(0).strip()
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

    A value is one cell, or one line, or -- when a renderer collapsed two
    columns into a single run-on cell and the field declares a shape -- the
    leading part of that cell, but only where a lost column break can be
    proved.  See ``VALUE_SHAPES`` for what counts as proof and why the reader
    would rather keep a visible tail than invent a shorter key.

    A neighbouring cell that is itself a label/value cell is not this field's
    value: ``Policy Number:`` beside ``VAT Status: Non Taxable`` yields no
    policy number.  A neighbouring cell that carries no recognised label is
    still taken whole, because a cell boundary is a value boundary.
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
