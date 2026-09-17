from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from app.domain.line_item_type import ensure_line_item_type
from app.domain.money import as_decimal, money
from app.domain.normalisation import (
    normalise_description,
    normalise_unit,
    strip_scan_artifacts,
)
from app.extraction.label_grid import parse_money, read_label_values
from app.extraction.schemas import (
    BoundingBox,
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
    PageAnalysis,
)
from app.llm.base import LLMProviderError
from app.llm.invoice_extraction import MultimodalInvoiceExtractor, merge_invoice_extractions

MONEY_PATTERN = r"(?:£\s*)?([0-9][0-9,]*\.\d{2})"

# Audatex-style PARTS schedule row: guide number, description, part number,
# "Bet." discount percentage, price. Example:
# "1720   R/SCREW              0019846529   0%   2.80"
PARTS_SCHEDULE_ROW_PATTERN = re.compile(
    r"^(?P<guide>\d{3,5}(?:\s\d{2})?)\s+(?P<description>[A-Za-z].*?)\s+"
    r"(?P<part_number>\d{6,14})\s+(?P<discount>\d{1,3}(?:\.\d+)?)\s*%\s+"
    r"£?(?P<price>\d[\d,]*\.\d{2})\s*$"
)
# Generic priced schedule row: description followed by a trailing amount,
# optionally currency-prefixed. Example: "E.P.A. Charge     GBP 30.00".
PRICED_SCHEDULE_ROW_PATTERN = re.compile(
    r"^(?P<description>.+?)\s+(?:GBP|£)?\s*(?P<price>\d[\d,]*\.\d{2})\s*$",
    re.IGNORECASE,
)
SCHEDULE_SECTION_PATTERN = re.compile(
    r"^\s*(parts|extras|labour|paint work|paint (?:and|&) materials"
    r"|specialist operation|additional items)\b",
    re.IGNORECASE,
)
NON_SCHEDULE_LINE_TOKENS = (
    "total",
    "deduction",
    "discount",
    "vat",
    "balance",
    "payment",
    "carried",
)
SCHEDULE_SECTION_KINDS = {
    "parts": "part",
    "extras": "fee",
    "labour": "labour",
    "paint work": "paint",
    "paint and materials": "paint",
    "specialist operation": "fee",
    "additional items": "fee",
}
# Columns in a Word table arrive as one text line with 2+ spaces between cells
# (see extraction.docx_ingest._table_row_text), which is also how the DLAS
# invoices print their parts grid.
CELL_SPLIT_PATTERN = re.compile(r"\s{2,}")
# "L/R DOOR 1781" / "Door Fitting Kit 1000": the Audatex guide number is
# appended to the description in the DLAS parts grid rather than given its own
# column, and it is not part of the part's name.
GUIDE_NUMBER_SUFFIX_PATTERN = re.compile(r"\s+\d{3,5}$")
QUANTITY_CELL_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3})?$")
PART_NUMBER_PLACEHOLDERS = frozenset({"renew", "repair", "-", "--", "n/a"})
PERCENTAGE_CELL_PATTERN = re.compile(r"^\d{1,3}(?:\.\d+)?\s*%$")
DASH_CELL_PATTERN = re.compile(r"^[-–—]$")
TRAILING_AMOUNT_PATTERN = re.compile(rf"{MONEY_PATTERN}\s*$")
# A candidate row with this many words, no column structure and no trailing
# amount is prose (Format 7 embeds a "Validation note" paragraph that quotes
# every total on the invoice), not a line item.
PROSE_WORD_LIMIT = 12
# The rolled-up section totals an invoice prints *instead of* the section's
# rows. Longest first so "Total Paint & Materials Amount" is never read as
# "Total Paint & Materials" with a stray "Amount".
ROLLED_UP_TOTAL_LABELS: tuple[str, ...] = (
    "Total Paint & Materials Amount",
    "Total Paint and Materials",
    "Total Paint & materials",
    "Total Parts Amount",
    "Total Labour Amount",
    "Additional charges",
    "Total Labour",
)
ROLLED_UP_TOTAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(rf"^{re.escape(label)}\s*:?\s+{MONEY_PATTERN}", re.IGNORECASE))
    for label in ROLLED_UP_TOTAL_LABELS
)
# The labels a rolled-up summary block prints down its first column. Longest
# spelling first within each family, so "paint work" and "paint and materials"
# are never read as a bare "paint" with a stray word after it.
#
# Four of these are the EXL demo invoice's and nothing else in the corpus
# prints them: "additional extras", "collection & delivery", "recovery", and
# bare "paint" (the DLAS invoices spell it "Paint Work" or "Paint &
# Materials"). Each is anchored to a whole line ending in one amount below, so
# a priced row that happens to open with one of these words cannot match.
SUMMARY_SECTION_LABELS = (
    r"paint\s*work",
    r"paint\s*(?:and|&)\s*materials",
    r"specialist operation",
    r"additional items",
    r"additional extras",
    r"collection\s*(?:and|&)\s*delivery",
    r"recovery",
    r"parts",
    r"extras",
    r"labour",
    r"paint",
)
_SUMMARY_SECTION_ALTERNATION = "|".join(SUMMARY_SECTION_LABELS)
# The same roll-up without the "Total" prefix: "Parts   448.91", "Labour
# 2008.00", "Paint & Materials   1034.02". Anchored on the section vocabulary
# and a single trailing amount, so an itemised row ("Corrosion protection
# 6.00") can never match it.
BARE_SECTION_TOTAL_PATTERN = re.compile(
    rf"^(?P<label>{_SUMMARY_SECTION_ALTERNATION})\s*[:£]?\s+(?:GBP\s*)?{MONEY_PATTERN}\s*$",
    re.IGNORECASE,
)
# The same label with its Amount cell left empty: "Recovery" on the EXL
# invoice. On its own this matches a section *heading* too ("Parts" heads the
# DLAS parts grid), so `_blank_summary_row` only accepts it between two priced
# summary rows.
BLANK_SUMMARY_ROW_PATTERN = re.compile(
    rf"^(?P<label>{_SUMMARY_SECTION_ALTERNATION})\s*[:£]?\s*$", re.IGNORECASE
)
# A summary block's VAT row, with or without the rate: "VAT   844.81",
# "VAT 20%   747.60". Anchored at both ends, so the supplier's registration
# number ("VAT Registration no. 106 9411 33") and the run-on registration cell
# ("VAT Reg No. 738 1978 88   Labour   266.00") are not summary rows.
SUMMARY_VAT_ROW_PATTERN = re.compile(
    rf"^VAT\s*(?:[@(]?\s*\d{{1,2}}(?:\.\d+)?\s*%\)?)?\s*[:£]?\s+(?:GBP\s*)?{MONEY_PATTERN}\s*$",
    re.IGNORECASE,
)
# "Claim   5068.87": the EXL layout's grand total. See `_claim_grand_total`
# for why the pattern alone is not enough to act on.
CLAIM_GRAND_TOTAL_PATTERN = re.compile(
    rf"^Claim\s*[:£]?\s+(?:GBP\s*)?{MONEY_PATTERN}\s*$", re.IGNORECASE
)
# "An amount equivalent to VAT @20%: 982.52", "VAT 20%   747.60", "VAT (20%)
# 97.21": a VAT amount whose own label states the rate is unambiguous. The
# rate is required, so "Grand Total Excl VAT   GBP 1423.92" is not a VAT.
EXPLICIT_VAT_AMOUNT_PATTERN = re.compile(
    rf"VAT\s*[@(]?\s*\d{{1,2}}(?:\.\d+)?\s*%\)?\s*[:£]?\s*(?:GBP\s*)?{MONEY_PATTERN}",
    re.IGNORECASE,
)
# "VAT Reg No. 738 1978 88": a cell that opens with the VAT-total label and is
# actually the supplier's registration number.
VAT_REGISTRATION_CELL_PATTERN = re.compile(
    r"^vat\b.*\b(?:reg|registration|number|no)\b", re.IGNORECASE
)
# Values a label reader hands back when the band it read was all column
# headings: "Registration   Make and Model   Chassis Number" yields the label
# "Make" and the "value" "and Model".
COLUMN_HEADING_TOKENS = frozenset(
    {
        "chassis",
        "chassis number",
        "colour",
        "description",
        "make",
        "make and model",
        "manufacturer",
        "model",
        "number",
        "reg",
        "reg no",
        "registration",
        "registration number",
        "variant",
        "vehicle",
        "vin",
    }
)
LEADING_CONNECTOR_PATTERN = re.compile(r"^(?:and|&|/)\s*", re.IGNORECASE)
# A printed company block opens with the company's registered name at the start
# of its own line and runs on into its registration and address: "DL Assistance
# Accident repair Center Ltd, Registered in England & Wales No 1234, registered
# Office: St Clare House, ...". The name is everything from the line start up
# to the first company suffix; the lazy quantifier stops at the first one so a
# block naming two companies keeps the one it opens with.
#
# The anchor is load-bearing. A block is a printed heading, not a sentence, and
# without the two guards below this pattern happily reports
# "Please make all cheques payable to Bright Panel Repairs Ltd" as a company.
COMPANY_BLOCK_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][\w&.'’/-]*(?:\s+[\w&.'’/-]+)*?"
    r"\s+(?:Ltd|Limited|LLP|LLC|PLC|Inc)\.?)\s*(?:,|$)",
    re.IGNORECASE,
)
#: At most this many words in a registered name. "DL Assistance Accident repair
#: Center Ltd" is six; a sentence that happens to name a company is longer.
MAX_COMPANY_NAME_WORDS = 6
#: Lower-case function words that only appear in running prose. The test is
#: this closed class rather than "every word is capitalised", because a trade
#: name does carry lower-case words of its own -- "Accident repair Center".
PROSE_WORDS = frozenset(
    {
        "a", "all", "an", "and", "are", "at", "be", "by", "for", "from", "in",
        "is", "of", "on", "or", "our", "please", "the", "this", "to", "we",
        "with", "your",
    }
)
#: A repair invoice is never supplied by the insurer, so a company block naming
#: one is never the repairer -- however far down the document it is printed.
#: The DLAS layouts repeat their issuer block ("DL Insurance Limited, Central
#: Invoicing Dept, ...") as a per-page footer, and the auda-style invoices name
#: the repairer first and the insurer afterwards, so position alone decides
#: this wrong in both directions.
INSURER_NAME_PATTERN = re.compile(r"\b(?:insurance|assurance|insurer|underwrit)", re.IGNORECASE)


def _first_not_none(*values: Decimal | None) -> Decimal | None:
    """The first value that was actually read, treating a printed 0.00 as read.

    ``a or b`` silently discards ``Decimal("0.00")``, which is how "Total
    Additional Costs GBP 0.00" used to come back as "not printed".
    """

    return next((value for value in values if value is not None), None)


def _parse_date(value: str | None):
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _search_money(text: str, label: str) -> Decimal | None:
    patterns = [
        rf"{label}\s*[:£]?\s*([0-9][0-9,]*\.\d{{2}})",
        rf"{label}\s*\n\s*([0-9][0-9,]*\.\d{{2}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return money(match.group(1))
    return None


def _clean_cell(value: str | None) -> str:
    return strip_scan_artifacts(value or "")


def _column_index(headers: list[str], *labels: str) -> int | None:
    return next(
        (
            index
            for index, value in enumerate(headers)
            if value in labels or any(label in value for label in labels)
        ),
        None,
    )


REGISTRATION_PATTERN = re.compile(r"[A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3}")


def _labelled_registration(value: str | None) -> str | None:
    """Keep a label-grid registration only when it is plate-shaped.

    The scanned vehicle band prints "Registration   Make & Model   Chassis
    Number ..." as a column header, and a label reader has no way to know the
    cell to its right is another heading rather than a value.
    """

    cleaned = strip_scan_artifacts(value or "")
    return cleaned if REGISTRATION_PATTERN.fullmatch(cleaned.upper()) else None


def _company_block_name(line: str) -> str | None:
    """The registered name a whole printed company block opens with.

    ``None`` unless the line really is a block: the name must start the line,
    read like a name rather than a sentence, and not be an insurer's.
    """

    match = COMPANY_BLOCK_PATTERN.match(line)
    if match is None:
        return None
    name = match.group("name").strip()
    words = name.split()
    if len(words) > MAX_COMPANY_NAME_WORDS:
        return None
    if any(word.strip(",.").casefold() in PROSE_WORDS and word[:1].islower() for word in words):
        return None
    if INSURER_NAME_PATTERN.search(name):
        return None
    return name


def _footer_company(text: str) -> str | None:
    """The repairer named in the document's closing company block.

    Both DLAS layouts print two company blocks and they share one address: the
    insurer's invoicing department heads page 1 ("DL Insurance Limited, Central
    Invoicing Dept, St Clare House, ...") and the repairer closes the document
    in the page-2 footer ("DL Assistance Accident repair Center Ltd, Registered
    in England & Wales No 1234, ..."). The insurer is excluded by name rather
    than by position -- see ``INSURER_NAME_PATTERN`` -- and the last of what is
    left wins, because a repairer's own block closes the document.

    Known residual: a customer's company block printed below the repairer's
    would still win. No document in this corpus prints one that way (the
    auda-style invoice labels its "Account: ..." line, which is not a block at
    all), so there is nothing here to key on yet.
    """

    names = [
        name
        for name in (
            _company_block_name(strip_scan_artifacts(line)) for line in text.splitlines()
        )
        if name is not None
    ]
    return names[-1] if names else None


def _labelled_value(value: str | None) -> str | None:
    """Drop a label value that is really a neighbouring column heading.

    Two shapes: one opening with punctuation (a mis-split column band), and
    one where the whole band is headings -- "Registration   Make and Model
    Chassis Number" hands the label reader "Make" and the value "and Model".
    """

    if not value or not re.match(r"[A-Za-z0-9]", value):
        return None
    remainder = LEADING_CONNECTOR_PATTERN.sub("", value.strip()).strip()
    heading = " ".join(remainder.replace("&", " and ").lower().split()).strip(":")
    return None if not remainder or heading in COLUMN_HEADING_TOKENS else value


def _section_key(heading: str) -> str:
    """Collapse a section heading to its ``SCHEDULE_SECTION_KINDS`` key."""

    return " ".join(heading.replace("&", "and").lower().split())


def _row_cells(raw_line: str) -> list[str]:
    """Split a printed row into its columns on runs of 2+ spaces.

    The raw line is split before ``strip_scan_artifacts`` collapses runs of
    whitespace, because the runs *are* the column boundaries.
    """

    return [
        cleaned
        for cleaned in (strip_scan_artifacts(cell) for cell in CELL_SPLIT_PATTERN.split(raw_line))
        if cleaned
    ]


def _is_prose_line(raw_line: str, line: str) -> bool:
    """Return whether a candidate row is a sentence rather than a table row."""

    if len(line.split()) <= PROSE_WORD_LIMIT:
        return False
    if CELL_SPLIT_PATTERN.search(raw_line.strip()):
        return False
    return TRAILING_AMOUNT_PATTERN.search(line) is None


def _rolled_up_total(line: str) -> tuple[str, Decimal] | None:
    """Match a rolled-up section total, returning its label and amount.

    Both spellings count: "Total Labour   2008.00" and the bare "Labour
    2008.00" a summary-only invoice prints. Either way it is a section, never
    a priced row, so `_schedule_text_lines` skips it and
    `_rolled_up_total_lines` emits it once with provenance.
    """

    for label, pattern in ROLLED_UP_TOTAL_PATTERNS:
        match = pattern.match(line)
        if match is None:
            continue
        amount = money(match.group(1))
        if amount is None:
            continue
        return label, amount
    bare = BARE_SECTION_TOTAL_PATTERN.match(line)
    if bare is not None:
        amount = money(bare.group(2))
        if amount is not None:
            return bare.group("label"), amount
    return None


# ponytail: WHY "Claim" IS SAFE AS A GRAND TOTAL, AND ONLY HERE.
#
# The EXL demo invoice labels its grand total "Claim   5068.87". No "Total",
# "Grand Total", "Invoice Total" or "Total Due" appears anywhere on it, so
# without this rule the one figure a reviewer looks at first is not read at
# all -- and worse, the row is ingested as an ordinary priced line and billed.
#
# "Claim" cannot simply join the grand-total vocabulary, because the word
# collides twice over:
#
#   * ``Claim Reference 123456`` sits two tables above it on this very
#     invoice, and ``Claim No 123456/1`` heads the three Request for Payment
#     invoices;
#   * ``Claim`` alone heads the *Summary Information* grid on all seven DL
#     Auda engineer reports.
#
# The rule below keys on the one thing that is true of the total and of
# neither collision: it is a whole line of exactly "Claim" and one amount,
# printed directly beneath that block's VAT row. An identity label never
# carries a two-decimal amount (``Claim Reference 123456`` has none, and a
# reference that did would still print more than one field on the line), and
# a section heading carries no amount at all. Following VAT is what makes it a
# *grand* total rather than another section: VAT is the last thing added
# before the money owed, so the row beneath it is the money owed.
#
# Verified against every document in ``sample-data/client-formats``: the only
# line in the whole corpus that satisfies both halves is the EXL invoice's.
def _claim_grand_total(line: str, previous: str | None) -> Decimal | None:
    """The grand total of an invoice that labels it "Claim", or ``None``.

    ``previous`` is the printed line above this one -- the context that
    separates a grand total from the identity label and the section heading
    that share its word.
    """

    if previous is None or SUMMARY_VAT_ROW_PATTERN.match(previous) is None:
        return None
    match = CLAIM_GRAND_TOTAL_PATTERN.match(line)
    return money(match.group(1)) if match else None


def _claim_grand_total_in(text: str) -> Decimal | None:
    """Scan whole document text for the "Claim" grand total."""

    previous: str | None = None
    for raw_line in text.splitlines():
        line = strip_scan_artifacts(raw_line)
        if not line:
            continue
        amount = _claim_grand_total(line, previous)
        if amount is not None:
            return amount
        previous = line
    return None


def _blank_summary_row(rows: list[str], index: int) -> str | None:
    """The label of a summary row the document printed with no amount.

    The EXL invoice prints ``Recovery`` between ``Collection & Delivery
    156.14`` and ``VAT 844.81`` with its Amount cell empty. Dropping it hides
    from the reviewer that the document printed the row at all, which is a
    different fact from the row not existing -- so it is kept as an
    amount-less section total.

    Both neighbours must be priced summary rows, because the pattern on its
    own also matches a section *heading*: the DLAS invoices print bare
    ``Parts`` and ``Specialist Operation`` lines, and each is followed by its
    own column header rather than by another amount.
    """

    match = BLANK_SUMMARY_ROW_PATTERN.match(rows[index])
    if match is None or index == 0 or index + 1 >= len(rows):
        return None
    previous, following = rows[index - 1], rows[index + 1]
    if _rolled_up_total(previous) is None:
        return None
    if _rolled_up_total(following) is None and SUMMARY_VAT_ROW_PATTERN.match(following) is None:
        return None
    return match.group("label")


def _explicit_vat_amount(text: str) -> Decimal | None:
    """The VAT amount whose own label states the rate."""

    match = EXPLICIT_VAT_AMOUNT_PATTERN.search(text)
    return money(match.group(1)) if match else None


def _vat_registration_only(text: str) -> bool:
    """Whether every "VAT ..." cell in the document is a registration number."""

    cells = [
        cell.strip()
        for raw_line in text.splitlines()
        for cell in CELL_SPLIT_PATTERN.split(raw_line.strip())
        if re.match(r"vat\b", cell.strip(), re.IGNORECASE)
    ]
    return bool(cells) and all(VAT_REGISTRATION_CELL_PATTERN.match(cell) for cell in cells)


def _guarded_labelled_vat(
    text: str, amount: Decimal | None, *, excluded: tuple[Decimal | None, ...]
) -> Decimal | None:
    """The label reader's VAT amount, minus the registration cell it mistakes for one.

    "VAT Reg No. 738 1978 88   Labour   266.00" carries the label "VAT" and a
    trailing amount, so it reads as VAT of 266.00 -- which is also the labour
    total, the second tell.
    """

    if amount is None or _vat_registration_only(text):
        return None
    return None if any(amount == value for value in excluded if value is not None) else amount


def _has_uncertain_lines(lines: list[ExtractedLine]) -> bool:
    """Whether any priced row is one the deterministic parser did not understand.

    A rolled-up section total is `unknown` by construction -- it is a section,
    not a row -- so it must not pull a perfectly parsed invoice into the
    LLM/vision tier.
    """

    return any(
        (line.item_kind == "unknown" and not line.is_section_total)
        or line.source.confidence < 0.75
        for line in lines
    )


# ponytail: only the two sections whose total no invoice in hand prints as a
# readable label are summed from their rows. Parts is left to the printed
# "Total Parts", which already includes the sundry percentage its rows do not.
SECTION_SUM_FIELDS: dict[str, frozenset[str]] = {
    "paint_net": frozenset({"paint", "paint_materials"}),
    "extras_net": frozenset({"extras", "specialist_operation"}),
}


#: The ``InvoiceTotals`` field each section's own printed total belongs to.
SECTION_TOTAL_FIELDS: dict[str, str] = {
    "parts": "parts_net",
    "labour": "labour_net",
    "paint": "paint_net",
    "paint_materials": "paint_net",
    "extras": "extras_net",
    "specialist_operation": "extras_net",
}
#: Sections whose printed total is *added* to a bucket another section already
#: feeds, rather than being that bucket's own figure.
#:
#: ``Collection & Delivery`` and ``Recovery`` are line-item types nothing else
#: in the corpus prints, and ``line_item_type`` is deliberately an open
#: vocabulary, so each keeps its own code ("collection_and_delivery",
#: "recovery") on the row -- a reviewer sees what the document printed. Their
#: *money* has to land somewhere, though, and extras is where it belongs: the
#: EXL engineer report rolls both of them up under EXTRAS (£941.89 =
#: £785.75 + £156.14), so anything else would compare the invoice's extras
#: against the report's on two different definitions.
#:
#: They stay out of ``SECTION_TOTAL_FIELDS`` on purpose. That map is what
#: ``_rolled_up_total_lines`` de-duplicates on -- one printed total per bucket
#: -- and an entry here would make "Collection & Delivery" look like a repeat
#: of "Additional Extras" and silently drop it.
FOLDED_SECTION_TOTAL_FIELDS: dict[str, str] = {
    "collection_and_delivery": "extras_net",
    "recovery": "extras_net",
}

#: What a summary block's *bare* label means, where the bare spelling is less
#: specific than the section vocabulary's own.
#:
#: "Paint" alone on the EXL invoice is the paint **and materials** figure: its
#: 389.81 is exactly the paired report's "Total Paint & Materials", and the
#: report keeps paintwork *labour* inside its labour total (which the invoice's
#: 2019.98 also matches to the penny). ``ensure_line_item_type`` would read the
#: bare word as "paint", the paint-labour code -- which no printed total in
#: this corpus is, and which ``engineer_assessment.SECTION_TOTAL_FIELDS`` has
#: no field for, so the section would show a billed figure with nothing to
#: compare it against. The spelled-out headings ("Paint Work", "Paint &
#: Materials") say which they are and are not remapped.
SUMMARY_LABEL_TYPES: dict[str, str] = {"paint": "paint_materials"}

#: Where a rolled-up section total's money belongs in ``InvoiceTotals``, folded
#: codes included. Summed rather than first-wins, because a folded code shares
#: its bucket with the section that owns it.
ROLLED_UP_TOTAL_FIELDS: dict[str, str] = SECTION_TOTAL_FIELDS | FOLDED_SECTION_TOTAL_FIELDS
SECTION_TOTAL_ROW_PATTERN = re.compile(rf"^Total\b\s*[:£]?\s*{MONEY_PATTERN}", re.IGNORECASE)


def _printed_section_totals(text: str) -> dict[str, Decimal]:
    """Read the bare "Total   136.32" a schedule prints at the foot of itself.

    ``label_grid`` deliberately does not treat "Total" as a subtotal synonym
    because it heads every schedule; the section it closes is only knowable
    here, from the heading above it.
    """

    totals: dict[str, Decimal] = {}
    field: str | None = None
    for raw_line in text.splitlines():
        line = strip_scan_artifacts(raw_line)
        heading = SCHEDULE_SECTION_PATTERN.match(line)
        if heading and not re.search(r"\d[\d,]*\.\d{2}", line):
            field = SECTION_TOTAL_FIELDS.get(ensure_line_item_type(heading.group(1)))
            continue
        match = SECTION_TOTAL_ROW_PATTERN.match(line)
        if match is None or field is None:
            continue
        amount = money(match.group(1))
        if amount is not None:
            totals.setdefault(field, amount)
        field = None
    return totals


def _rolled_up_section_totals(lines: list[ExtractedLine]) -> dict[str, Decimal]:
    """The ``InvoiceTotals`` figures a fully rolled-up invoice's summary states.

    A summary-only invoice prints its section totals as bare "Labour 2019.98"
    rows and carries no label a ``FIELD_SYNONYMS`` reader recognises, so the
    rows `_rolled_up_total_lines` already emitted are the only evidence of
    each section's value. Reading them back here keeps one parse of the
    summary block rather than a second regex over the text.

    Amount-less rows (``Recovery``) contribute nothing; they exist so the
    reviewer can see the document printed them.
    """

    totals: dict[str, Decimal] = {}
    for line in lines:
        if not line.is_section_total or line.line_total_net is None:
            continue
        field = ROLLED_UP_TOTAL_FIELDS.get(line.line_item_type or "")
        if field is None:
            continue
        totals[field] = totals.get(field, Decimal("0")) + line.line_total_net
    return totals


def _section_sums(lines: list[ExtractedLine]) -> dict[str, Decimal]:
    """Total the itemised rows of each section whose total is not printed."""

    sums: dict[str, Decimal] = {}
    for field, codes in SECTION_SUM_FIELDS.items():
        amounts = [
            line.line_total_net
            for line in lines
            if not line.is_section_total
            and line.line_item_type in codes
            and line.line_total_net is not None
        ]
        if amounts:
            sums[field] = sum(amounts, Decimal("0"))
    return sums


def _guess_item_kind(section: str, description: str) -> str:
    section = section.lower()
    description_lower = description.lower()
    description_words = set(re.findall(r"[a-z]+", description_lower))
    if "labour" in section:
        return "labour"
    # Generic invoice tables often put every row under a "Part" heading even
    # when the description clearly represents an operation. Preserve the
    # governed part/service boundary by recognising explicit operation wording
    # before falling back to the section label.
    if description_lower.startswith(
        ("fit ", "fitted ", "replace ", "replaced ", "remove ", "removed ", "refit ")
    ):
        return "labour"
    if description_lower.startswith(("carried out ", "carry out ")):
        return "service" if ("service" in description_lower or "mot" in description_lower) else "labour"
    if "mot" in section or "mot test" in description_lower:
        return "service"
    if "disposal" in description_lower or {
        "waste",
        "oil",
        "filter",
    }.issubset(description_lower.split()):
        return "disposal"
    if "paint" in description_lower:
        return "paint"
    if "service" in description_words:
        return "service"
    if "service" in section:
        return "service"
    if any(
        token in description_words
        for token in {
            "adblue",
            "bumper",
            "cleaner",
            "disc",
            "discs",
            "door",
            "filter",
            "gas",
            "grille",
            "lamp",
            "oil",
            "pad",
            "pads",
            "panel",
            "screenwash",
            "seal",
            "sensor",
            "tyre",
            "washer",
            "wheel",
            "wing",
        }
    ):
        return "part"
    return "part" if "part" in section else "unknown"


def _ocr_section(line: str) -> str | None:
    """Recognise noisy OCR section headings without mistaking priced rows for headings."""

    if re.search(MONEY_PATTERN, line):
        return None
    token = re.sub(r"[^a-z]+", " ", line.lower()).strip()
    words = token.split()
    if not words:
        return None
    if words[0] in {"parts", "part"} and len(words) <= 6:
        return "parts"
    if "parts" in words and any(
        marker in words for marker in {"qty", "quantity", "unit", "value", "total"}
    ):
        return "parts"
    if words[0] == "labour" and len(words) <= 7:
        return "labour"
    if words[0] == "service" and len(words) <= 6:
        return "service"
    if token in {"work performed", "labour work carried out"}:
        return "labour"
    return None


def _token(value: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", value.lower().replace(",", ""))


def _target_tokens(value: str) -> list[str]:
    return [token for token in (_token(item) for item in value.split()) if token]


def _union_bbox(boxes: list[BoundingBox]) -> BoundingBox | None:
    if not boxes:
        return None
    return BoundingBox(
        x0=min(box.x0 for box in boxes),
        y0=min(box.y0 for box in boxes),
        x1=max(box.x1 for box in boxes),
        y1=max(box.y1 for box in boxes),
    )


def _matching_words(page: PageAnalysis, value: str, *, prefer_last: bool = False):
    wanted = _target_tokens(value)
    words = [word for word in page.words if _token(word.text)]
    if not wanted or not words:
        return []
    matches = []
    keys = [_token(word.text) for word in words]
    for index in range(len(keys) - len(wanted) + 1):
        if keys[index : index + len(wanted)] == wanted:
            matches.append(words[index : index + len(wanted)])
    if not matches:
        return []
    return matches[-1] if prefer_last else matches[0]


def _row_words(page: PageAnalysis, anchor: BoundingBox) -> list:
    anchor_centre = (anchor.y0 + anchor.y1) / 2
    anchor_height = max(anchor.y1 - anchor.y0, 1)
    return [
        word
        for word in page.words
        if abs(((word.bbox.y0 + word.bbox.y1) / 2) - anchor_centre)
        <= max(anchor_height, word.bbox.y1 - word.bbox.y0) * 1.15
    ]


def _region_in_words(words: list, value: str, *, prefer_last: bool = False):
    wanted = _target_tokens(value)
    filtered = [word for word in words if _token(word.text)]
    keys = [_token(word.text) for word in filtered]
    matches = []
    for index in range(len(keys) - len(wanted) + 1):
        if wanted and keys[index : index + len(wanted)] == wanted:
            matches.append(filtered[index : index + len(wanted)])
    if not matches:
        return None
    selected = matches[-1] if prefer_last else matches[0]
    return _union_bbox([word.bbox for word in selected])


def _line_source(
    page: PageAnalysis,
    *,
    description: str,
    quantity: str,
    unit_price: str,
    line_total: str,
    raw_text: str,
    extraction_method: str,
    confidence: float,
) -> FieldSource:
    description_words = _matching_words(page, description)
    description_bbox = _union_bbox([word.bbox for word in description_words])
    if description_bbox is None:
        return FieldSource(
            page_number=page.page_number,
            raw_text=raw_text,
            extraction_method=extraction_method,
            confidence=confidence,
            precision="approximate",
        )
    row_words = _row_words(page, description_bbox)
    regions = {"description": description_bbox}
    quantity_bbox = _region_in_words(row_words, quantity)
    unit_price_bbox = _region_in_words(row_words, unit_price)
    line_total_bbox = _region_in_words(row_words, line_total, prefer_last=True)
    if quantity_bbox:
        regions["quantity"] = quantity_bbox
    if unit_price_bbox:
        regions["unit_price"] = unit_price_bbox
    if line_total_bbox:
        regions["line_total"] = line_total_bbox
    row_bbox = _union_bbox([word.bbox for word in row_words]) or description_bbox
    regions["row"] = row_bbox
    return FieldSource(
        page_number=page.page_number,
        bbox=row_bbox,
        regions=regions,
        raw_text=raw_text,
        extraction_method=extraction_method,
        confidence=confidence,
        precision="exact" if line_total_bbox else "approximate",
    )


def _group_words_by_line(page: PageAnalysis) -> list[list]:
    groups: list[list] = []
    for word in sorted(page.words, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        centre = (word.bbox.y0 + word.bbox.y1) / 2
        target = next(
            (
                group
                for group in reversed(groups[-4:])
                if abs(
                    centre - sum((item.bbox.y0 + item.bbox.y1) / 2 for item in group) / len(group)
                )
                <= max(word.bbox.y1 - word.bbox.y0, 1) * 0.8
            ),
            None,
        )
        if target is None:
            groups.append([word])
        else:
            target.append(word)
    return [sorted(group, key=lambda item: item.bbox.x0) for group in groups]


def _total_source(
    pages: list[PageAnalysis],
    labels: tuple[str, ...],
    value: Decimal | None,
) -> FieldSource | None:
    """Point at the printed text that states this total.

    ponytail: THE TIGHTEST TEXT WINS, NOT THE LAST ONE.

    A total's label and its amount can both appear in *prose* as well as on
    the row that states them. Invoices 5, 6 and 7 embed a "Validation note"
    paragraph that recites every figure on the document -- "Totals aligned to
    report: Total Parts £1,237.50; Total Additional Costs £144.13; Total
    Labour £2,653.01;" -- and it is printed below the totals it recites. A
    scan that simply took the last match therefore sent labour, parts, paint
    and VAT provenance into the note, so a reviewer clicking "show evidence"
    on a number landed on a sentence *about* the number. On invoice 5 that
    sentence asserts a reconciliation which is false by £78.77, which is the
    worst possible thing to offer as proof.

    So every match is collected and ranked, best first:

    1. the text *ends* in the figure. A totals row states its label and then
       its amount and stops; a recital runs on into the next figure, which is
       what separates "An amount equivalent to VAT @20%: 1022.55" from the
       note's shorter "...; VAT £1,022.55; Total Due £6,135.29.";
    2. then the fewest words, because a printed row is the tightest text that
       carries the label and the figure together;
    3. then the old behaviour -- the last such text in the document, which is
       what makes "Total Due: 6233.03" win over an identical "Invoice total:
       6233.03" printed above it.

    Both are preferences, not filters: invoice 6 prints its extras total as a
    bare "Total 141.87" under a heading, so the note really is the only text
    carrying that label and that figure together, and it stays the evidence
    rather than the field losing its provenance altogether.

    This selects among texts that already state the figure; it never changes
    which figure is stated.
    """

    if value is None:
        return None
    value_token = _token(f"{value:.2f}")
    best: tuple[tuple[int, int], PageAnalysis, list] | None = None
    for page in reversed(pages):
        for words in reversed(_group_words_by_line(page)):
            keys = [_token(word.text) for word in words]
            joined = " ".join(keys)
            if not any(all(token in joined for token in _target_tokens(label)) for label in labels):
                continue
            if not any(key == value_token for key in keys):
                continue
            rank = (0 if keys[-1] == value_token else 1, len(words))
            if best is None or rank < best[0]:
                best = (rank, page, words)
    if best is None:
        return None
    _rank, page, words = best
    value_words = [word for word in words if _token(word.text) == value_token]
    value_bbox = _union_bbox([word.bbox for word in value_words[-1:]])
    return FieldSource(
        page_number=page.page_number,
        bbox=value_bbox,
        regions={"value": value_bbox} if value_bbox else {},
        raw_text=" ".join(word.text for word in words),
        extraction_method=page.extraction_method,
        confidence=page.extraction_confidence,
        precision="exact",
    )


def _vehicle_row(text: str) -> dict[str, str | int | None]:
    """Read the values beneath the stable vehicle-detail header in visual order."""

    match = None
    for line in text.splitlines():
        cleaned = strip_scan_artifacts(line)
        candidate = re.match(
            r"^([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3})\s+(.+?)\s+"
            r"([A-Z0-9]{12,20})\s+([0-9]{3,5})\s+([0-9,]{3,})$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if candidate:
            match = candidate
            break
    if not match:
        for line in text.splitlines():
            cleaned = strip_scan_artifacts(line)
            compact = re.match(
                r"^([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3})\s*[-–—]\s*([A-Z][A-Z0-9 .'-]+)$",
                cleaned,
                flags=re.IGNORECASE,
            )
            if compact:
                make_model = strip_scan_artifacts(compact.group(2))
                make, _, model = make_model.partition(" ")
                return {
                    "registration": strip_scan_artifacts(compact.group(1)).upper(),
                    "vehicle_make": make or None,
                    "vehicle_model": model or None,
                    "vin": None,
                    "engine_cc": None,
                    "mileage": None,
                }
        return {}
    make_model = strip_scan_artifacts(match.group(2))
    make, _, model = make_model.partition(" ")
    return {
        "registration": strip_scan_artifacts(match.group(1)).upper(),
        "vehicle_make": make or None,
        "vehicle_model": model or None,
        "vin": match.group(3),
        "engine_cc": int(match.group(4)),
        "mileage": int(match.group(5).replace(",", "")),
    }


def _line_tax(
    line_total: Decimal | None, vat_rate: Decimal, applies: bool
) -> tuple[Decimal, Decimal]:
    net = line_total or Decimal("0")
    vat = money(net * vat_rate / Decimal("100")) if applies else Decimal("0.00")
    vat = vat or Decimal("0.00")
    return vat, money(net + vat) or Decimal("0.00")


class InvoiceParser:
    def __init__(self, vision_extractor: MultimodalInvoiceExtractor | None = None) -> None:
        self.vision_extractor = vision_extractor

    def parse_group(
        self,
        pdf_path: Path,
        pages: list[PageAnalysis],
        *,
        document_role: str = "invoice",
    ) -> ExtractedInvoice:
        raw_text = "\n".join(page.text for page in pages)
        page_numbers = [page.page_number for page in pages]
        extraction_method = (
            "native_table" if all(page.extraction_method == "native" for page in pages) else "ocr"
        )
        lines: list[ExtractedLine] = []
        layout_text_parts: list[str] = []

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_info in pages:
                    pdf_page = pdf.pages[page_info.page_number - 1]
                    layout_text_parts.append(pdf_page.extract_text(layout=True) or page_info.text)
                    if page_info.extraction_method == "native":
                        page_lines = self._native_table_lines(pdf_page, page_info, len(lines) + 1)
                        if not page_lines:
                            # Priced schedules drawn as plain text (Audatex PARTS
                            # and EXTRAS pages) expose no pdfplumber table; parse
                            # their rows deterministically before any LLM tier.
                            page_lines = self._schedule_text_lines(page_info, len(lines) + 1)
                        lines.extend(page_lines)
                    else:
                        lines.extend(self._ocr_lines(page_info, len(lines) + 1))
        except Exception:
            if self.vision_extractor is None:
                raise
            layout_text_parts.extend(page.text for page in pages)

        layout_text = "\n".join(layout_text_parts)
        lines.extend(
            self._rolled_up_total_lines(layout_text + "\n" + raw_text, pages, len(lines) + 1, lines)
        )
        totals = self._totals(layout_text + "\n" + raw_text, pages, lines)
        if totals.non_vatable is not None and not any(
            line.item_kind == "service" and "mot" in line.normalised_description for line in lines
        ):
            source_page = pages[-1]
            mot_words = _matching_words(source_page, "MOT")
            mot_bbox = _union_bbox([word.bbox for word in mot_words])
            lines.append(
                ExtractedLine(
                    sequence_no=len(lines) + 1,
                    raw_description="MOT test",
                    normalised_description="mot test",
                    item_kind="service",
                    quantity=Decimal("1"),
                    unit="test",
                    unit_price_net=totals.non_vatable,
                    line_total_net=totals.non_vatable,
                    vat_rate=Decimal("0"),
                    vat_amount=Decimal("0.00"),
                    gross_amount=totals.non_vatable,
                    vat_applicable=False,
                    source=FieldSource(
                        page_number=source_page.page_number,
                        bbox=mot_bbox,
                        regions={"row": mot_bbox, "description": mot_bbox} if mot_bbox else {},
                        raw_text="MOT",
                        extraction_method=source_page.extraction_method,
                        confidence=source_page.extraction_confidence,
                        precision="approximate",
                    ),
                )
            )

        header = self._header(layout_text + "\n" + raw_text)
        confidence = sum(page.extraction_confidence for page in pages) / len(pages)
        deterministic = ExtractedInvoice(
            header=header,
            totals=totals,
            line_items=lines,
            page_numbers=page_numbers,
            document_role=document_role,
            extraction_method=extraction_method,
            extraction_confidence=confidence,
        )
        usable_lines = [
            line
            for line in deterministic.line_items
            if line.line_total_net is not None and line.line_total_net > 0
        ]
        stated_subtotal = deterministic.totals.subtotal_net
        extracted_subtotal = sum(
            (
                line.line_total_net
                for line in usable_lines
                if line.vat_applicable and line.line_total_net is not None
            ),
            Decimal("0"),
        )
        uncertain_lines = _has_uncertain_lines(usable_lines)
        recover_lines = not usable_lines or uncertain_lines or (
            stated_subtotal is not None
            and abs(extracted_subtotal - stated_subtotal) > Decimal("0.05")
        )
        if self.vision_extractor is None or (
            not recover_lines
            and deterministic.header.invoice_date is not None
            and deterministic.header.supplier_name
            and (
                deterministic.totals.subtotal_net is not None
                or deterministic.totals.total_gross is not None
            )
        ):
            return deterministic
        try:
            vision = self.vision_extractor.extract(pages, role_hint=document_role)
        except LLMProviderError:
            return deterministic
        return merge_invoice_extractions(
            deterministic,
            vision,
            include_vision_lines=recover_lines,
        )

    def _native_table_lines(self, pdf_page, page: PageAnalysis, start: int) -> list[ExtractedLine]:
        return self._table_lines(
            pdf_page.extract_tables() or [],
            page,
            start,
            extraction_method="native_table",
            confidence=0.98,
        )

    def _schedule_text_lines(self, page: PageAnalysis, start: int) -> list[ExtractedLine]:
        """Deterministic text-row parsing for priced schedules without table rulings.

        Handles Audatex-style PARTS schedules (guide number / description /
        part number / "Bet." discount / price), the DLAS parts grid (Qty /
        Description / Part Number / Each / Extended, columns separated by 2+
        spaces) and EXTRAS charge lists (description followed by a GBP
        amount). Summary rows (totals, deductions, discounts) and rolled-up
        section totals never become lines, and an unpriced row is kept only
        inside a recognised section, so rolled-up calculation pages still
        yield no lines.
        """

        output: list[ExtractedLine] = []
        sequence = start
        section: str | None = None
        heading_text: str | None = None
        previous: str | None = None
        for raw_line in page.text.splitlines():
            line = strip_scan_artifacts(raw_line)
            if not line:
                continue
            prior, previous = previous, line
            if _is_prose_line(raw_line, line):
                continue
            heading = SCHEDULE_SECTION_PATTERN.match(line)
            if heading and not re.search(r"\d[\d,]*\.\d{2}", line):
                heading_text = strip_scan_artifacts(heading.group(1))
                section = _section_key(heading_text)
                continue
            # A rolled-up section total is evidence of a section, not a row in
            # it; `_rolled_up_total_lines` emits it once, with provenance.
            if _rolled_up_total(line) is not None:
                continue
            # The grand total is the invoice's answer, not a thing it billed
            # for. "Claim   5068.87" reads as an ordinary priced row on shape
            # alone, so the whole document's total would be charged as a line.
            if _claim_grand_total(line, prior) is not None:
                continue
            lower = line.casefold()
            # A summary row is never a line item, whatever shape it arrives
            # in. This has to precede every row reader, not just the generic
            # one: "VAT   20%   982.52", "Overall Discount   10%   50.00" and
            # "Deductions   0%   0.00" are the same three cells as "Sundry
            # parts   3.50%   41.85", and `_percentage_row` cannot tell them
            # apart on shape alone.
            if any(token in lower for token in NON_SCHEDULE_LINE_TOKENS):
                continue
            cells = _row_cells(raw_line)
            parts_match = PARTS_SCHEDULE_ROW_PATTERN.match(line)
            quantity: Decimal | None = Decimal("1")
            unit_price: Decimal | None = None
            category = heading_text
            if parts_match:
                description = strip_scan_artifacts(parts_match.group("description"))
                line_total = money(parts_match.group("price"))
                part_number: str | None = parts_match.group("part_number")
                item_kind = "part"
            elif grid := self._parts_grid_row(section, cells):
                description, part_number, quantity, unit_price, line_total = grid
                item_kind = "part"
            elif sundry := self._percentage_row(cells):
                category, line_total = sundry
                description = category
                part_number = None
                item_kind = "fee"
                quantity = None
            else:
                part_number = None
                item_kind = SCHEDULE_SECTION_KINDS.get(section or "", "unknown")
                priced_match = PRICED_SCHEDULE_ROW_PATTERN.match(line)
                if priced_match is not None:
                    description = strip_scan_artifacts(priced_match.group("description"))
                    line_total = money(priced_match.group("price"))
                elif section is not None and len(cells) == 2 and DASH_CELL_PATTERN.match(cells[1]):
                    # "C/Car Class A   -": a priced schedule row the repairer
                    # did not charge for. It belongs to the section's row count
                    # and contributes nothing to its total.
                    description = cells[0]
                    line_total = Decimal("0.00")
                else:
                    continue
            # ponytail: a credit row ("Goodwill credit   -20.00", "(20.00)")
            # is dropped, not signed: PRICED_SCHEDULE_ROW_PATTERN reads no
            # sign and no bracket, and every downstream sum, benchmark and
            # math finding assumes a non-negative row. Accepting one is a
            # change to those, not to this regex.
            if (
                not description
                or not re.search(r"[A-Za-z]{3}", description)
                or line_total is None
                or line_total < 0
                or (line_total == 0 and section is None)
            ):
                continue
            vat_amount, gross_amount = _line_tax(line_total, Decimal("20"), True)
            output.append(
                ExtractedLine(
                    sequence_no=sequence,
                    raw_description=description,
                    normalised_description=normalise_description(description),
                    item_kind=item_kind,
                    part_number=part_number,
                    quantity=quantity,
                    unit=normalise_unit(None, item_kind=item_kind),
                    unit_price_net=unit_price if unit_price is not None else line_total,
                    line_total_net=line_total,
                    vat_rate=Decimal("20"),
                    vat_amount=vat_amount,
                    gross_amount=gross_amount,
                    vat_applicable=True,
                    line_item_type=ensure_line_item_type(category),
                    raw_category=category,
                    source=_line_source(
                        page,
                        description=description,
                        quantity=str(quantity) if quantity is not None else "",
                        unit_price=str(unit_price if unit_price is not None else line_total),
                        line_total=str(line_total),
                        raw_text=raw_line,
                        extraction_method="native",
                        confidence=page.extraction_confidence,
                    ),
                )
            )
            sequence += 1
        return output

    def _parts_grid_row(
        self, section: str | None, cells: list[str]
    ) -> tuple[str, str | None, Decimal | None, Decimal | None, Decimal | None] | None:
        """Read one DLAS parts row: Qty | Description | Part Number | Each | Extended."""

        if section != "parts" or len(cells) != 5:
            return None
        quantity_cell, description, part_cell, each, extended = cells
        if not QUANTITY_CELL_PATTERN.match(quantity_cell):
            return None
        line_total = money(extended) if TRAILING_AMOUNT_PATTERN.match(extended) else None
        if line_total is None:
            return None
        part_number = None if part_cell.casefold() in PART_NUMBER_PLACEHOLDERS else part_cell
        return (
            GUIDE_NUMBER_SUFFIX_PATTERN.sub("", description).strip() or description,
            part_number,
            as_decimal(quantity_cell),
            money(each) if TRAILING_AMOUNT_PATTERN.match(each) else None,
            line_total,
        )

    def _percentage_row(self, cells: list[str]) -> tuple[str, Decimal | None] | None:
        """Read a percentage-charged row: "Sundry parts | 3.50% | 41.85"."""

        if len(cells) != 3 or not PERCENTAGE_CELL_PATTERN.match(cells[1]):
            return None
        if not TRAILING_AMOUNT_PATTERN.match(cells[2]):
            return None
        return cells[0], money(cells[2])

    def _rolled_up_total_lines(
        self,
        text: str,
        pages: list[PageAnalysis],
        start: int,
        itemised: list[ExtractedLine],
    ) -> list[ExtractedLine]:
        """Emit one line per section the invoice rolled up instead of itemising.

        Format 1 and 7 itemise parts and specialist operations but print
        labour and paint as a single total each; Format 2 prints nothing but
        totals. A section that already has itemised rows is skipped, so a row
        set and its own total are never both recorded.

        A summary row printed with an empty Amount cell is emitted too, with
        no amount on it -- see `_blank_summary_row` for why a reviewer needs
        to see it and how it is told apart from a section heading.
        """

        # paint + paint_materials and extras + specialist_operation are one
        # bucket each in `SECTION_TOTAL_FIELDS`, so a paint section with rows
        # must also suppress "Total Paint & Materials Amount", and itemised
        # specialist operations must suppress a footer "Additional charges".
        recorded = {
            SECTION_TOTAL_FIELDS.get(line.line_item_type, line.line_item_type)
            for line in itemised
            if not line.is_section_total
        }
        output: list[ExtractedLine] = []
        sequence = start
        # Blank lines carry no summary row and would break the neighbour test
        # `_blank_summary_row` makes, so the block is read as printed rows.
        rows = [
            cleaned for cleaned in (strip_scan_artifacts(raw) for raw in text.splitlines()) if cleaned
        ]
        for index, row in enumerate(rows):
            matched = _rolled_up_total(row)
            if matched is None:
                blank_label = _blank_summary_row(rows, index)
                if blank_label is None:
                    continue
                label, amount = blank_label, None
            else:
                label, amount = matched
            line_item_type = SUMMARY_LABEL_TYPES.get(
                _section_key(label), ensure_line_item_type(label)
            )
            bucket = SECTION_TOTAL_FIELDS.get(line_item_type, line_item_type)
            if bucket in recorded:
                continue
            recorded.add(bucket)
            # An amount-less row states nothing about tax either: it carries
            # no rate, no VAT and no gross, so no sum can quietly read a zero
            # off it as if the document had printed one.
            vat_rate = Decimal("20") if amount is not None else None
            vat_amount, gross_amount = (
                _line_tax(amount, Decimal("20"), True) if amount is not None else (None, None)
            )
            source = _total_source(pages, (label,), amount) or FieldSource(
                page_number=pages[-1].page_number,
                raw_text=row,
                extraction_method=pages[-1].extraction_method,
                confidence=pages[-1].extraction_confidence,
                precision="approximate",
            )
            output.append(
                ExtractedLine(
                    sequence_no=sequence,
                    raw_description=label,
                    normalised_description=normalise_description(label),
                    item_kind="unknown",
                    quantity=None,
                    unit_price_net=None,
                    line_total_net=amount,
                    vat_rate=vat_rate,
                    vat_amount=vat_amount,
                    gross_amount=gross_amount,
                    vat_applicable=amount is not None,
                    line_item_type=line_item_type,
                    raw_category=label,
                    is_section_total=True,
                    source=source,
                )
            )
            sequence += 1
        return output

    def _table_lines(
        self,
        tables: list[list[list[str | None]]],
        page: PageAnalysis,
        start: int,
        *,
        extraction_method: str,
        confidence: float,
    ) -> list[ExtractedLine]:
        output: list[ExtractedLine] = []
        sequence = start
        for table in tables:
            if not table:
                continue
            header_cells = [_clean_cell(cell) for cell in table[0]]
            normalised_headers = [re.sub(r"\s+", " ", cell.lower()).strip() for cell in header_cells]
            header = " ".join(cell for cell in header_cells if cell)
            header_lower = header.lower()

            description_index = _column_index(
                normalised_headers, "description", "operation", "item"
            )
            quantity_index = _column_index(normalised_headers, "qty", "quantity")
            unit_price_index = _column_index(
                normalised_headers, "unit price", "unit cost", "rate", "price"
            )
            line_total_index = _column_index(
                normalised_headers, "line total", "subtotal", "sub total", "amount"
            )
            if line_total_index is None:
                line_total_index = _column_index(normalised_headers, "total")
            part_number_index = _column_index(
                normalised_headers, "part number", "part no", "part #"
            )
            generic_parts_table = (
                description_index is not None
                and quantity_index is not None
                and line_total_index is not None
            )
            governed_table = "sub total" in header_lower and any(
                key in header_lower for key in ("parts", "labour", "service")
            )
            if not generic_parts_table and not governed_table:
                continue
            section = "labour" if "labour" in header_lower else "parts"
            for row in table[1:]:
                cells = [_clean_cell(cell) for cell in row]
                if not cells or not cells[0]:
                    continue
                if generic_parts_table:
                    required_index = max(description_index, quantity_index, line_total_index)
                    if len(cells) <= required_index:
                        continue
                    description = cells[description_index]
                    quantity = cells[quantity_index]
                    line_total = cells[line_total_index]
                    unit_price = (
                        cells[unit_price_index]
                        if unit_price_index is not None and unit_price_index < len(cells)
                        else ""
                    )
                    part_number = (
                        cells[part_number_index]
                        if part_number_index is not None and part_number_index < len(cells)
                        else ""
                    )
                elif section == "parts" and len(cells) >= 6:
                    description, part_number, quantity, unit_price, _, line_total = cells[:6]
                elif section == "labour" and len(cells) >= 5:
                    description, quantity, unit_price, _, line_total = cells[:5]
                    part_number = ""
                else:
                    continue
                try:
                    qty = as_decimal(quantity)
                    unit_price_value = money(unit_price)
                    line_total_value = money(line_total)
                except ValueError:
                    continue
                if not description or line_total_value is None:
                    continue
                if unit_price_value is None and qty and qty > 0:
                    unit_price_value = line_total_value / qty
                output.append(
                    ExtractedLine(
                        sequence_no=sequence,
                        raw_description=description,
                        normalised_description=normalise_description(description),
                        item_kind=_guess_item_kind(section, description),
                        part_number=part_number or None,
                        quantity=qty,
                        unit=normalise_unit(None, item_kind=_guess_item_kind(section, description)),
                        unit_price_net=unit_price_value,
                        line_total_net=line_total_value,
                        vat_rate=Decimal("20"),
                        vat_amount=_line_tax(line_total_value, Decimal("20"), True)[0],
                        gross_amount=_line_tax(line_total_value, Decimal("20"), True)[1],
                        vat_applicable=True,
                        line_item_type=ensure_line_item_type(section),
                        raw_category=section,
                        source=_line_source(
                            page,
                            description=description,
                            quantity=quantity,
                            unit_price=unit_price,
                            line_total=line_total,
                            raw_text=" | ".join(cells),
                            extraction_method=extraction_method,
                            confidence=confidence,
                        ),
                    )
                )
                sequence += 1
        return output

    def _ocr_lines(self, page: PageAnalysis, start: int) -> list[ExtractedLine]:
        table_lines = self._table_lines(
            page.tables,
            page,
            start,
            extraction_method="ocr",
            confidence=page.extraction_confidence,
        )
        if table_lines:
            return table_lines

        output: list[ExtractedLine] = []
        current_section = "unknown"
        current_heading: str | None = None
        sequence = start
        previous: str | None = None
        for raw_line in page.text.splitlines():
            line = strip_scan_artifacts(raw_line)
            lower = line.lower()
            if not line:
                continue
            prior, previous = previous, line
            if _is_prose_line(raw_line, line):
                continue
            # The grand total, however it is labelled, is never a billed row.
            if _claim_grand_total(line, prior) is not None:
                continue
            if section := _ocr_section(line):
                current_section = section
                current_heading = line
                continue
            amounts = re.findall(MONEY_PATTERN, line)
            if not amounts or not re.search(r"[A-Za-z]{3}", line):
                continue
            if any(token in lower for token in ("subtotal", "total", "vat", "balance", "payment")):
                continue
            if _rolled_up_total(line) is not None:
                continue
            if any(
                token in lower
                for token in (
                    "terms and conditions",
                    "all repairs are undertaken",
                    "receipt",
                )
            ):
                continue
            line_total = money(amounts[-1])
            unit_price = money(amounts[-2]) if len(amounts) > 1 else line_total
            description = re.sub(MONEY_PATTERN, " ", line)
            description = re.sub(r"\b\d+(?:\.\d+)?\b", " ", description)
            description = strip_scan_artifacts(description)
            if len(description) < 3:
                continue
            quantity = Decimal("1")
            if unit_price and line_total and unit_price > 0:
                candidate = line_total / unit_price
                if candidate <= Decimal("50"):
                    quantity = candidate
            output.append(
                ExtractedLine(
                    sequence_no=sequence,
                    raw_description=description,
                    normalised_description=normalise_description(description),
                    item_kind=_guess_item_kind(current_section, description),
                    quantity=quantity,
                    unit=normalise_unit(
                        None, item_kind=_guess_item_kind(current_section, description)
                    ),
                    unit_price_net=unit_price,
                    line_total_net=line_total,
                    vat_rate=Decimal("0") if "mot" in lower else Decimal("20"),
                    vat_amount=_line_tax(
                        line_total,
                        Decimal("0") if "mot" in lower else Decimal("20"),
                        "mot" not in lower,
                    )[0],
                    gross_amount=_line_tax(
                        line_total,
                        Decimal("0") if "mot" in lower else Decimal("20"),
                        "mot" not in lower,
                    )[1],
                    vat_applicable="mot" not in lower,
                    line_item_type=ensure_line_item_type(current_section),
                    raw_category=current_heading,
                    source=_line_source(
                        page,
                        description=description,
                        quantity=str(quantity),
                        unit_price=str(unit_price or ""),
                        line_total=str(line_total or ""),
                        raw_text=raw_line,
                        extraction_method="ocr",
                        confidence=page.extraction_confidence,
                    ),
                )
            )
            sequence += 1
        return output

    def _header(self, text: str) -> InvoiceHeader:
        # The DLAS reference grid prints its labels without colons, in two
        # columns; `read_label_values` is the one reader for every shape, and
        # today's regexes stay as the fallback for everything it does not know.
        labels = read_label_values(text)
        compact = strip_scan_artifacts(text)
        vehicle = _vehicle_row(text)
        invoice_number = labels.get("invoice_number")
        for pattern in (
            # "343653726836/1~3538": the "~" suffix is part of the number.
            r"Invoice\s*(?:No\.?|Number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/~-]{2,})",
            r"SALES INVOICE.*?Invoice No\s*[:#]?\s*([A-Z0-9/~-]+)",
        ):
            if invoice_number:
                break
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if match and match.group(1).lower() not in {"date", "name"}:
                invoice_number = match.group(1)
                break
        date_match = re.search(
            r"(?:Invoice Date|Date of Work|Date)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            compact,
            flags=re.IGNORECASE,
        )
        registration_match = re.search(
            r"(?<!VAT\s)(?:Registration|Reg\.?\s*No\.?)\s*:?\s*([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3})",
            compact,
            flags=re.IGNORECASE,
        )
        mileage_match = re.search(r"Mileage\s*:?\s*([0-9,]{3,})", compact, flags=re.IGNORECASE)
        vat_number_match = re.search(
            r"VAT\s*(?:Reg(?:istration)?\s*(?:No\.)?|Number)\s*[:.]?\s*([0-9 ]{8,15})",
            compact,
            flags=re.IGNORECASE,
        )
        supplier = None
        for line in text.splitlines():
            cleaned = strip_scan_artifacts(line)
            if re.search(r"(clinic|garage|autosolutions|mot centre|mini service)", cleaned, re.I):
                supplier = cleaned
                break
        # The DLAS invoices name no garage; their repairer is the closing
        # company block, which `_footer_company` reads.
        supplier = supplier or _footer_company(text)
        customer_match = re.search(
            r"(?:Clinic|Garage|Autosolutions|MOT Centre)\s+(.+?)\s+Invoice\s+[A-Z0-9/-]+",
            compact,
            flags=re.IGNORECASE,
        )
        # The positional vehicle band wins for vehicle identity: it reads the
        # whole row at once, so it cannot mistake a neighbouring column
        # heading for a value the way a label reader can.
        registration = vehicle.get("registration") or _labelled_registration(
            labels.get("registration")
        )
        return InvoiceHeader(
            invoice_number=invoice_number,
            invoice_date=_parse_date(labels.get("invoice_date"))
            or _parse_date(date_match.group(1) if date_match else None),
            supplier_name=supplier,
            supplier_vat_number=vat_number_match.group(1).strip() if vat_number_match else None,
            customer_name=labels.get("customer_name")
            or (strip_scan_artifacts(customer_match.group(1)) if customer_match else None),
            claim_reference=labels.get("claim_reference"),
            policy_number=labels.get("policy_number"),
            assessment_reference=labels.get("assessment_number"),
            registration=registration
            or (registration_match.group(1).strip() if registration_match else None),
            vin=vehicle.get("vin") or _labelled_value(labels.get("vin")),
            vehicle_make=vehicle.get("vehicle_make") or _labelled_value(labels.get("vehicle_make")),
            vehicle_model=vehicle.get("vehicle_model")
            or _labelled_value(labels.get("vehicle_model")),
            engine_cc=vehicle.get("engine_cc"),
            mileage=vehicle.get("mileage")
            or (int(mileage_match.group(1).replace(",", "")) if mileage_match else None),
        )

    def _totals(
        self,
        text: str,
        pages: list[PageAnalysis],
        lines: list[ExtractedLine] | None = None,
    ) -> InvoiceTotals:
        labels = read_label_values(text)

        def labelled(field: str) -> Decimal | None:
            value = labels.get(field)
            return parse_money(value) if value else None

        subtotal = _search_money(text, r"Sub\s*Total")
        non_vatable = _search_money(text, r"MOT")
        total_matches = re.findall(
            rf"(?<!Sub)\bTotal\b\s*[:£]?\s*{MONEY_PATTERN}", text, flags=re.IGNORECASE
        )
        # A document that prints a grand total under a label this reader knows
        # is read that way; "Claim" is the last resort, for the layout that
        # prints no such label at all.
        claim_total = _claim_grand_total_in(text)
        total = _first_not_none(
            labelled("gross_total"),
            money(total_matches[-1]) if total_matches else None,
            claim_total,
        )
        vat_rate_match = re.search(r"VAT\s*\((\d+(?:\.\d+)?)%\)", text, re.I)
        printed = _printed_section_totals(text)
        rolled_up = _rolled_up_section_totals(lines or [])
        section_sums = _section_sums(lines or [])

        def section_net(field: str) -> Decimal | None:
            """The printed section label, the section's own total, its summary row, its rows.

            All four outrank `_search_money`, whose first match for "Parts"
            on Format 1 is the "Sundry parts 3.50%" rate rather than a total.
            Each step tests for None rather than truth, so a printed
            "Total Additional Costs GBP 0.00" stays 0.00 instead of falling
            through to the next source.

            The summary-row step is what a fully rolled-up invoice with no
            "Total ..." labels at all (the EXL layout) has instead of the
            first two; where a document prints both, they are the same number
            read twice, and the printed label wins.
            """

            return _first_not_none(
                labelled(field),
                printed.get(field),
                rolled_up.get(field),
                section_sums.get(field),
            )

        labour_net = _first_not_none(section_net("labour_net"), _search_money(text, r"Labour"))
        parts_net = _first_not_none(section_net("parts_net"), _search_money(text, r"Parts"))
        paint_net = section_net("paint_net")
        extras_net = section_net("extras_net")
        # A label reader has to accept the bare label "VAT", which is also how
        # a VAT registration cell opens, so the rate-carrying spelling wins
        # outright and the bare one is guarded.
        vat_amount = _first_not_none(
            _explicit_vat_amount(text),
            _search_money(text, r"VAT\s*(?:\([^)]*\))?"),
            _guarded_labelled_vat(
                text, labelled("vat_total"), excluded=(labour_net, parts_net)
            ),
        )
        if subtotal is None:
            # A printed subtotal is the invoice's own answer and beats any
            # sum derived from the sections it prints beside it.
            subtotal = labelled("subtotal_net")
        section_nets = [
            value for value in (labour_net, parts_net, paint_net, extras_net) if value is not None
        ]
        if subtotal is None and section_nets:
            # An invoice that prints only section totals has no printed
            # subtotal to read.
            subtotal = sum(section_nets, Decimal("0"))
        totals = InvoiceTotals(
            labour_net=labour_net,
            parts_net=parts_net,
            paint_net=paint_net,
            extras_net=extras_net,
            subtotal_net=subtotal,
            vat_rate=as_decimal(vat_rate_match.group(1)) if vat_rate_match else Decimal("20"),
            vat_amount=vat_amount,
            non_vatable=non_vatable,
            total_gross=total,
        )
        candidates = {
            "labour_net": _total_source(pages, ("labour",), labour_net),
            "parts_net": _total_source(pages, ("parts",), parts_net),
            "paint_net": _total_source(pages, ("paint",), paint_net),
            "extras_net": _total_source(pages, ("additional", "extras"), extras_net),
            "subtotal_net": _total_source(pages, ("sub total", "subtotal"), subtotal),
            "vat_amount": _total_source(pages, ("vat",), vat_amount),
            "non_vatable": _total_source(pages, ("mot",), non_vatable),
            # "claim" is offered as a grand-total label only on a document
            # that actually printed one, so a "Claim Reference" row elsewhere
            # in the corpus is never a candidate for this box.
            "total_gross": _total_source(
                pages,
                ("total", "invoice total") + (("claim",) if claim_total is not None else ()),
                total,
            ),
        }
        totals.sources = {key: source for key, source in candidates.items() if source is not None}
        return totals
