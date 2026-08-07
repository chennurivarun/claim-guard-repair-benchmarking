from decimal import Decimal

from app.extraction.invoice_parser import InvoiceParser, _guess_item_kind
from app.extraction.schemas import PageAnalysis, PageType


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


def test_native_parser_reads_generic_description_quantity_unit_subtotal_table() -> None:
    lines = InvoiceParser()._native_table_lines(_TablePage(), _page(), 1)

    assert [line.raw_description for line in lines] == ["Oil Filter", "Spark Plugs"]
    assert [line.quantity for line in lines] == [Decimal("1"), Decimal("4")]
    assert [line.unit_price_net for line in lines] == [Decimal("8.95"), Decimal("9.81")]
    assert [line.line_total_net for line in lines] == [Decimal("8.95"), Decimal("39.24")]


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
