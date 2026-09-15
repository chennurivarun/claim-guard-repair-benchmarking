from app.extraction.pdf_pipeline import (
    _group_key,
    _reclassify_priced_assessment_pages,
    classify_page,
)
from app.extraction.schemas import PageAnalysis, PageType


def _page(number: int, text: str, page_type: PageType) -> PageAnalysis:
    """Minimal PageAnalysis for exercising the reclassification pass directly."""

    return PageAnalysis(
        page_number=number,
        width=595.0,
        height=842.0,
        rotation=0,
        native_character_count=len(text),
        positioned_word_count=len(text.split()),
        image_count=0,
        extraction_method="native",
        extraction_confidence=0.98,
        text=text,
        page_type=page_type,
        classification_confidence=0.9,
    )


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


def test_group_key_keeps_tilde_inside_invoice_number() -> None:
    key = _group_key(
        PageType.INVOICE, "Invoice Number: 343653726836/1~3538", 1
    )
    assert key == "invoice:343653726836/1~3538"


def test_assessment_identity_gate_keeps_priced_pages_as_assessment_evidence() -> None:
    """An authorised Audatex estimate must never have its PARTS/EXTRAS/LABOUR
    pages flipped to INVOICE, however many priced rows they carry -- the
    Summary Information / Assessment Report identity signal wins outright."""

    summary_page = _page(
        1,
        "Assessment Report\nSummary Information\nClaim Reference: 2025/ABC/12345",
        PageType.ENGINEER_ASSESSMENT,
    )
    parts_page = _page(
        2,
        "PARTS\n"
        "1720   R/SCREW              0019846529   2.80\n"
        "1740   R/DOOR MIRROR HSG    0008111122   19.10\n"
        "1760   R/D-MIRROR INDICATOR 0018229020   27.10\n"
        "1764   R/OSTRO MIRROR       0008107219   76.00\n"
        "1768   R/MIRROR FRAME       0008130356   11.75\n",
        PageType.ENGINEER_ASSESSMENT,
    )
    pages = [summary_page, parts_page]

    _reclassify_priced_assessment_pages(pages)

    assert [page.page_type for page in pages] == [
        PageType.ENGINEER_ASSESSMENT,
        PageType.ENGINEER_ASSESSMENT,
    ]


def test_other_page_with_priced_rows_still_rescued_to_invoice() -> None:
    """Non-assessment bundles keep the OTHER-page rescue: no identity signal
    is present anywhere in the document, so 2+ priced rows on an OTHER page
    still promote it to INVOICE."""

    assessment_page = _page(
        1,
        "Engineer Report\nVehicle inspected on site, no summary grid present.",
        PageType.ENGINEER_ASSESSMENT,
    )
    other_page = _page(
        2,
        "Wiring harness repair kit ABC   45.00\n"
        "Bumper clip set XYZ   12.50\n"
        "Headlamp assembly unit   150.75\n",
        PageType.OTHER,
    )
    pages = [assessment_page, other_page]

    _reclassify_priced_assessment_pages(pages)

    assert other_page.page_type == PageType.INVOICE
    assert other_page.group_key is not None
