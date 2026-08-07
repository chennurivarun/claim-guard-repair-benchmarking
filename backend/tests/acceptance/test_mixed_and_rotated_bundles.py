import shutil
from pathlib import Path

import pytest

from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.extraction.schemas import PageType


@pytest.mark.slow
def test_twenty_page_bundle_finds_invoice_and_estimate(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data/1381115_doc_13811151.pdf"
    if not source.exists() or not shutil.which("tesseract"):
        pytest.skip("Supplied OCR corpus or Tesseract is not available")
    analysis = PDFPipeline(PipelineConfig(ocr_dpi=200)).analyse(source, tmp_path / "mixed")
    assert analysis.page_count == 20
    assert analysis.pages[16].page_type == PageType.INVOICE
    assert analysis.pages[19].page_type == PageType.ESTIMATE
    assert {invoice.document_role for invoice in analysis.invoices} >= {"invoice", "estimate"}


@pytest.mark.slow
def test_rotated_service_book_sequence_is_preserved(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data/1646540_doc_16465407.pdf"
    if not source.exists() or not shutil.which("tesseract"):
        pytest.skip("Supplied OCR corpus or Tesseract is not available")
    analysis = PDFPipeline(PipelineConfig(ocr_dpi=200)).analyse(source, tmp_path / "rotated")
    rotated_pages = analysis.pages[8:12]
    assert [page.rotation for page in rotated_pages] == [90, 90, 90, 90]
    assert all(page.page_type == PageType.SERVICE_HISTORY for page in rotated_pages)
