from __future__ import annotations

from pathlib import Path

import pytest

from app.extraction.engineer_assessment_parser import parse_engineer_assessment
from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.extraction.schemas import PageType

PAIR_DIR = Path(__file__).resolve().parents[3] / "sample-data" / "engineer-invoice-pairs"


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
