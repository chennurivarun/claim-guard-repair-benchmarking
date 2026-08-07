from decimal import Decimal
from pathlib import Path

import pytest

from app.extraction.calculation_validator import validate_invoice
from app.extraction.pdf_pipeline import PDFPipeline
from app.extraction.schemas import (
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
)


@pytest.mark.parametrize(
    (
        "filename",
        "invoice_number",
        "registration",
        "mileage",
        "line_count",
        "subtotal",
        "vat",
        "non_vat",
        "gross",
    ),
    [
        (
            "1597491_doc_15974912.pdf",
            "90538",
            "KU65 EOK",
            100340,
            16,
            "486.03",
            "97.21",
            "54.85",
            "638.09",
        ),
        (
            "1643919_doc_16439191.pdf.pdf",
            "91283",
            "PX64 XCU",
            56914,
            18,
            "588.41",
            "117.68",
            "54.85",
            "760.94",
        ),
    ],
)
def test_native_invoice_totals(
    tmp_path: Path,
    filename: str,
    invoice_number: str,
    registration: str,
    mileage: int,
    line_count: int,
    subtotal: str,
    vat: str,
    non_vat: str,
    gross: str,
) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data" / filename
    if not source.exists():
        pytest.skip("Supplied corpus is not available")
    analysis = PDFPipeline().analyse(source, tmp_path / filename)
    invoice = next(
        unit for unit in analysis.invoices if unit.header.invoice_number == invoice_number
    )
    assert invoice.header.registration == registration
    assert invoice.header.mileage == mileage
    assert invoice.totals.subtotal_net == Decimal(subtotal)
    assert invoice.totals.vat_amount == Decimal(vat)
    assert invoice.totals.non_vatable == Decimal(non_vat)
    assert invoice.totals.total_gross == Decimal(gross)
    assert len(invoice.line_items) == line_count
    assert all(
        line.vat_amount is not None and line.gross_amount is not None for line in invoice.line_items
    )
    located_lines = [line for line in invoice.line_items if line.source.regions]
    assert located_lines
    assert all("row" in line.source.regions for line in located_lines)
    assert any("line_total" in line.source.regions for line in located_lines)
    assert "subtotal_net" in invoice.totals.sources
    assert "value" in invoice.totals.sources["subtotal_net"].regions
    failures = [item for item in validate_invoice(invoice) if item.status == "fail"]
    assert failures == []


def test_summary_only_labour_is_not_reported_as_missing_line_math() -> None:
    source = FieldSource(
        page_number=1,
        raw_text="Parts £235.47 Labour £350.00 Subtotal £585.47",
        extraction_method="native_pdf",
        confidence=0.98,
    )
    invoice = ExtractedInvoice(
        header=InvoiceHeader(invoice_number="9407"),
        totals=InvoiceTotals(
            labour_net=Decimal("350.00"),
            parts_net=Decimal("235.47"),
            subtotal_net=Decimal("585.47"),
            vat_rate=Decimal("20"),
            vat_amount=Decimal("117.09"),
            non_vatable=Decimal("54.85"),
            total_gross=Decimal("757.41"),
        ),
        line_items=[
            ExtractedLine(
                sequence_no=1,
                raw_description="Oil filter",
                normalised_description="oil filter",
                item_kind="part",
                quantity=Decimal("1"),
                unit_price_net=Decimal("100.00"),
                line_total_net=Decimal("100.00"),
                source=source,
            ),
            ExtractedLine(
                sequence_no=2,
                raw_description="Engine oil",
                normalised_description="engine oil",
                item_kind="part",
                quantity=Decimal("1"),
                unit_price_net=Decimal("135.47"),
                line_total_net=Decimal("135.47"),
                source=source,
            ),
        ],
        page_numbers=[1],
        extraction_method="native_pdf",
        extraction_confidence=0.98,
    )

    findings = {item.finding_type: item for item in validate_invoice(invoice)}

    assert findings["LABOUR_TOTAL_MISMATCH"].status == "not_applicable"
    assert "summary" in findings["LABOUR_TOTAL_MISMATCH"].explanation.lower()
    assert findings["PARTS_TOTAL_MISMATCH"].status == "pass"
    assert findings["SUBTOTAL_MISMATCH"].status == "pass"
