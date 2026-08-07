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


def validate_invoice(
    invoice: ExtractedInvoice,
    *,
    line_tolerance: Decimal = Decimal("0.02"),
    invoice_tolerance: Decimal = Decimal("0.05"),
) -> list[MathFinding]:
    findings: list[MathFinding] = []
    for line in invoice.line_items:
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
        for line in invoice.line_items
        if line.line_total_net is not None and line.vat_applicable
    ]
    labour_lines = [
        line.line_total_net
        for line in invoice.line_items
        if line.line_total_net is not None and line.item_kind == "labour"
    ]
    calculated_labour = sum(labour_lines, ZERO)
    summary_only_labour = (
        not labour_lines
        and invoice.totals.labour_net is not None
        and invoice.totals.labour_net != ZERO
    )
    calculated_subtotal = sum(comparable_lines, ZERO) + (
        invoice.totals.labour_net if summary_only_labour else ZERO
    )
    calculated_parts = sum(
        (
            line.line_total_net
            for line in invoice.line_items
            if line.line_total_net is not None
            and line.vat_applicable
            and line.item_kind != "labour"
        ),
        ZERO,
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
        if summary_only_labour
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
            _finding(
                "PARTS_TOTAL_MISMATCH",
                calculated_parts,
                invoice.totals.parts_net,
                invoice_tolerance,
                severity="high",
                explanation="Sum of extracted vatable non-labour lines against the stated parts total.",
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
                "Sum of vatable extracted line totals plus any summary-only labour "
                "amount against invoice subtotal."
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
