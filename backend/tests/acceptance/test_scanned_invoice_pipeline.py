import shutil
from pathlib import Path

import pytest

from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.extraction.schemas import PageType


def test_three_scanned_pages_become_three_invoice_units(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data/1185790_doc_11857903.pdf"
    if not source.exists() or not shutil.which("tesseract"):
        pytest.skip("Supplied OCR corpus or Tesseract is not available")
    analysis = PDFPipeline(PipelineConfig(ocr_dpi=220)).analyse(source, tmp_path)
    assert [page.page_type for page in analysis.pages] == [
        PageType.INVOICE,
        PageType.INVOICE,
        PageType.INVOICE,
    ]
    assert len(analysis.invoices) == 3
    assert all(invoice.line_items for invoice in analysis.invoices)
