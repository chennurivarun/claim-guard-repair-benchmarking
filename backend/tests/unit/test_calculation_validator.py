"""Arithmetic reconciliation against the sections an invoice actually printed.

Every check here is a row sum against a *stated* section total. Two things
decide whether the sum is right: which rows belong to the section, and whether
the extraction recognised any sections at all. Getting the second one wrong is
what makes a correct invoice look fraudulent -- "unknown" is the code every row
of an unrecognised invoice carries, so reading it as a section splits the rows
away from the total they add up to.
"""

from __future__ import annotations

from decimal import Decimal

from app.extraction.calculation_validator import SECTION_FAMILIES, validate_invoice
from app.extraction.schemas import (
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
)

SOURCE = FieldSource(page_number=1, extraction_method="native", confidence=0.98)


def _line(
    sequence_no: int,
    description: str,
    total: str,
    *,
    line_item_type: str | None,
    item_kind: str = "part",
    is_section_total: bool = False,
) -> ExtractedLine:
    return ExtractedLine(
        sequence_no=sequence_no,
        raw_description=description,
        normalised_description=description.lower(),
        item_kind=item_kind,
        quantity=Decimal("1"),
        unit_price_net=Decimal(total),
        line_total_net=Decimal(total),
        line_item_type=line_item_type,
        raw_category=description,
        is_section_total=is_section_total,
        source=SOURCE,
    )


def _invoice(lines: list[ExtractedLine], **totals: str | None) -> ExtractedInvoice:
    return ExtractedInvoice(
        header=InvoiceHeader(invoice_number="INV-1"),
        totals=InvoiceTotals(
            **{
                name: (None if value is None else Decimal(value))
                for name, value in totals.items()
            }
        ),
        line_items=lines,
        page_numbers=[1],
        extraction_method="native",
        extraction_confidence=0.98,
    )


def _by_type(invoice: ExtractedInvoice) -> dict[str, object]:
    return {finding.finding_type: finding for finding in validate_invoice(invoice)}


def test_section_families_are_the_inverse_of_the_parser_total_fields() -> None:
    """One source of truth: the parser says which stated total each section
    code belongs to, and the families are read back off that map. "sundry"
    prints no total of its own and folds into parts; "specialist_operation"
    folds into extras; the never-produced "additional" code is gone."""

    assert SECTION_FAMILIES == {
        "labour": frozenset({"labour"}),
        "parts": frozenset({"parts", "sundry"}),
        "paint": frozenset({"paint", "paint_materials"}),
        "extras": frozenset({"extras", "specialist_operation"}),
    }


def test_unknown_section_codes_are_not_read_as_recognised_sections() -> None:
    """An invoice whose headings the parser did not recognise still gets
    "unknown" stamped on every row. Treating that as a section leaves the
    parts family empty, so the stated parts total is added to the subtotal as
    a summary-only section *on top of* the rows it is the total of, and a
    correct invoice fails SUBTOTAL_MISMATCH at double its own value."""

    invoice = _invoice(
        [
            _line(1, "Front bumper", "300.00", line_item_type="unknown"),
            _line(2, "Wheel alignment", "190.84", line_item_type="unknown"),
        ],
        parts_net="490.84",
        subtotal_net="490.84",
    )

    findings = _by_type(invoice)

    assert findings["PARTS_TOTAL_MISMATCH"].status == "pass"
    assert findings["PARTS_TOTAL_MISMATCH"].expected == Decimal("490.84")
    assert findings["SUBTOTAL_MISMATCH"].status == "pass"
    assert findings["SUBTOTAL_MISMATCH"].expected == Decimal("490.84")


def test_unknown_section_codes_still_fail_a_wrong_parts_total() -> None:
    """The same root cause, the other way round: reading "unknown" as a
    section empties the parts sum, so 0.00 rows against a 0.00 stated total
    passes and a real disagreement is silenced."""

    invoice = _invoice(
        [
            _line(index, f"Part {index}", "81.81", line_item_type="unknown")
            for index in range(1, 7)
        ],
        parts_net="0.00",
        subtotal_net="490.86",
    )

    findings = _by_type(invoice)

    assert findings["PARTS_TOTAL_MISMATCH"].status == "fail"
    assert findings["PARTS_TOTAL_MISMATCH"].expected == Decimal("490.86")
    assert findings["PARTS_TOTAL_MISMATCH"].found == Decimal("0.00")


def test_a_row_in_no_stated_section_keeps_its_place_in_the_parts_sum() -> None:
    """``line_item_type`` is an open vocabulary, so a row can carry a code no
    printed total covers. Recognised sections elsewhere on the invoice must
    not make such a row disappear from every row sum."""

    invoice = _invoice(
        [
            _line(1, "Front bumper", "300.00", line_item_type="parts"),
            _line(2, "Courtesy car", "50.00", line_item_type="storage_charge"),
        ],
        parts_net="350.00",
        subtotal_net="350.00",
    )

    findings = _by_type(invoice)

    assert findings["PARTS_TOTAL_MISMATCH"].status == "pass"
    assert findings["PARTS_TOTAL_MISMATCH"].expected == Decimal("350.00")


def test_paint_and_extras_rows_are_reconciled_against_their_own_totals() -> None:
    """Before sections were read, a specialist-operation row was counted in
    the parts sum and a wrong extras total was caught there. Now that its rows
    belong to extras, extras has to check them itself."""

    invoice = _invoice(
        [
            _line(1, "Front bumper", "300.00", line_item_type="parts"),
            _line(2, "ADAS calibration", "190.84", line_item_type="specialist_operation"),
            _line(3, "Paint labour", "120.00", line_item_type="paint", item_kind="labour"),
        ],
        parts_net="300.00",
        extras_net="190.84",
        paint_net="120.00",
        subtotal_net="610.84",
    )

    findings = _by_type(invoice)

    assert findings["PARTS_TOTAL_MISMATCH"].status == "pass"
    assert findings["EXTRAS_TOTAL_MISMATCH"].status == "pass"
    assert findings["EXTRAS_TOTAL_MISMATCH"].expected == Decimal("190.84")
    assert findings["PAINT_TOTAL_MISMATCH"].status == "pass"
    assert findings["PAINT_TOTAL_MISMATCH"].expected == Decimal("120.00")


def test_a_wrong_extras_total_now_fails_instead_of_going_unchecked() -> None:
    invoice = _invoice(
        [
            _line(1, "Front bumper", "300.00", line_item_type="parts"),
            _line(2, "ADAS calibration", "190.84", line_item_type="specialist_operation"),
        ],
        parts_net="300.00",
        extras_net="90.84",
        subtotal_net="490.84",
    )

    findings = _by_type(invoice)

    assert findings["EXTRAS_TOTAL_MISMATCH"].status == "fail"
    assert findings["EXTRAS_TOTAL_MISMATCH"].expected == Decimal("190.84")
    assert findings["EXTRAS_TOTAL_MISMATCH"].found == Decimal("90.84")
    assert findings["EXTRAS_TOTAL_MISMATCH"].severity == "high"


def test_a_wrong_paint_total_now_fails_instead_of_going_unchecked() -> None:
    invoice = _invoice(
        [
            _line(1, "Paint labour", "400.00", line_item_type="paint", item_kind="labour"),
            _line(2, "Paint materials", "129.57", line_item_type="paint_materials"),
        ],
        paint_net="429.57",
        subtotal_net="529.57",
    )

    findings = _by_type(invoice)

    assert findings["PAINT_TOTAL_MISMATCH"].status == "fail"
    assert findings["PAINT_TOTAL_MISMATCH"].expected == Decimal("529.57")
    assert findings["PAINT_TOTAL_MISMATCH"].found == Decimal("429.57")


def test_a_rolled_up_paint_section_is_not_applicable_not_a_mismatch() -> None:
    """A section stated only in the summary has no rows to reconcile. Its
    stated amount still has to reach the subtotal check."""

    invoice = _invoice(
        [
            _line(1, "Front bumper", "300.00", line_item_type="parts"),
            _line(
                2,
                "Total Paint & Materials",
                "429.57",
                line_item_type="paint_materials",
                item_kind="unknown",
                is_section_total=True,
            ),
        ],
        parts_net="300.00",
        paint_net="429.57",
        subtotal_net="729.57",
    )

    findings = _by_type(invoice)

    assert findings["PAINT_TOTAL_MISMATCH"].status == "not_applicable"
    assert "summary" in findings["PAINT_TOTAL_MISMATCH"].explanation.lower()
    assert findings["SUBTOTAL_MISMATCH"].status == "pass"


def test_an_invoice_with_no_paint_or_extras_section_reports_nothing_to_check() -> None:
    invoice = _invoice(
        [_line(1, "Front bumper", "300.00", line_item_type="parts")],
        parts_net="300.00",
        subtotal_net="300.00",
    )

    findings = _by_type(invoice)

    assert findings["PAINT_TOTAL_MISMATCH"].status == "not_applicable"
    assert findings["EXTRAS_TOTAL_MISMATCH"].status == "not_applicable"
    assert findings["PARTS_TOTAL_MISMATCH"].status == "pass"
