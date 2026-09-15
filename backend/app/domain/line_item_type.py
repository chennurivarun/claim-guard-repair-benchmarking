"""Open vocabulary for the section a line item sat in.

This is deliberately *not* a database enum. `LineItemKind` says what a row is
(and drives mapping, benchmarkability and the ontology); `line_item_type` says
which printed section the row came from. The client asked for a set that grows
when a new section appears ("if a new invoice shows Total ABC, add ABC"), so an
unrecognised heading is slugged into a new code rather than rejected. Enumerate
the live values with `SELECT DISTINCT line_item_type`.
"""

from __future__ import annotations

import re

MAX_CODE_LENGTH = 40

UNKNOWN = "unknown"

CANONICAL_TYPES: tuple[str, ...] = (
    "parts",
    "extras",
    "labour",
    "paint",
    "paint_materials",
    "specialist_operation",
    "sundry",
    "discount",
    UNKNOWN,
)

# Canonical code -> the section headings seen in client documents, including the
# rolled-up total labels an invoice prints instead of a section. Matching is
# case-, whitespace- and punctuation-insensitive ("&" reads as "and"), so only
# genuinely different wordings need an entry here.
#
# "extras" is the single code for every extras / additional spelling: the invoice
# total "Additional charges" must find the assessment's EXTRAS rows, so the two
# sides cannot carry different codes. "additional" is accepted as an alias.
SECTION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "parts": ("Parts", "Total Parts", "Total Parts Amount", "Parts Total"),
    "extras": (
        "Extras",
        "Extra",
        "Total Extras",
        "Additional",
        "Additional Items",
        "Additional charges",
        "Additional Costs",
        "Total Additional Costs",
        "Additional Total Items",
    ),
    "labour": (
        "Labour",
        "Total Labour",
        "Total Labour Amount",
        "Total Panel/Mechanical Labour",
        "Total Panel/Mechanical",
    ),
    "paint": ("Paint Work", "Paint Labour", "Total Paintwork"),
    "paint_materials": (
        "Paint and Materials",
        "Paint & Materials",
        "Total Paint and Materials",
        "Total Paint & Materials",
        "Total Paint & Materials Amount",
        "Total Paint / Materials Costs",
    ),
    "specialist_operation": ("Specialist Operation",),
    "sundry": ("Sundry parts",),
    "discount": ("Deduction", "Discount", "Deductions", "Overall Discount"),
    UNKNOWN: (),
}


def _match_key(value: str) -> str:
    """Collapse a heading to its comparison form: lowercase words, "&" as "and"."""

    text = value.replace("&", " and ").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_LOOKUP: dict[str, str] = {
    **{_match_key(code): code for code in CANONICAL_TYPES},
    **{
        _match_key(heading): code
        for code, headings in SECTION_SYNONYMS.items()
        for heading in headings
    },
}


def ensure_line_item_type(raw: str | None) -> str:
    """Return the canonical code for a section heading, never raising.

    A known heading maps to its canonical code; anything else becomes a slug of
    itself (lowercase letters, digits and underscores, at most 40 characters) so
    a new section starts recording rows immediately. Blank input is "unknown".
    """

    if raw is None:
        return UNKNOWN
    key = _match_key(str(raw))
    if not key:
        return UNKNOWN
    known = _LOOKUP.get(key)
    if known is not None:
        return known
    return key.replace(" ", "_")[:MAX_CODE_LENGTH].strip("_") or UNKNOWN
