from app.extraction.pdf_pipeline import _group_key, classify_page
from app.extraction.schemas import PageType


def test_invoice_total_outranks_embedded_estimate_reference() -> None:
    page_type, _, signals = classify_page(
        "Invoice I025735 Estimate: Q007052 Invoice Total £281.55",
        image_only=True,
    )
    assert page_type == PageType.INVOICE
    assert "invoice total" in signals


def test_explicit_estimate_order_is_not_an_invoice() -> None:
    page_type, _, _ = classify_page("ESTIMATE/ORDER Document No 12345", image_only=True)
    assert page_type == PageType.ESTIMATE


def test_group_key_rejects_prose_after_invoice_word() -> None:
    assert _group_key(PageType.INVOICE, "The invoice has been paid", 4) == "invoice:page-4"
    assert _group_key(PageType.INVOICE, "Invoice 91283", 1) == "invoice:91283"
