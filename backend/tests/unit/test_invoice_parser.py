import tempfile
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from unittest import mock

import fitz
import pytest

import app.services.document_processing as document_processing
from app.extraction.calculation_validator import validate_invoice
from app.extraction.invoice_parser import (
    InvoiceParser,
    _claim_grand_total,
    _footer_company,
    _guess_item_kind,
    _has_uncertain_lines,
)
from app.extraction.schemas import (
    BoundingBox,
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
    OCRWord,
    PageAnalysis,
    PageType,
)

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[3] / "sample-data"
CLIENT_FORMATS_DIR = SAMPLE_DATA_DIR / "client-formats"
_CONVERTED_DIRS: list[tempfile.TemporaryDirectory] = []


class _TablePage:
    def extract_tables(self):
        return [
            [
                ["Description", "Qty", "Unit", "Subtotal"],
                ["Oil Filter", "1", "£8.95", "£8.95"],
                ["Spark Plugs", "4", "£9.81", "£39.24"],
            ],
            [["Labour", "£210.00"], ["TOTAL", "£556.17"]],
        ]


def _page() -> PageAnalysis:
    return PageAnalysis(
        page_number=1,
        width=595,
        height=842,
        rotation=0,
        native_character_count=100,
        positioned_word_count=20,
        image_count=0,
        extraction_method="native",
        extraction_confidence=0.98,
        text="",
        page_type=PageType.INVOICE,
        classification_confidence=0.98,
    )


@cache
def _client_invoice(filename: str, *, with_words: bool = False) -> ExtractedInvoice:
    """Parse a client `.docx` invoice through the real upload-normalisation path.

    `shutil.which` is forced to `None` so the deterministic pure-Python
    reportlab conversion is used rather than LibreOffice if it happens to be
    installed, exactly as `test_client_format_fixtures` does.

    ``with_words`` positions every word on the page, which is what
    `InvoiceParser` needs to give a total a bounding box. Off by default,
    because only the provenance tests look at one.
    """

    source = CLIENT_FORMATS_DIR / filename
    if not source.is_file():
        pytest.skip(f"Client-format fixture {filename} is not available")
    with mock.patch.object(document_processing.shutil, "which", return_value=None):
        normalised = document_processing.normalise_document_upload(
            source.name, source.read_bytes()
        )
    directory = tempfile.TemporaryDirectory()
    _CONVERTED_DIRS.append(directory)
    pdf_path = Path(directory.name) / normalised.stored_filename
    pdf_path.write_bytes(normalised.content)

    return _parse_pdf(pdf_path, with_words=with_words)


def _parse_pdf(pdf_path: Path, *, with_words: bool = False) -> ExtractedInvoice:
    document = fitz.open(pdf_path)
    try:
        pages = [
            PageAnalysis(
                page_number=number,
                width=page.rect.width,
                height=page.rect.height,
                rotation=0,
                native_character_count=len(page.get_text("text")),
                positioned_word_count=len(page.get_text("words")),
                image_count=0,
                extraction_method="native",
                extraction_confidence=0.98,
                text=page.get_text("text"),
                words=_positioned_words(page) if with_words else [],
                page_type=PageType.INVOICE,
                classification_confidence=0.98,
            )
            for number, page in enumerate(document, start=1)
        ]
    finally:
        document.close()
    return InvoiceParser().parse_group(pdf_path, pages)


def _positioned_words(page) -> list[OCRWord]:
    return [
        OCRWord(text=text, confidence=1.0, bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1))
        for x0, y0, x1, y1, text, *_ in page.get_text("words")
        if text.strip()
    ]


@cache
def _corpus_invoice(relative_path: str) -> ExtractedInvoice:
    """Parse a corpus PDF that is already a PDF -- no upload normalisation."""

    source = SAMPLE_DATA_DIR / relative_path
    if not source.is_file():
        pytest.skip(f"Corpus fixture {relative_path} is not available")
    return _parse_pdf(source)


def _schedule_and_section_totals(text: str) -> list[ExtractedLine]:
    """Run one page of printed text through both row readers, as `parse_group` does."""

    parser = InvoiceParser()
    page = _page().model_copy(update={"text": text})
    lines = parser._schedule_text_lines(page, 1)
    return lines + parser._rolled_up_total_lines(text, [page], len(lines) + 1, lines)


def _of_type(invoice: ExtractedInvoice, line_item_type: str) -> list[ExtractedLine]:
    return [
        line
        for line in invoice.line_items
        if line.line_item_type == line_item_type and not line.is_section_total
    ]


def _section_totals(invoice: ExtractedInvoice) -> dict[str, Decimal | None]:
    return {
        line.line_item_type: line.line_total_net
        for line in invoice.line_items
        if line.is_section_total
    }


def test_native_parser_reads_generic_description_quantity_unit_subtotal_table() -> None:
    lines = InvoiceParser()._native_table_lines(_TablePage(), _page(), 1)

    assert [line.raw_description for line in lines] == ["Oil Filter", "Spark Plugs"]
    assert [line.quantity for line in lines] == [Decimal("1"), Decimal("4")]
    assert [line.unit_price_net for line in lines] == [Decimal("8.95"), Decimal("9.81")]
    assert [line.line_total_net for line in lines] == [Decimal("8.95"), Decimal("39.24")]


def test_ocr_parser_reuses_azure_structured_tables_before_line_regex() -> None:
    page = _page().model_copy(
        update={
            "extraction_method": "azure_layout",
            "extraction_confidence": 0.94,
            "tables": [
                [
                    ["Operation", "Part No", "Qty", "Unit Price", "Total"],
                    ["Oil Filter", "OF-1", "1", "8.95", "8.95"],
                    ["Spark Plugs", "SP-4", "4", "9.81", "39.24"],
                ]
            ],
        }
    )

    lines = InvoiceParser()._ocr_lines(page, 1)

    assert [line.raw_description for line in lines] == ["Oil Filter", "Spark Plugs"]
    assert [line.part_number for line in lines] == ["OF-1", "SP-4"]
    assert [line.line_total_net for line in lines] == [Decimal("8.95"), Decimal("39.24")]
    assert all(line.source.extraction_method == "ocr" for line in lines)


def test_ocr_parser_recognises_parts_heading_with_column_labels() -> None:
    page = _page().model_copy(
        update={
            "extraction_method": "ocr",
            "extraction_confidence": 0.86,
            "text": (
                "PARTS Qty Unit Value\n"
                "oil filter 1.00 11.10 11.10\n"
                "FULLY SYN ENG OIL 9.50 7.50 71.25\n"
            ),
        }
    )

    lines = InvoiceParser()._ocr_lines(page, 1)

    assert [line.raw_description for line in lines] == ["oil filter", "FULLY SYN ENG OIL"]
    assert all(line.item_kind == "part" for line in lines)


def test_header_reads_compact_registration_make_and_model_line() -> None:
    header = InvoiceParser()._header(
        "ST ALBANS CAR CLINIC\n"
        "Invoice #9400 Date: 10/12/2025\n"
        "KU65 EOK - Vauxhall Adam Glam\n"
    )

    assert header.registration == "KU65 EOK"
    assert header.vehicle_make == "Vauxhall"
    assert header.vehicle_model == "Adam Glam"


def test_totals_derive_net_subtotal_from_parts_and_labour() -> None:
    totals = InvoiceParser()._totals(
        "Labour £210.00\nParts £207.77\nVAT £83.55\nMOT £54.85\nTOTAL £556.17",
        [_page()],
    )

    assert totals.subtotal_net == Decimal("417.77")


def test_generic_part_table_recognises_explicit_repair_operations() -> None:
    assert _guess_item_kind("Part", "Carried Out Full Service") == "service"
    assert _guess_item_kind("Part", "Fit Track Rod Ends") == "labour"
    assert _guess_item_kind("Part", "Waste Oil and Filter") == "disposal"
    assert _guess_item_kind("Part", "Oil Filter") == "part"
    assert _guess_item_kind("unknown", "REPLACED FRONT BRAKE DISCS AND PADS") == "labour"
    assert _guess_item_kind("unknown", "LWR door seal") == "part"


def test_subtotal_mismatch_recovers_missing_lines_with_vision(monkeypatch) -> None:
    class SingleLinePage:
        def extract_text(self, layout=False):
            return (
                "ST ALBANS CAR CLINIC\nInvoice INV-1\nInvoice Date: 19/08/2026\n"
                "Subtotal 30.00\nTotal 36.00"
            )

        def extract_tables(self):
            return [
                [
                    ["Description", "Qty", "Unit Price", "Subtotal"],
                    ["Existing part", "1", "10.00", "10.00"],
                ]
            ]

    class FakePDF:
        pages = [SingleLinePage()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class VisionFallback:
        def extract(self, pages, *, role_hint=None):
            return ExtractedInvoice(
                header=InvoiceHeader(
                    invoice_number="INV-1",
                    invoice_date=date(2026, 8, 19),
                    supplier_name="ST ALBANS CAR CLINIC",
                ),
                totals=InvoiceTotals(
                    subtotal_net=Decimal("30.00"), total_gross=Decimal("36.00")
                ),
                line_items=[
                    ExtractedLine(
                        sequence_no=1,
                        raw_description="Existing part",
                        normalised_description="existing part",
                        line_total_net=Decimal("10.00"),
                        source=FieldSource(
                            page_number=1, extraction_method="vision", confidence=0.8
                        ),
                    ),
                    ExtractedLine(
                        sequence_no=2,
                        raw_description="Recovered labour",
                        normalised_description="recovered labour",
                        line_total_net=Decimal("20.00"),
                        source=FieldSource(
                            page_number=1, extraction_method="vision", confidence=0.8
                        ),
                    ),
                ],
                page_numbers=[1],
                extraction_method="vision",
                extraction_confidence=0.8,
            )

    monkeypatch.setattr("app.extraction.invoice_parser.pdfplumber.open", lambda _: FakePDF())
    invoice = InvoiceParser(VisionFallback()).parse_group(Path("unused.pdf"), [_page()])
    assert [line.raw_description for line in invoice.line_items] == [
        "Existing part",
        "Recovered labour",
    ]
    assert invoice.extraction_method == "vision"


def test_unknown_priced_line_triggers_vision_enrichment_even_when_totals_match(
    monkeypatch,
) -> None:
    class UnknownLinePage:
        def extract_text(self, layout=False):
            return (
                "EXL Repairer Service Ltd\nInvoice INV-7\nInvoice Date: 19/08/2026\n"
                "R/OSTROM MIRROR 1.00 76.00 76.00\n"
                "Subtotal 76.00\nVAT 15.20\nTotal 91.20"
            )

        def extract_tables(self):
            return []

    class FakePDF:
        pages = [UnknownLinePage()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class VisionEnrichment:
        def __init__(self) -> None:
            self.calls = 0

        def extract(self, pages, *, role_hint=None):
            self.calls += 1
            return ExtractedInvoice(
                header=InvoiceHeader(
                    invoice_number="INV-7",
                    invoice_date=date(2026, 8, 19),
                    supplier_name="EXL Repairer Service Ltd",
                ),
                totals=InvoiceTotals(
                    subtotal_net=Decimal("76.00"), total_gross=Decimal("91.20")
                ),
                line_items=[
                    ExtractedLine(
                        sequence_no=1,
                        raw_description="R/OSTROM MIRROR",
                        normalised_description="r/ostrom mirror",
                        item_kind="part",
                        part_number="7219-000-813",
                        line_total_net=Decimal("76.00"),
                        source=FieldSource(
                            page_number=1,
                            extraction_method="vision",
                            confidence=0.85,
                        ),
                    )
                ],
                page_numbers=[1],
                extraction_method="vision",
                extraction_confidence=0.85,
            )

    vision = VisionEnrichment()
    monkeypatch.setattr("app.extraction.invoice_parser.pdfplumber.open", lambda _: FakePDF())
    source_page = _page().model_copy(
        update={
            "extraction_method": "ocr",
            "extraction_confidence": 0.86,
            "text": UnknownLinePage().extract_text(),
        }
    )
    invoice = InvoiceParser(vision).parse_group(Path("unused.pdf"), [source_page])

    assert vision.calls == 1
    assert invoice.extraction_method == "vision"
    assert invoice.line_items[0].line_total_net == Decimal("76.00")


def test_format_1_invoice_itemises_parts_specialist_operations_and_two_section_totals() -> None:
    invoice = _client_invoice("DL_Repair_Invoice_format_1.docx")

    header = invoice.header
    assert header.invoice_number == "343653726836/1~3538"
    assert header.claim_reference == "245338996/1"
    assert header.customer_name == "John Doe"
    assert header.registration == "AB12XYZ"

    parts = _of_type(invoice, "parts")
    assert [line.raw_description for line in parts] == [
        "L/R DOOR",
        "L/SILL PANEL COVER",
        "Door Fitting Kit",
        "DOOR FOIL X1",
        "SOUND PAD X1",
        "Door Fitting Kit",
        "Light Moulding Clip",
    ]
    assert [line.part_number for line in parts] == [
        "7700332300",
        "8775132000",
        None,
        None,
        None,
        None,
        None,
    ]
    assert all(line.item_kind == "part" for line in parts)
    # The guide number is stripped from the description, but the printed row
    # survives whole in the provenance the reviewer sees.
    assert "L/R DOOR 1781" in (parts[0].source.raw_text or "")

    sundry = _of_type(invoice, "sundry")
    assert len(sundry) == 1
    assert sundry[0].line_total_net == Decimal("41.85")
    assert sundry[0].quantity is None
    assert sundry[0].item_kind == "fee"

    specialist = _of_type(invoice, "specialist_operation")
    assert len(specialist) == 12
    assert sum(line.line_total_net for line in specialist) == Decimal("136.32")
    assert all(line.item_kind == "fee" for line in specialist)

    assert _section_totals(invoice) == {
        "labour": Decimal("2509.20"),
        "paint_materials": Decimal("1029.57"),
    }

    totals = invoice.totals
    assert totals.parts_net == Decimal("1237.50")
    assert totals.extras_net == Decimal("136.32")
    assert totals.paint_net == Decimal("1029.57")
    assert totals.labour_net == Decimal("2509.20")
    assert totals.vat_amount == Decimal("982.52")
    assert totals.total_gross == Decimal("5895.11")


def test_format_2_request_for_payment_is_four_rolled_up_section_totals() -> None:
    invoice = _client_invoice("DL_Invoice_2_request_for_payment.docx")

    header = invoice.header
    assert header.invoice_number == "22564547648/1~AJ123456"
    assert header.claim_reference == "123456/1"
    assert header.policy_number == "103466899"
    assert header.registration == "A30DRY"
    assert header.vehicle_make == "SKODA"
    assert header.vehicle_model == "KAROQ SE TSI 115]"
    # Captured for display only: "BOY1537" matches no assessment number on the
    # paired report, so it must never be used to pair the two documents.
    assert header.assessment_reference == "BOY1537"

    assert _section_totals(invoice) == {
        "parts": Decimal("448.91"),
        "paint_materials": Decimal("1034.02"),
        "labour": Decimal("2008.00"),
        "extras": Decimal("627.00"),
    }
    assert [line for line in invoice.line_items if not line.is_section_total] == []
    assert invoice.totals.total_gross == Decimal("4941.52")


def test_format_7_validation_note_paragraph_produces_no_line_or_total() -> None:
    invoice = _client_invoice("DL_Repair_Invoice_format_7.docx")

    header = invoice.header
    assert header.claim_reference == "426953180/3"
    assert header.registration == "JK21MNO"
    assert header.vehicle_make is None
    assert header.vehicle_model is None
    assert invoice.totals.parts_net == Decimal("939.00")

    # The embedded prose quotes every total on the invoice; none of it is a row.
    assert not any("validation" in line.raw_description.casefold() for line in invoice.line_items)
    assert not any(
        "verified against" in (line.source.raw_text or "").casefold()
        for line in invoice.line_items
    )
    assert _section_totals(invoice) == {
        "labour": Decimal("1910.00"),
        "paint_materials": Decimal("785.00"),
    }


@pytest.mark.parametrize(
    "filename",
    [
        "DL_Repair_Invoice_format_1.docx",
        "DL_Invoice_2_request_for_payment.docx",
        "DL_Repair_Invoice_format_7.docx",
    ],
)
def test_section_total_rows_are_never_benchmarkable(filename: str) -> None:
    invoice = _client_invoice(filename)
    section_totals = [line for line in invoice.line_items if line.is_section_total]

    assert section_totals
    assert not any(line.benchmarkable for line in section_totals)


def test_printed_subtotal_beats_the_sum_of_the_sections_printed_beside_it() -> None:
    """Item 1: `Grand Total Excl VAT` is the invoice's own answer."""

    invoice = _corpus_invoice("auda-style/Auda7_format_invoice.pdf")

    assert invoice.totals.subtotal_net == Decimal("1423.92")
    assert invoice.totals.vat_amount == Decimal("284.78")
    assert invoice.totals.total_gross == Decimal("1708.70")

    findings = {finding.finding_type: finding for finding in validate_invoice(invoice)}
    assert findings["VAT_MISCALC"].status == "pass"
    assert findings["TOTAL_MISMATCH"].status == "pass"
    # The remaining subtotal finding is the document's own arithmetic, not an
    # invented total: it prints "Total Labour GBP 1488.00" while its grand
    # total (744.00 panel + 143.92 paint/materials + 536.00 parts) counts the
    # panel labour once. What matters here is that 1423.92 is what is checked.
    assert findings["SUBTOTAL_MISMATCH"].found == Decimal("1423.92")


def test_engineer_assessment_pdf_reads_its_printed_grand_total_excl_vat() -> None:
    """Item 1, second corpus proof: 369.80 printed, not 275.60 derived."""

    invoice = _corpus_invoice("engineer-invoice-pairs/CLM-UK-001_Engineer_Assessment.pdf")

    assert invoice.totals.subtotal_net == Decimal("369.80")


def test_printed_zero_total_is_a_value_not_a_missing_field() -> None:
    """Item 3: "Total Additional Costs GBP 0.00" is 0.00, never None."""

    invoice = _corpus_invoice("auda-style/Auda7_format_invoice.pdf")

    assert invoice.totals.extras_net == Decimal("0.00")


def test_percentage_summary_rows_are_never_line_items() -> None:
    """Item 2: a summary row has the same three cells as a sundry row."""

    lines = InvoiceParser()._schedule_text_lines(
        _page().model_copy(
            update={
                "text": (
                    "Parts\n"
                    "VAT   20%   982.52\n"
                    "Overall Discount   10%   50.00\n"
                    "Deductions   0%   0.00\n"
                )
            }
        ),
        1,
    )

    assert lines == []


def test_paint_rows_suppress_the_paint_and_materials_rolled_up_total() -> None:
    """Item 4: paint and paint_materials are one bucket."""

    lines = _schedule_and_section_totals(
        "Paint Work\n"
        "Base Coat   40.00\n"
        "Lacquer   22.00\n"
        "Total Paint & Materials Amount   62.00\n"
    )

    assert [line.line_total_net for line in lines if not line.is_section_total] == [
        Decimal("40.00"),
        Decimal("22.00"),
    ]
    assert [line for line in lines if line.is_section_total] == []


def test_specialist_rows_suppress_an_additional_charges_footer() -> None:
    """Item 4: extras and specialist_operation are one bucket."""

    lines = _schedule_and_section_totals(
        "Specialist Operation\n"
        "Corrosion protection   6.00\n"
        "Car Sanitisation   30.00\n"
        "Additional charges   36.00\n"
    )

    assert [line.line_total_net for line in lines if not line.is_section_total] == [
        Decimal("6.00"),
        Decimal("30.00"),
    ]
    assert [line for line in lines if line.is_section_total] == []


def test_rolled_up_section_totals_do_not_make_a_document_uncertain() -> None:
    """Item 5: a section total is `unknown` by construction, not by failure."""

    invoice = _client_invoice("DL_Repair_Invoice_format_1.docx")
    usable = [
        line
        for line in invoice.line_items
        if line.line_total_net is not None and line.line_total_net > 0
    ]

    assert any(line.is_section_total and line.item_kind == "unknown" for line in usable)
    assert _has_uncertain_lines(usable) is False


def test_vat_registration_cell_is_not_a_vat_total() -> None:
    """Item 6: "VAT Reg No. ...   Labour   266.00" carries the label "VAT"."""

    totals = InvoiceParser()._totals("VAT Reg No. 738 1978 88   Labour   266.00", [_page()])

    assert totals.vat_amount is None
    assert totals.labour_net == Decimal("266.00")


@pytest.mark.parametrize(
    ("filename", "vat_amount"),
    [
        ("DL_Repair_Invoice_format_1.docx", Decimal("982.52")),
        ("DL_Repair_Invoice_format_7.docx", Decimal("747.60")),
    ],
)
def test_spelled_out_vat_label_still_wins(filename: str, vat_amount: Decimal) -> None:
    """Item 6: "An amount equivalent to VAT @20%" states its own rate."""

    assert _client_invoice(filename).totals.vat_amount == vat_amount


def test_column_heading_is_never_read_as_a_vehicle_make() -> None:
    """Item 7: the band is all headings; "and Model" is the one to its right."""

    parser = InvoiceParser()

    assert parser._header("Registration   Make and Model   Chassis Number\n").vehicle_make is None
    assert parser._header("Registration   Make & Model   Chassis Number\n").vehicle_make is None
    assert parser._header("Vehicle Make   SKODA\n").vehicle_make == "SKODA"


def test_unprefixed_rolled_up_totals_are_section_totals_not_unknown_rows() -> None:
    """Item 8: "Parts   448.91" is a section, not a priced row."""

    lines = _schedule_and_section_totals(
        "Parts   448.91\nLabour   2008.00\nPaint & Materials   1034.02\n"
    )

    assert all(line.is_section_total and line.quantity is None for line in lines)
    assert {line.line_item_type: line.line_total_net for line in lines} == {
        "parts": Decimal("448.91"),
        "labour": Decimal("2008.00"),
        "paint_materials": Decimal("1034.02"),
    }


def test_credit_rows_are_dropped_rather_than_signed() -> None:
    """Item 9: the documented limit -- a negative row is not read at all."""

    lines = InvoiceParser()._schedule_text_lines(
        _page().model_copy(
            update={"text": "Extras\nGoodwill credit   -20.00\nGoodwill refund   (20.00)\n"}
        ),
        1,
    )

    assert lines == []


#: What each client invoice actually prints, field by field. `None` means the
#: label is absent from the document -- formats 1 and 7 print no policy number
#: and no vehicle make/model at all, and inventing either is the failure this
#: table exists to catch. Filling those gaps from the matched assessment is a
#: separate step that happens after extraction.
#:
#: Honest label: rows 1, 2 and 7 are REGRESSION COVER, not a reproduction.
#: They pass against the parser as it stood before this table was written, so
#: the reported real-world symptom (blank invoice number, claim and policy in
#: the running app) has a cause that is not present in these replicas and is
#: still unidentified. Rows 3 and 4 are acceptance cases for two pairs that
#: arrived on 16 Sep 2026 and print every pairing key on both documents.
CLIENT_INVOICE_IDENTITY: dict[str, dict[str, str | None]] = {
    "DL_Repair_Invoice_format_1.docx": {
        "invoice_number": "343653726836/1~3538",
        "claim_reference": "245338996/1",
        "policy_number": None,
        "registration": "AB12XYZ",
        "vehicle_make": None,
        "vehicle_model": None,
        "customer_name": "John Doe",
    },
    "DL_Invoice_2_request_for_payment.docx": {
        "invoice_number": "22564547648/1~AJ123456",
        "claim_reference": "123456/1",
        "policy_number": "103466899",
        "registration": "A30DRY",
        "vehicle_make": "SKODA",
        # The stray closing bracket is printed, so it is kept as printed.
        "vehicle_model": "KAROQ SE TSI 115]",
        "customer_name": "John Doe",
    },
    "DL_Invoice_3_request_for_payment.docx": {
        "invoice_number": "132467/1~FT56678",
        "claim_reference": "354647/1",
        "policy_number": "103466899",
        "registration": "AM06TAH",
        "vehicle_make": "SEAT",
        "vehicle_model": "IBIZA",
        "customer_name": "John Doe",
    },
    "DL_Invoice_4_request_for_payment.docx": {
        # The same invoice number invoice 3 prints, against a different claim
        # -- the second duplicate pair in the corpus, after formats 1 and 7.
        # An invoice number is never a pairing key.
        "invoice_number": "132467/1~FT56678",
        "claim_reference": "1111111/1",
        "policy_number": "9865433",
        "registration": "PD73UUF",
        "vehicle_make": "FORD",
        "vehicle_model": "Puma",
        "customer_name": "John Doe",
    },
    "DL_Repair_Invoice_format_7.docx": {
        "invoice_number": "343653726836/1~3538",
        "claim_reference": "426953180/3",
        "policy_number": None,
        "registration": "JK21MNO",
        "vehicle_make": None,
        "vehicle_model": None,
        "customer_name": "Oliver Reed",
    },
}


@pytest.mark.parametrize("filename", sorted(CLIENT_INVOICE_IDENTITY))
def test_client_invoice_identity_is_exactly_what_is_printed(filename: str) -> None:
    """Every printed identity label is read, and nothing absent is invented.

    The DLAS "INVOICE" header and the "Request for Payment" reference grid
    both print a label cell beside a value cell with no colon anywhere, which
    is why these fields came back blank against the client's own documents.
    """

    header = _client_invoice(filename).header
    expected = CLIENT_INVOICE_IDENTITY[filename]

    assert {name: getattr(header, name) for name in expected} == expected


@pytest.mark.parametrize("filename", sorted(CLIENT_INVOICE_IDENTITY))
def test_client_invoice_supplier_is_the_footer_repairer_not_the_issuer(filename: str) -> None:
    """The repairer closes the document; the insurer's invoicing dept opens it.

    Both company blocks print the same St Clare House address, so only their
    position separates them -- taking the first would file every one of these
    invoices against "DL Insurance Limited".
    """

    header = _client_invoice(filename).header

    assert header.supplier_name == "DL Assistance Accident repair Center Ltd"


def test_a_sentence_naming_a_company_is_not_a_company_block() -> None:
    """A payment instruction is prose, not the repairer's printed block.

    Reading it as one filed the invoice against
    "Please make all cheques payable to Bright Panel Repairs Ltd".
    """

    assert (
        _footer_company(
            "Bright Panel Repairs Ltd, 12 High Street, Leeds\n"
            "Total Due 100.00\n"
            "Please make all cheques payable to Bright Panel Repairs Ltd, "
            "quoting the invoice number\n"
        )
        == "Bright Panel Repairs Ltd"
    )


def test_the_insurer_is_never_the_repairer_however_late_it_is_printed() -> None:
    """Repeating the registered-office block per page is standard on invoices.

    With position as the only rule, the repeat files every DLAS invoice
    against the insurer -- the outcome `_footer_company` exists to prevent.
    """

    assert (
        _footer_company(
            "DL Insurance Limited, Central Invoicing Dept, St Clare House, 30-33 Minories\n"
            "INVOICE\n"
            "DL Assistance Accident repair Center Ltd, Registered in England & Wales No 1234\n"
            "Total Due 5895.11\n"
            "DL Insurance Limited, Central Invoicing Dept, St Clare House, 30-33 Minories\n"
        )
        == "DL Assistance Accident repair Center Ltd"
    )


# --------------------------------------------------------------------------
# The EXL summary layout: a grand total labelled "Claim", four section labels
# nothing else prints, and a row printed with no amount.
# --------------------------------------------------------------------------

#: The line above a "Claim   <amount>" row is what decides whether the row is
#: a grand total.  Each case states the printed context and the verdict.
CLAIM_GRAND_TOTAL_CASES: tuple[tuple[str, str, Decimal | None], ...] = (
    # The EXL invoice: the last row of a summary block, under its VAT.
    ("VAT   844.81", "Claim   5068.87", Decimal("5068.87")),
    ("VAT 20%   747.60", "Claim   4485.60", Decimal("4485.60")),
    # The bare "Claim" heading of every DL Auda Summary Information grid
    # carries no amount, so it is not a row this rule can even see.
    ("Summary Information", "Claim", None),
    # The identity label on the same invoice, two tables above the total.
    ("Invoice Date   25/02/2026", "Claim Reference   123456", None),
    ("Invoice Number   ABC1234", "Claim No   123456/1", None),
    # An amount alone is not enough: without the VAT row above it, "Claim"
    # could be any figure a document prints beside the word.
    ("Insured Name   John Smith", "Claim   5068.87", None),
    # The supplier's VAT registration number is not a VAT row.
    ("VAT Registration no. 106 9411 33", "Claim   5068.87", None),
)


@pytest.mark.parametrize(("previous", "line", "expected"), CLAIM_GRAND_TOTAL_CASES)
def test_claim_is_a_grand_total_only_under_a_summary_blocks_vat_row(
    previous: str, line: str, expected: Decimal | None
) -> None:
    """"Claim" is a grand total, an identity label and a heading in this corpus.

    What separates the total from the other two is printed position: a whole
    line of "Claim" and one amount, directly beneath the block's VAT row.
    """

    assert _claim_grand_total(line, previous) == expected


def test_exl_summary_block_is_six_section_totals_and_a_grand_total() -> None:
    """The demo invoice: every printed row read, and none of them billed."""

    invoice = _client_invoice("EXL_demo_invoice.docx")

    assert invoice.totals.total_gross == Decimal("5068.87")
    assert [(line.raw_description, line.line_item_type) for line in invoice.line_items] == [
        ("Labour", "labour"),
        ("Parts", "parts"),
        ("Paint", "paint_materials"),
        ("Additional Extras", "extras"),
        ("Collection & Delivery", "collection_and_delivery"),
        ("Recovery", "recovery"),
    ]
    assert all(line.is_section_total for line in invoice.line_items)
    # The grand total is the invoice's answer, not a thing it billed for.
    assert "Claim" not in {line.raw_description for line in invoice.line_items}


def test_exl_summary_totals_add_up_to_the_printed_claim() -> None:
    """2019.98 + 872.38 + 389.81 + (785.75 + 156.14) = 4224.06, VAT 844.81."""

    totals = _client_invoice("EXL_demo_invoice.docx").totals

    assert totals.labour_net == Decimal("2019.98")
    assert totals.parts_net == Decimal("872.38")
    assert totals.paint_net == Decimal("389.81")
    # Two printed rows, one bucket: "Collection & Delivery" keeps its own
    # section code but its money is extras, which is where the paired report
    # rolls it up.
    assert totals.extras_net == Decimal("941.89")
    assert totals.subtotal_net == Decimal("4224.06")
    assert totals.vat_amount == Decimal("844.81")


def test_a_summary_row_with_no_amount_stays_visible() -> None:
    """"Recovery" is printed with an empty Amount cell.

    Dropping it tells the reviewer the document did not print the row, which
    is false; giving it a zero tells them the document priced it at nothing,
    which is also false. It is kept with no amount at all.
    """

    recovery = next(
        line
        for line in _client_invoice("EXL_demo_invoice.docx").line_items
        if line.raw_description == "Recovery"
    )

    assert recovery.is_section_total is True
    assert recovery.line_total_net is None
    assert recovery.vat_rate is None
    assert recovery.vat_amount is None
    assert recovery.gross_amount is None
    assert recovery.vat_applicable is False


def test_a_bare_section_label_between_schedule_rows_is_still_a_heading() -> None:
    """The guard on `_blank_summary_row`: "Parts" heads a grid, it is not a row.

    Both neighbours have to be priced summary rows. On the DLAS invoices a
    bare section label is followed by its own column header, so none of them
    can be mistaken for an amount-less summary row.
    """

    lines = _schedule_and_section_totals(
        "Total Parts   1237.50\n"
        "Specialist Operation\n"
        "Specialist Operation Cost (£)\n"
        "Corrosion protection   6.00\n"
    )

    assert "Specialist Operation" not in {line.raw_description for line in lines}


# --------------------------------------------------------------------------
# Provenance: what a totals figure's "show evidence" points at.
# --------------------------------------------------------------------------

#: Invoices 5, 6 and 7 embed a "Validation note" paragraph reciting every
#: figure on the document, printed *below* the totals it recites. Each row is
#: the text that must be offered as evidence for that field.
VALIDATION_NOTE_PROVENANCE: tuple[tuple[str, str, str], ...] = (
    ("DL_Repair_Invoice_format_5.docx", "labour_net", "Total Labour: 2653.01"),
    ("DL_Repair_Invoice_format_5.docx", "parts_net", "Total Parts 1237.50"),
    ("DL_Repair_Invoice_format_5.docx", "paint_net", "Total Paint & materials: 1088.59"),
    (
        "DL_Repair_Invoice_format_5.docx",
        "vat_amount",
        "An amount equivalent to VAT @20%: 1038.84",
    ),
    ("DL_Repair_Invoice_format_6.docx", "labour_net", "Total Labour: 2611.41"),
    ("DL_Repair_Invoice_format_6.docx", "parts_net", "Total Parts 1287.94"),
    (
        "DL_Repair_Invoice_format_6.docx",
        "vat_amount",
        "An amount equivalent to VAT @20%: 1022.55",
    ),
    ("DL_Repair_Invoice_format_7.docx", "labour_net", "Total Labour: 1910.00"),
    ("DL_Repair_Invoice_format_7.docx", "parts_net", "Total Parts 939.00"),
    (
        "DL_Repair_Invoice_format_7.docx",
        "vat_amount",
        "An amount equivalent to VAT @20%: 747.60",
    ),
)


@pytest.mark.parametrize(("filename", "field", "printed"), VALIDATION_NOTE_PROVENANCE)
def test_a_total_points_at_the_row_that_states_it_not_at_prose_about_it(
    filename: str, field: str, printed: str
) -> None:
    """Evidence that points at the wrong thing is worse than no evidence.

    Invoice 5's note asserts a reconciliation that is false by £78.77, and a
    reviewer clicking "show evidence" on its labour total used to land on
    that sentence rather than on the row the figure is printed in.
    """

    source = _client_invoice(filename, with_words=True).totals.sources[field]

    assert source.raw_text == printed
    assert "Validation note" not in (source.raw_text or "")
    assert "aligned to report" not in (source.raw_text or "")
