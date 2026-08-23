"""Header and totals plausibility guards found via the client's Auda batch."""

from decimal import Decimal

from app.extraction.schemas import InvoiceHeader, InvoiceTotals


def test_claim_reference_is_rejected_as_invoice_number():
    header = InvoiceHeader(invoice_number="Claim Reference: 2025/ABC/12345")
    assert header.invoice_number is None


def test_real_invoice_number_is_kept():
    assert InvoiceHeader(invoice_number="ABCD12345").invoice_number == "ABCD12345"
    assert InvoiceHeader(invoice_number="91283").invoice_number == "91283"


def test_lone_vat_amount_is_discarded():
    totals = InvoiceTotals(vat_amount=Decimal("1423.92"))
    assert totals.vat_amount is None


def test_vat_exceeding_its_base_is_discarded():
    totals = InvoiceTotals(
        subtotal_net=Decimal("100.00"), vat_amount=Decimal("1423.92")
    )
    assert totals.vat_amount is None


def test_plausible_vat_is_kept():
    totals = InvoiceTotals(
        subtotal_net=Decimal("1423.92"),
        vat_amount=Decimal("284.78"),
        total_gross=Decimal("1708.70"),
    )
    assert totals.vat_amount == Decimal("284.78")
