from __future__ import annotations

from decimal import Decimal

from app.domain.money import ZERO, money
from app.extraction.schemas import ExtractedInvoice, MathFinding


def _finding(
    finding_type: str,
    expected: Decimal | None,
    found: Decimal | None,
    tolerance: Decimal,
    *,
    line_sequence_no: int | None = None,
    severity: str = "warning",
    explanation: str,
) -> MathFinding:
    if expected is None or found is None:
        return MathFinding(
            finding_type="MISSING_VALUE",
            status="not_applicable",
            expected=expected,
            found=found,
            difference=None,
            tolerance=tolerance,
            severity="review",
            line_sequence_no=line_sequence_no,
            explanation=explanation,
        )
    difference = money(found - expected) or ZERO
    return MathFinding(
        finding_type=finding_type,
        status="pass" if abs(difference) <= tolerance else "fail",
        expected=money(expected),
        found=money(found),
        difference=difference,
        tolerance=tolerance,
        severity="info" if abs(difference) <= tolerance else severity,
        line_sequence_no=line_sequence_no,
        explanation=explanation,
    )


def _not_applicable(finding_type: str, *, explanation: str) -> MathFinding:
    return MathFinding(
        finding_type=finding_type,
        status="not_applicable",
        expected=None,
        found=None,
        difference=None,
        tolerance=None,
        severity="info",
        line_sequence_no=None,
        explanation=explanation,
    )


#: Which printed section a row belongs to, per stated total. A total and the
#: rows that make it up have to land in the same family, or the row sum is
#: reconciled against the wrong printed figure: a repairer's "Total Parts"
#: covers its sundry-parts line, and "Additional charges" covers the
#: specialist-operation rows printed above it. Codes come from
#: :mod:`app.domain.line_item_type`, which is an open vocabulary -- an
#: unrecognised section simply belongs to no family and is only ever counted in
#: the subtotal.
SECTION_FAMILIES: dict[str, frozenset[str]] = {
    "labour": frozenset({"labour"}),
    "parts": frozenset({"parts", "sundry"}),
    "paint": frozenset({"paint", "paint_materials"}),
    "extras": frozenset({"extras", "additional", "specialist_operation"}),
}


def validate_invoice(
    invoice: ExtractedInvoice,
    *,
    line_tolerance: Decimal = Decimal("0.02"),
    invoice_tolerance: Decimal = Decimal("0.05"),
) -> list[MathFinding]:
    findings: list[MathFinding] = []
    # A section total printed instead of the section's rows is evidence of the
    # section's value, never a priced row. It must not enter any row sum, or
    # every rolled-up invoice reports a mismatch against its own totals.
    itemised = [line for line in invoice.line_items if not line.is_section_total]
    for line in itemised:
        if line.quantity is None or line.unit_price_net is None or line.line_total_net is None:
            findings.append(
                _finding(
                    "LINE_MATH_MISMATCH",
                    None,
                    line.line_total_net,
                    line_tolerance,
                    line_sequence_no=line.sequence_no,
                    explanation=f"Line {line.sequence_no} lacks quantity, unit price or total.",
                )
            )
            continue
        expected = line.quantity * line.unit_price_net
        findings.append(
            _finding(
                "LINE_MATH_MISMATCH",
                expected,
                line.line_total_net,
                line_tolerance,
                line_sequence_no=line.sequence_no,
                explanation=f"Quantity multiplied by net unit price for line {line.sequence_no}.",
            )
        )

    comparable_lines = [
        line.line_total_net
        for line in itemised
        if line.line_total_net is not None and line.vat_applicable
    ]
    # Section codes only exist once the extraction recognised the printed
    # sections. Without them the historical attribution stands unchanged:
    # labour is item_kind "labour", parts is every other vatable row. A fully
    # rolled-up invoice has no itemised rows to read codes off, so its section
    # totals are the only evidence of its sections there is.
    coded = itemised or invoice.line_items
    sectioned = any(line.line_item_type for line in coded)

    def section_rows(code: str) -> list[Decimal]:
        if sectioned:
            family = SECTION_FAMILIES[code]
            return [
                line.line_total_net
                for line in itemised
                if line.line_total_net is not None and line.line_item_type in family
            ]
        if code == "labour":
            return [
                line.line_total_net
                for line in itemised
                if line.line_total_net is not None and line.item_kind == "labour"
            ]
        if code == "parts":
            return [
                line.line_total_net
                for line in itemised
                if line.line_total_net is not None
                and line.vat_applicable
                and line.item_kind != "labour"
            ]
        return []

    stated = {
        "labour": invoice.totals.labour_net,
        "parts": invoice.totals.parts_net,
        "paint": invoice.totals.paint_net,
        "extras": invoice.totals.extras_net,
    }
    if not sectioned:
        # Paint and extras cannot be attributed to rows without section codes,
        # so they stay out of the reconciliation exactly as they always have.
        stated = {"labour": stated["labour"]}
    # Sections the invoice states a total for but prints no rows for. Their
    # stated amount is the only evidence of the section's value, so the
    # section's own row check is not applicable and the subtotal uses the
    # stated figure instead of an absent row sum.
    summary_only = {
        code
        for code, amount in stated.items()
        if amount is not None and amount != ZERO and not section_rows(code)
    }

    calculated_labour = sum(section_rows("labour"), ZERO)
    calculated_parts = sum(section_rows("parts"), ZERO)
    calculated_subtotal = sum(comparable_lines, ZERO) + sum(
        (stated[code] for code in sorted(summary_only)), ZERO
    )
    findings.append(
        _not_applicable(
            "LABOUR_TOTAL_MISMATCH",
            explanation=(
                "Labour is stated only in the invoice summary, so there are no "
                "detailed labour lines to reconcile. The stated labour amount is "
                "included in the subtotal, VAT and gross-total checks."
            ),
        )
        if "labour" in summary_only
        else _finding(
            "LABOUR_TOTAL_MISMATCH",
            calculated_labour,
            invoice.totals.labour_net,
            invoice_tolerance,
            severity="high",
            explanation="Sum of extracted labour lines against the stated labour total.",
        )
    )
    findings.append(
        _not_applicable(
            "PARTS_TOTAL_MISMATCH",
            explanation=(
                "Parts are stated only in the invoice summary, so there are no "
                "detailed parts lines to reconcile. The stated parts amount is "
                "included in the subtotal, VAT and gross-total checks."
            ),
        )
        if "parts" in summary_only
        else _finding(
            "PARTS_TOTAL_MISMATCH",
            calculated_parts,
            invoice.totals.parts_net,
            invoice_tolerance,
            severity="high",
            explanation=(
                "Sum of the extracted parts-section lines against the stated parts total."
                if sectioned
                else "Sum of extracted vatable non-labour lines against the stated parts total."
            ),
        )
    )
    findings.append(
        _finding(
            "SUBTOTAL_MISMATCH",
            calculated_subtotal,
            invoice.totals.subtotal_net,
            invoice_tolerance,
            severity="high",
            explanation=(
                "Sum of vatable extracted line totals plus the stated total of every "
                "section the invoice rolled up against invoice subtotal."
            ),
        )
    )

    if invoice.totals.subtotal_net is not None and invoice.totals.vat_rate is not None:
        expected_vat = invoice.totals.subtotal_net * invoice.totals.vat_rate / Decimal("100")
    else:
        expected_vat = None
    findings.append(
        _finding(
            "VAT_MISCALC",
            expected_vat,
            invoice.totals.vat_amount,
            line_tolerance,
            severity="high",
            explanation="VAT on the vatable subtotal using the invoice's stated rate.",
        )
    )

    if invoice.totals.subtotal_net is not None and invoice.totals.vat_amount is not None:
        expected_total = (
            invoice.totals.subtotal_net
            + invoice.totals.vat_amount
            + (invoice.totals.non_vatable or ZERO)
        )
    else:
        expected_total = None
    findings.append(
        _finding(
            "TOTAL_MISMATCH",
            expected_total,
            invoice.totals.total_gross,
            invoice_tolerance,
            severity="high",
            explanation="Subtotal plus VAT plus non-vatable charges against gross total.",
        )
    )
    return findings
