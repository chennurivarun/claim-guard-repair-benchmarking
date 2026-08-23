"""Tests for the A1-A3 universal extraction ladder.

Covers: the LLM text-extraction tier (the "universal reader"), retaining every
parsed invoice instead of discarding non-benchmarkable ones, and routing
unparseable engineer assessments to manual review instead of failing the
document.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import fitz
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.enums import DocumentRole, UploadStatus
from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.extraction.schemas import (
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
    PageAnalysis,
    PageType,
)
from app.init_db import initialize_database
from app.llm.base import LLMProviderError
from app.llm.invoice_extraction import MultimodalInvoiceExtractor
from app.models import Case
from app.services import document_processing


class _StubClient:
    """Fake StructuredLLMClient; records every payload it is sent, no network."""

    provider = "stub"
    model_id = "stub-model"

    def __init__(self, *, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def _native_pdf(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def _line(
    description: str,
    *,
    item_kind: str,
    part_number: str | None = None,
    net: str = "80.00",
    sequence_no: int = 1,
) -> ExtractedLine:
    return ExtractedLine(
        sequence_no=sequence_no,
        raw_description=description,
        normalised_description=description.lower(),
        item_kind=item_kind,
        part_number=part_number,
        line_total_net=Decimal(net),
        source=FieldSource(page_number=1, extraction_method="native", confidence=0.95),
    )


def _fragment(*lines: ExtractedLine, invoice_number: str = "INV-1") -> ExtractedInvoice:
    return ExtractedInvoice(
        header=InvoiceHeader(invoice_number=invoice_number, supplier_name="Acme Repairs"),
        totals=InvoiceTotals(subtotal_net=Decimal("80.00")),
        line_items=list(lines),
        page_numbers=[1],
        extraction_method="native_table",
        extraction_confidence=0.9,
    )


# --- (a) labour-only invoices survive the pipeline -------------------------


def test_labour_only_invoice_is_retained_and_flagged_for_review(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = _native_pdf(
        tmp_path,
        "labour-only.pdf",
        "Invoice Number: INV-LABOUR\nRenew wing mirror labour only, no parts supplied.",
    )
    pipeline = PDFPipeline(
        PipelineConfig(native_min_characters=1, native_min_words=1, ocr_enabled=False)
    )
    labour_only = _fragment(_line("Renew mirror", item_kind="labour"))
    monkeypatch.setattr(pipeline.parser, "parse_group", lambda *a, **k: labour_only)

    analysis = pipeline.analyse(pdf_path, tmp_path / "pages")

    assert len(analysis.invoices) == 1
    assert [line.item_kind for line in analysis.invoices[0].line_items] == ["labour"]
    assert analysis.manual_review_reason is not None


def test_partially_benchmarkable_invoice_is_retained_without_review_flag(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = _native_pdf(
        tmp_path,
        "mixed.pdf",
        "Invoice Number: INV-MIXED\nDoor mirror part plus fitting labour on the same job.",
    )
    pipeline = PDFPipeline(
        PipelineConfig(native_min_characters=1, native_min_words=1, ocr_enabled=False)
    )
    mixed = _fragment(
        _line("Renew mirror", item_kind="labour", net="80.00", sequence_no=1),
        _line(
            "Right door mirror", item_kind="part", part_number="A-001", net="76.00", sequence_no=2
        ),
    )
    monkeypatch.setattr(pipeline.parser, "parse_group", lambda *a, **k: mixed)

    analysis = pipeline.analyse(pdf_path, tmp_path / "pages")

    assert len(analysis.invoices) == 1
    assert len(analysis.invoices[0].line_items) == 2
    assert analysis.manual_review_reason is None


# --- (b) text tier merges recovered lines -----------------------------------


def test_text_tier_recovers_lines_with_capped_confidence(tmp_path: Path) -> None:
    pdf_path = _native_pdf(
        tmp_path,
        "narrative.pdf",
        "Invoice Number: INV-200\nThis narrative invoice has no priced table rows, only "
        "prose describing the repair carried out on site for the customer vehicle today.",
    )
    client = _StubClient(
        response={
            "document_role": "invoice",
            "confidence": 0.99,
            "header": {"invoice_number": "INV-200", "supplier_name": "Acme Repairs"},
            "totals": {"subtotal_net": "76.00"},
            "line_items": [
                {
                    "page_number": 1,
                    "description": "Right door mirror",
                    "item_kind": "part",
                    "part_number": "A-001",
                    "line_total_net": "76.00",
                }
            ],
        }
    )
    pipeline = PDFPipeline(
        PipelineConfig(native_min_characters=1, native_min_words=1, ocr_enabled=False),
        text_extractor=MultimodalInvoiceExtractor(client),
    )

    analysis = pipeline.analyse(pdf_path, tmp_path / "pages")

    assert len(analysis.invoices) == 1
    invoice = analysis.invoices[0]
    assert invoice.extraction_method == "llm_text"
    assert invoice.extraction_confidence <= 0.89
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].line_total_net == Decimal("76.00")
    assert invoice.line_items[0].source.extraction_method == "llm_text"
    assert invoice.line_items[0].source.precision == "approximate"
    assert len(client.calls) == 1
    assert client.calls[0]["image_data_urls"] is None


def test_text_tier_recovers_parts_when_deterministic_parse_only_found_summary_rows(
    tmp_path: Path, monkeypatch
) -> None:
    pdf_path = _native_pdf(
        tmp_path,
        "type-7-summary.pdf",
        "Invoice Number: TYPE-7\nAudatex repair invoice\nRear bumper repaired\n"
        "Rear left wing renewed\nParts schedule DGHJ797 193.00\n"
        "Subtotal 193.00 VAT 38.60 Total 231.60",
    )
    client = _StubClient(
        response={
            "document_role": "invoice",
            "confidence": 0.92,
            "header": {"invoice_number": "TYPE-7", "supplier_name": "Acme Repairs"},
            "totals": {"subtotal_net": "193.00"},
            "line_items": [
                {
                    "page_number": 1,
                    "description": "Rear left wing",
                    "item_kind": "part",
                    "part_number": "DGHJ797",
                    "line_total_net": "193.00",
                }
            ],
        }
    )
    pipeline = PDFPipeline(
        PipelineConfig(native_min_characters=1, native_min_words=1, ocr_enabled=False),
        text_extractor=MultimodalInvoiceExtractor(client),
    )
    summary_only = _fragment(_line("Rear bumper repair labour", item_kind="labour", net="193.00"))
    monkeypatch.setattr(pipeline.parser, "parse_group", lambda *a, **k: summary_only)

    analysis = pipeline.analyse(pdf_path, tmp_path / "pages")

    recovered_parts = [
        line
        for invoice in analysis.invoices
        for line in invoice.line_items
        if line.item_kind == "part"
    ]
    assert len(client.calls) == 1
    assert recovered_parts
    assert recovered_parts[0].part_number == "DGHJ797"
    assert recovered_parts[0].source.extraction_method == "llm_text"


# --- (c) text tier failures never fail the document -------------------------


def test_text_tier_failure_is_recorded_and_document_still_completes(tmp_path: Path) -> None:
    pdf_path = _native_pdf(
        tmp_path,
        "narrative-fail.pdf",
        "Invoice Number: INV-201\nAnother narrative invoice with no priced table rows, "
        "describing repair work performed for the customer without any figures at all.",
    )
    client = _StubClient(error=LLMProviderError("LLM_RATE_LIMITED", "Provider rate limited"))
    pipeline = PDFPipeline(
        PipelineConfig(native_min_characters=1, native_min_words=1, ocr_enabled=False),
        text_extractor=MultimodalInvoiceExtractor(client),
    )

    analysis = pipeline.analyse(pdf_path, tmp_path / "pages")

    assert analysis.llm_failures == ["LLM_RATE_LIMITED"]
    assert len(analysis.invoices) == 1
    assert analysis.invoices[0].line_items == []
    assert analysis.manual_review_reason is not None


# --- (d) redaction closes the gap on both the vision and text paths --------


def test_untrusted_page_text_is_redacted_before_reaching_the_model(tmp_path: Path) -> None:
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (10, 10), "white").save(image_path)
    page = PageAnalysis(
        page_number=1,
        width=100,
        height=100,
        rotation=0,
        native_character_count=0,
        positioned_word_count=0,
        image_count=1,
        extraction_method="native",
        extraction_confidence=0.9,
        text="Contact the customer at driver.name@example.co.uk about the claim.",
        page_type=PageType.OTHER,
        classification_confidence=0.5,
        rendered_image_path=image_path,
    )
    response = {
        "document_role": "other",
        "confidence": 0.5,
        "header": {},
        "totals": {},
        "line_items": [],
    }

    vision_client = _StubClient(response=response)
    MultimodalInvoiceExtractor(vision_client).extract([page])
    vision_payload = str(vision_client.calls[0]["payload"])
    assert "driver.name@example.co.uk" not in vision_payload
    assert "REDACTED_EMAIL" in vision_payload

    text_client = _StubClient(response=response)
    MultimodalInvoiceExtractor(text_client).extract_from_text([page])
    text_payload = str(text_client.calls[0]["payload"])
    assert "driver.name@example.co.uk" not in text_payload
    assert "REDACTED_EMAIL" in text_payload
    assert text_client.calls[0]["image_data_urls"] is None


# --- (e) unparseable engineer assessments become reviewable, not FAILED ----


def test_unparseable_engineer_assessment_is_reviewable_not_failed(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'engineer-review.db'}")
    initialize_database(engine, seed_defaults=True)
    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")

    pdf_path = tmp_path / "assessment.pdf"
    document = fitz.open()
    document.new_page().insert_text(
        (72, 72),
        "Engineer Assessment Report\nThis narrative section describes the vehicle "
        "inspection findings without providing a structured identifier or itemised "
        "repair operations that automated parsing tools could recognise for "
        "benchmarking purposes.",
    )
    document.save(pdf_path)
    document.close()

    try:
        with Session(engine, expire_on_commit=False) as session:
            case = Case(case_reference="CLM-UNPARSEABLE-001", created_by="pytest.handler")
            session.add(case)
            session.flush()
            doc = document_processing.store_pdf(
                session,
                case=case,
                filename="assessment.pdf",
                content=pdf_path.read_bytes(),
                role=DocumentRole.CURRENT,
            )
            run = document_processing.process_document(session, doc)
            session.commit()

            assert run.status.value == "succeeded"
            assert doc.upload_status == UploadStatus.READY
            serialised = document_processing.serialise_document(doc)
            assert serialised["manual_review"] is True
            assert serialised["manual_review_reason"] == (
                "Engineer assessment could not be parsed automatically; manual review required."
            )
    finally:
        engine.dispose()
