from app.extraction.pdf_pipeline import (
    _group_key,
    _reclassify_priced_assessment_pages,
    _relink_invoice_continuation_pages,
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


def test_invoice_totals_page_keeps_the_previous_numbered_group() -> None:
    first = _page(
        1,
        "INVOICE\nInvoice Number: 343653726836/1~3538\nParts\nDoor 847.73",
        PageType.INVOICE,
    )
    first.group_key = "invoice:343653726836/1~3538"
    totals = _page(
        2,
        "E.P.A. Charge 22.00\nTotal Labour 2509.20\nVAT @20% 982.52\nInvoice total 5895.11",
        PageType.INVOICE,
    )
    totals.group_key = "invoice:page-2"

    _relink_invoice_continuation_pages([first, totals])

    assert totals.group_key == first.group_key
    assert "invoice continuation" in totals.classification_signals


def test_separate_numberless_invoice_heading_is_not_joined() -> None:
    first = _page(
        1,
        "INVOICE\nInvoice Number: INV-101\nDoor 847.73",
        PageType.INVOICE,
    )
    first.group_key = "invoice:INV-101"
    second = _page(
        2,
        "INVOICE\nLabour 200.00\nVAT 40.00\nInvoice total 240.00",
        PageType.INVOICE,
    )
    second.group_key = "invoice:page-2"

    _relink_invoice_continuation_pages([first, second])

    assert second.group_key == "invoice:page-2"


def test_authorised_assessment_keeps_wrapped_schedule_pages() -> None:
    summary = _page(
        1,
        "Assessment report\nSummary Information\nAssessment Number D7576879",
        PageType.ENGINEER_ASSESSMENT,
    )
    wrapped_labour = _page(
        2,
        "1000\nREPAIR LEFT SILL / BODY\nAREA\n15\n1000\nCORROSION PROTECTION\n5",
        PageType.OTHER,
    )
    wrapped_parts = _page(
        3,
        "1781\nL/R DOOR\n7700332300\n0%\n847.73\nTotal Parts\n1237.50",
        PageType.INVOICE,
    )
    wrapped_parts.classification_signals = ["financial table", "5 amounts"]
    wrapped_parts.group_key = "invoice:page-3"

    _reclassify_priced_assessment_pages([summary, wrapped_labour, wrapped_parts])

    assert [page.page_type for page in (summary, wrapped_labour, wrapped_parts)] == [
        PageType.ENGINEER_ASSESSMENT,
        PageType.ENGINEER_ASSESSMENT,
        PageType.ENGINEER_ASSESSMENT,
    ]
    assert wrapped_parts.group_key is None


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


def test_engineer_report_marker_keeps_gt_motive_schedule_as_assessment() -> None:
    """A GT Motive-style "Engineer Report" template carries no Audatex
    Summary Information / Assessment Number heading, but it is still an
    authorised estimate. Its priced Paint and Materials schedule must stay
    ENGINEER_ASSESSMENT rather than being flipped to INVOICE by the widened
    _SCHEDULE_HEADING_PATTERN."""

    identity_page = _page(
        1,
        "Engineer Report\nClaim ABC 123456\n",
        PageType.ENGINEER_ASSESSMENT,
    )
    schedule_page = _page(
        3,
        "Engineer Report   GT Motive, A.A 03/03/2026 - 3/3\n"
        "Paint and Materials\n"
        "Paint labour 3.60 hrs 45.00 162.00\n"
        "Paint materials consumables 128.40\n"
        "Primer and clearcoat 96.75\n"
        "Masking materials 22.30\n",
        PageType.ENGINEER_ASSESSMENT,
    )
    pages = [identity_page, schedule_page]

    _reclassify_priced_assessment_pages(pages)

    assert [page.page_type for page in pages] == [
        PageType.ENGINEER_ASSESSMENT,
        PageType.ENGINEER_ASSESSMENT,
    ]


def test_other_page_rescue_survives_authorised_assessment_gate() -> None:
    """The identity gate must only ever skip ENGINEER_ASSESSMENT pages: an
    authorised assessment elsewhere in the bundle must not disable the
    OTHER-page rescue for a genuinely unrelated priced page."""

    summary_page = _page(
        1,
        "Assessment Report\nSummary Information\nAssessment Number D7576879",
        PageType.ENGINEER_ASSESSMENT,
    )
    other_page = _page(
        2,
        "Repair account for services rendered\n"
        "Bumper cover supply and fit 245.00\n"
        "Headlamp bracket replacement 88.50\n"
        "Wheel alignment check 45.00",
        PageType.OTHER,
    )
    pages = [summary_page, other_page]

    _reclassify_priced_assessment_pages(pages)

    assert summary_page.page_type == PageType.ENGINEER_ASSESSMENT
    assert other_page.page_type == PageType.INVOICE
    assert other_page.group_key is not None


def test_schedule_continuation_page_becomes_assessment_evidence() -> None:
    """A LABOUR schedule that runs onto a page with no identity marker of its
    own classifies as OTHER. Leaving it OTHER while the assessment parser
    reads it makes the document say one thing and the operations another, so
    the page is reclassified. Its rows end in work units, not money, which is
    why the priced-row rescue never wanted it."""

    summary_page = _page(
        1,
        "Assessment report\nSummary Information\nAssessment Number   D7576879\n"
        "LABOUR\nTime Basis 10 WU=1HR.Price £80.00/HR\n"
        "52904A00   REPAIR LOWER TAILGATE   40.0\n",
        PageType.ENGINEER_ASSESSMENT,
    )
    continuation_page = _page(
        2,
        "865246R77 ZAX   REPAIR R/R BUMPER   20.0\n"
        "NO MUMBER   REPAIR REAR BUMPER   30.0\n"
        "0281   R+R REAR BUMPER CPL   5.0\n"
        "   Total Work Units   139.0\n",
        PageType.OTHER,
    )
    pages = [summary_page, continuation_page]

    _reclassify_priced_assessment_pages(pages)

    assert continuation_page.page_type == PageType.ENGINEER_ASSESSMENT
    assert "assessment continuation" in continuation_page.classification_signals
    assert continuation_page.group_key is None


def test_remittance_page_after_an_assessment_is_not_a_continuation() -> None:
    """A payment page carries no schedule rows at all -- every line it prints
    is a total, a balance or a payment -- so it is neither rescued to INVOICE
    nor absorbed into the assessment. It stays OTHER, which keeps it out of
    the assessment parser and off the vision-invoice candidate list."""

    summary_page = _page(
        1,
        "Assessment report\nSummary Information\nAssessment Number   D7576879\n",
        PageType.ENGINEER_ASSESSMENT,
    )
    remittance_page = _page(
        2,
        "Payment received on account   250.00\n"
        "Balance carried forward   120.00\n"
        "Discount agreed   35.00\n",
        PageType.OTHER,
    )
    pages = [summary_page, remittance_page]

    _reclassify_priced_assessment_pages(pages)

    assert remittance_page.page_type == PageType.OTHER
    assert remittance_page.classification_signals == []


def test_priced_garage_receipt_behind_an_assessment_is_still_an_invoice() -> None:
    """The continuation rule must not swallow a genuinely separate priced
    document bound behind the report: the priced-row rescue is tried first."""

    summary_page = _page(
        1,
        "Assessment report\nSummary Information\nAssessment Number   D7576879\n",
        PageType.ENGINEER_ASSESSMENT,
    )
    receipt_page = _page(
        2,
        "Invoice 88214   Corner Garage Ltd\n"
        "Wiper blade set   12.00\n"
        "Screen wash refill   12.00\n"
        "Bulb kit   12.00\n"
        "Total   36.00\n",
        PageType.OTHER,
    )
    pages = [summary_page, receipt_page]

    _reclassify_priced_assessment_pages(pages)

    assert receipt_page.page_type == PageType.INVOICE
    assert receipt_page.group_key is not None


def test_group_key_finds_invoice_number_when_date_matches_first() -> None:
    """re.search only ever inspects the first match of the pattern, so on
    real client text with "Invoice Date" printed above "Invoice Number" the
    first hit is the non-digit "Date" candidate, which the old code returned
    as a dead end (falling through to invoice:page-N). Iterating with
    re.finditer must keep scanning for the first digit-bearing candidate."""

    key = _group_key(
        PageType.INVOICE,
        "Invoice Date      26/11/2025\nInvoice Number    22564547648/1~AJ123456\n",
        1,
    )
    assert key is not None
    assert "22564547648/1~AJ123456" in key
