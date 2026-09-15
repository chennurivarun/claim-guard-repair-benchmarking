from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path

import fitz
import pytest

import app.services.document_processing as document_processing
from app.extraction.engineer_assessment_parser import parse_engineer_assessment
from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.extraction.schemas import PageAnalysis, PageType

REPO_ROOT = Path(__file__).resolve().parents[3]
PAIR_DIR = REPO_ROOT / "sample-data" / "engineer-invoice-pairs"
FIXTURES_DIR = REPO_ROOT / "sample-data" / "client-formats"


def _page(text: str, page_number: int = 1) -> PageAnalysis:
    return PageAnalysis(
        page_number=page_number,
        width=595.0,
        height=842.0,
        rotation=0,
        native_character_count=len(text),
        positioned_word_count=len(text.split()),
        image_count=0,
        extraction_method="native",
        extraction_confidence=0.95,
        text=text,
        page_type=PageType.ENGINEER_ASSESSMENT,
        classification_confidence=0.95,
    )


def _fixture_pages(monkeypatch: pytest.MonkeyPatch, filename: str) -> list[PageAnalysis]:
    """Convert a client `.docx` through the real upload-normalisation path.

    This is the same `normalise_document_upload` the API runs for every DOCX
    upload; LibreOffice is forced off so the deterministic reportlab path (and
    therefore `docx_ingest`'s 2+-space column join) is what the parser sees.
    """

    monkeypatch.setattr(document_processing.shutil, "which", lambda _: None)
    normalised = document_processing.normalise_document_upload(
        filename, (FIXTURES_DIR / filename).read_bytes()
    )
    document = fitz.open(stream=normalised.content, filetype="pdf")
    try:
        return [_page(page.get_text(), index + 1) for index, page in enumerate(document)]
    finally:
        document.close()


def test_engineer_report_is_classified_and_parsed_as_non_invoice(tmp_path: Path) -> None:
    path = PAIR_DIR / "CLM-UK-001_Engineer_Assessment.pdf"
    if not path.is_file():
        pytest.skip("Engineer Assessment acceptance fixture is not available")
    analysis = PDFPipeline(PipelineConfig(ocr_enabled=False)).analyse(path, tmp_path)
    engineer_pages = [
        page for page in analysis.pages if page.page_type == PageType.ENGINEER_ASSESSMENT
    ]
    parsed = parse_engineer_assessment(engineer_pages)

    assert analysis.invoices == []
    assert parsed.fields["assessment_number"] == "EA-0001"
    assert parsed.fields["claim_reference"] == "CLM-UK-001"
    assert parsed.fields["registration"] == "CG01 UKX"
    assert str(parsed.fields["gross_total"]) == "443.76"
    assert len(parsed.operations) == 5
    assert parsed.confidence == pytest.approx(0.99)


def test_format_1_identity_totals_and_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = parse_engineer_assessment(
        _fixture_pages(monkeypatch, "DL_Auda_format_1_assessment.docx")
    )

    # The Summary Information grid wins over the page-1 running header, which
    # prints L0987892222, and over the later band, which prints D38892222.
    assert parsed.fields["assessment_number"] == "D7576879"
    assert parsed.fields["claim_reference"] == "245338996/1"
    assert parsed.fields["policy_number"] == "PH"
    assert parsed.fields["registration"] == "AB12XYZ"
    assert parsed.fields["vehicle_make"] == "HYUNDAI"
    assert parsed.fields["vehicle_model"] == "140 SE Nav"
    assert parsed.fields["labour_rate"] == Decimal("38.00")
    assert parsed.fields["paint_rate"] == Decimal("68.00")
    assert parsed.fields["gross_total"] == Decimal("5895.11")
    # "Total Labour" covers panel (1482.40) and paintwork (1026.80) together.
    assert parsed.fields["labour_net"] == Decimal("2509.20")
    assert parsed.fields["paint_net"] == Decimal("1029.57")
    assert parsed.fields["parts_net"] == Decimal("1237.50")
    assert parsed.fields["extras_net"] == Decimal("136.32")

    counts = Counter(operation.line_item_type for operation in parsed.operations)
    assert counts == {"labour": 25, "paint": 16, "extras": 12, "parts": 7}

    by_type: dict[str, list] = {}
    for operation in parsed.operations:
        by_type.setdefault(operation.line_item_type, []).append(operation)

    assert {operation.raw_category for operation in by_type["labour"]} == {"LABOUR"}
    assert {operation.raw_category for operation in by_type["paint"]} == {"PAINT WORK"}
    assert {operation.unit_price for operation in by_type["labour"]} == {Decimal("38.00")}
    assert {operation.unit_price for operation in by_type["paint"]} == {Decimal("68.00")}
    assert all(operation.price_derived for operation in by_type["labour"])

    first_labour = by_type["labour"][0]
    assert first_labour.work_units == Decimal("10")
    assert first_labour.hours == Decimal("1.00")
    assert first_labour.total == Decimal("38.00")

    # Blank code, "NO NUMBER", bare "1000" and a code suffix all survive.
    assert by_type["labour"][7].code is None
    assert by_type["labour"][8].code is None
    assert by_type["labour"][8].description == "BODY WORK FOR LEFT FRONT DOOR"
    assert by_type["labour"][18].code == "1000"


def test_format_1_parts_and_extras_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = parse_engineer_assessment(
        _fixture_pages(monkeypatch, "DL_Auda_format_1_assessment.docx")
    )
    parts = [op for op in parsed.operations if op.line_item_type == "parts"]
    extras = [op for op in parsed.operations if op.line_item_type == "extras"]

    assert [op.part_number for op in parts] == [
        "7700332300",
        "8775132000",
        None,
        None,
        None,
        None,
        None,
    ]
    # "Renew" is a placeholder, not a part number -- but it is kept in the payload.
    assert [op.part_number_raw for op in parts[2:]] == ["Renew"] * 5
    assert parts[0].description == "L/R DOOR"
    assert parts[0].total == Decimal("847.73")
    assert {op.raw_category for op in parts} == {"PARTS"}

    assert extras[0].description == "Corrosion protection"
    assert extras[0].total == Decimal("6.00")
    # A zero-priced extra ("C/Car Class A") is still recorded.
    assert extras[2].description == "C/Car Class A"
    assert extras[2].total == Decimal("0.00")
    assert parsed.printed_totals["sub_total"] == Decimal("1195.65")
    assert parsed.printed_totals["sundry"] == Decimal("41.85")


def test_format_2_inline_rate_prices_seventeen_labour_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parse_engineer_assessment(
        _fixture_pages(monkeypatch, "DL_Auda_format_2_assessment.docx")
    )

    assert parsed.fields["registration"] == "A30DRY"
    assert parsed.fields["claim_reference"] == "123456/1"
    assert parsed.fields["policy_number"] == "103466899"

    labour = [op for op in parsed.operations if op.line_item_type == "labour"]
    assert len(labour) == 17
    # Inline "Time Basis 10 WU=1HR.Price £80.00/HR" beats the Calculation block,
    # which this report does not print at all.
    assert {op.unit_price for op in labour} == {Decimal("80.00")}
    assert labour[0].work_units == Decimal("40.0")
    assert labour[0].hours == Decimal("4.00")
    assert sum(op.total for op in labour) == Decimal("1112.00")
    # "NO MUMBER" and the "ZAX" code suffix both parse.
    assert labour[2].code == "865246R77 ZAX"
    assert labour[3].code is None
    # A 0.0 WU row is stored, priced at zero, and carries no benchmarkable work.
    assert labour[5].work_units == Decimal("0.0")
    assert labour[5].total == Decimal("0.00")
    # Only the labour pages were captured; nothing downstream may be invented.
    assert parsed.fields.get("gross_total") is None
    assert parsed.printed_work_units == {"labour": Decimal("139.0")}


def test_format_7_printed_totals_are_never_reconciled_against_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = parse_engineer_assessment(
        _fixture_pages(monkeypatch, "DL_Auda_format_7_assessment.docx")
    )

    assert parsed.fields["assessment_number"] == "T4592861"

    # The document prints 300 and 113.2 work units against rows summing to 101
    # and 151. Both figures are persisted; the gap is a finding, not a fix.
    assert parsed.printed_work_units == {"labour": Decimal("300"), "paint": Decimal("113.2")}
    assert parsed.row_work_units == {"labour": Decimal("101"), "paint": Decimal("151")}

    parts = [op for op in parsed.operations if op.line_item_type == "parts"]
    assert len(parts) == 7
    assert parsed.printed_totals["sub_total"] == Decimal("907.70")
    assert parsed.row_totals["parts"] == Decimal("908.30")
    assert parsed.fields["parts_net"] == Decimal("939.00")


HEADER_ONLY = """Assessment report
Summary Information
Assessment Number   D7576879   Reference Name   John Doe
Claim Reference   245338996/1   Able to authorize repairs   Yes
Registration Number   AB12XYZ   VIN Number   ABCD1234567
"""

WRAPPED_DESCRIPTION = (
    HEADER_ONLY
    + """Repair Information
LABOUR
Number   Description   WU
82650R00   R + R LEFT FRONT OUTER DOOR   2
HANDLE
   Total Work Units   2
"""
)


def test_identity_without_operations_still_parses() -> None:
    parsed = parse_engineer_assessment([_page(HEADER_ONLY)])

    assert parsed.operations == []
    assert parsed.fields["assessment_number"] == "D7576879"
    assert parsed.fields["registration"] == "AB12XYZ"


def test_assessment_without_any_identifier_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_engineer_assessment([_page("Assessment report\nRepair Information\nLABOUR\n")])


def test_wrapped_description_joins_and_an_unrated_row_keeps_no_price() -> None:
    parsed = parse_engineer_assessment([_page(WRAPPED_DESCRIPTION)])

    assert len(parsed.operations) == 1
    operation = parsed.operations[0]
    assert operation.description == "R + R LEFT FRONT OUTER DOOR HANDLE"
    assert operation.work_units == Decimal("2")
    # No rate is printed anywhere, so no price is guessed.
    assert operation.unit_price is None
    assert operation.total is None
    assert operation.price_derived is False
