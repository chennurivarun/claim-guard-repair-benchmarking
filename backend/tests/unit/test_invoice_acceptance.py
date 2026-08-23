from decimal import Decimal
from pathlib import Path

import fitz

from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.extraction.schemas import (
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
)


def _vat_only_fragment() -> ExtractedInvoice:
    return ExtractedInvoice(
        header=InvoiceHeader(invoice_number="Claim"),
        totals=InvoiceTotals(vat_amount=Decimal("1423.92")),
        line_items=[],
        page_numbers=[1],
        extraction_method="native_pdf",
        extraction_confidence=0.78,
    )


def test_generic_claim_label_is_not_accepted_as_an_invoice_number() -> None:
    assert _vat_only_fragment().header.invoice_number is None


def test_only_priced_parts_are_eligible_for_automatic_benchmarking() -> None:
    source = FieldSource(
        page_number=1,
        extraction_method="native",
        confidence=0.98,
    )
    labour_only = _vat_only_fragment().model_copy(
        update={
            "line_items": [
                ExtractedLine(
                    sequence_no=1,
                    raw_description="Renew mirror",
                    normalised_description="renew mirror",
                    item_kind="labour",
                    line_total_net=Decimal("80.00"),
                    source=source,
                )
            ]
        }
    )
    part_invoice = labour_only.model_copy(
        update={
            "line_items": [
                ExtractedLine(
                    sequence_no=1,
                    raw_description="Right door mirror",
                    normalised_description="right door mirror",
                    item_kind="part",
                    part_number="A-001",
                    line_total_net=Decimal("76.00"),
                    source=source,
                )
            ]
        }
    )

    assert labour_only.has_benchmarkable_part_lines() is False
    assert part_invoice.has_benchmarkable_part_lines() is True


def test_vat_only_fragment_is_routed_to_manual_review(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "vat-only.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Invoice Number: 123\nInvoice total VAT Claim")
    document.save(source)
    document.close()

    pipeline = PDFPipeline(
        PipelineConfig(native_min_characters=1, native_min_words=1, ocr_enabled=False)
    )
    monkeypatch.setattr(pipeline.parser, "parse_group", lambda *args, **kwargs: _vat_only_fragment())

    analysis = pipeline.analyse(source, tmp_path / "pages")

    # The invoice is retained (nothing is discarded) but still routed to manual
    # review because it carries no benchmarkable line evidence.
    assert len(analysis.invoices) == 1
    assert analysis.invoices[0].line_items == []
    assert analysis.manual_review_reason == (
        "Line-item information is not available. The invoice appears to be "
        "rolled up and cannot be benchmarked automatically."
    )
