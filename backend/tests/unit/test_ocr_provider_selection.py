from datetime import date
from decimal import Decimal
from pathlib import Path

import fitz
import pytest

import app.extraction.pdf_pipeline as pdf_pipeline_module
from app.config import Settings
from app.extraction.pdf_pipeline import OCRUnavailableError, PDFPipeline, PipelineConfig
from app.extraction.schemas import (
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
)
from app.services.document_processing import _build_cloud_ocr


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_partial_azure_configuration_is_rejected_before_tesseract() -> None:
    config = _settings(
        document_ocr_provider="auto",
        azure_document_endpoint="https://loss-run.cognitiveservices.azure.com",
        azure_document_api_key=None,
    )

    with pytest.raises(ValueError, match="Set both"):
        _build_cloud_ocr(config)


def test_complete_azure_configuration_builds_cloud_provider() -> None:
    config = _settings(
        document_ocr_provider="azure",
        azure_document_endpoint="https://loss-run.cognitiveservices.azure.com/",
        azure_document_api_key="company-key",
        azure_document_model="prebuilt-layout",
    )

    provider = _build_cloud_ocr(config)

    assert provider is not None
    assert provider.endpoint == "https://loss-run.cognitiveservices.azure.com"
    assert provider.model == "prebuilt-layout"


def test_azure_failure_is_not_hidden_by_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()

    class FailingAzure:
        def analyse(self, source, page_dimensions):
            raise RuntimeError("Azure rejected the endpoint, key, or model")

    def unexpected_tesseract(*args, **kwargs):
        raise AssertionError("Tesseract must not run after Azure is configured")

    monkeypatch.setattr(pdf_pipeline_module, "_ocr_image", unexpected_tesseract)

    with pytest.raises(
        OCRUnavailableError,
        match="Azure Document Intelligence OCR failed: Azure rejected",
    ):
        PDFPipeline(
            PipelineConfig(ocr_enabled=True),
            cloud_ocr=FailingAzure(),
        ).analyse(pdf_path, tmp_path / "pages")


def test_configured_vision_can_recover_when_azure_ocr_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()

    class FailingAzure:
        def analyse(self, source, page_dimensions):
            raise RuntimeError("Azure OCR unavailable")

    class VisionFallback:
        max_pages = 8

        def extract(self, pages, *, role_hint=None):
            return ExtractedInvoice(
                header=InvoiceHeader(
                    invoice_number="INV-1",
                    invoice_date=date(2026, 8, 19),
                    supplier_name="Example Repairer",
                ),
                totals=InvoiceTotals(subtotal_net=Decimal("10.00")),
                line_items=[
                    ExtractedLine(
                        sequence_no=1,
                        raw_description="Visible part",
                        normalised_description="visible part",
                        line_total_net=Decimal("10.00"),
                        source=FieldSource(
                            page_number=pages[0].page_number,
                            extraction_method="vision",
                            confidence=0.8,
                            precision="approximate",
                        ),
                    )
                ],
                page_numbers=[pages[0].page_number],
                extraction_method="vision",
                extraction_confidence=0.8,
            )

    def unexpected_tesseract(*args, **kwargs):
        raise AssertionError("Tesseract must not run after configured Azure fails")

    monkeypatch.setattr(pdf_pipeline_module, "_ocr_image", unexpected_tesseract)
    analysis = PDFPipeline(
        PipelineConfig(ocr_enabled=True),
        cloud_ocr=FailingAzure(),
        vision_extractor=VisionFallback(),
    ).analyse(pdf_path, tmp_path / "pages")

    assert len(analysis.invoices) == 1
    assert analysis.invoices[0].extraction_method == "vision"


def test_ungrouped_pages_are_sent_to_vision_separately(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two-scans.pdf"
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(pdf_path)
    document.close()

    class FailingAzure:
        def analyse(self, source, page_dimensions):
            raise RuntimeError("Azure OCR unavailable")

    class VisionFallback:
        max_pages = 8

        def __init__(self):
            self.calls = []

        def extract(self, pages, *, role_hint=None):
            self.calls.append([page.page_number for page in pages])
            page_number = pages[0].page_number
            return ExtractedInvoice(
                header=InvoiceHeader(invoice_number=f"INV-{page_number}"),
                totals=InvoiceTotals(subtotal_net=Decimal("10.00")),
                line_items=[
                    ExtractedLine(
                        sequence_no=1,
                        raw_description=f"Part {page_number}",
                        normalised_description=f"part {page_number}",
                        line_total_net=Decimal("10.00"),
                        source=FieldSource(
                            page_number=page_number,
                            extraction_method="vision",
                            confidence=0.8,
                        ),
                    )
                ],
                page_numbers=[page_number],
                extraction_method="vision",
                extraction_confidence=0.8,
            )

    vision = VisionFallback()
    analysis = PDFPipeline(
        PipelineConfig(ocr_enabled=True, vision_max_batches=3),
        cloud_ocr=FailingAzure(),
        vision_extractor=vision,
    ).analyse(pdf_path, tmp_path / "pages")
    assert vision.calls == [[1], [2]]
    assert [invoice.header.invoice_number for invoice in analysis.invoices] == [
        "INV-1",
        "INV-2",
    ]
