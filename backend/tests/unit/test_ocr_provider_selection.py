from pathlib import Path

import fitz
import pytest

import app.extraction.pdf_pipeline as pdf_pipeline_module
from app.config import Settings
from app.extraction.pdf_pipeline import OCRUnavailableError, PDFPipeline, PipelineConfig
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
