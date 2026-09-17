"""Smoke tests for the client-format `.docx` fixtures (Task 2).

Each fixture must survive the real upload-normalisation path -- the same
`normalise_document_upload` the API uses for every DOCX upload -- and the
converted PDF's extracted text must still contain the identifying values
recorded in `manifest.json` (claim reference, registration, gross total).
This does not exercise the extraction parsers; it only guarantees the
fixtures are readable inputs for them.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import fitz
import pytest

import app.services.document_processing as document_processing

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "sample-data" / "client-formats"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


def _load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _converted_text(monkeypatch: pytest.MonkeyPatch, docx_path: Path) -> str:
    # Force the pure-Python reportlab conversion path so the test is
    # deterministic and does not depend on LibreOffice being installed.
    monkeypatch.setattr(document_processing.shutil, "which", lambda _: None)

    content = docx_path.read_bytes()
    normalised = document_processing.normalise_document_upload(docx_path.name, content)
    assert normalised.content.startswith(b"%PDF-")
    assert normalised.source_format == "docx-python"

    document = fitz.open(stream=normalised.content, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()


@pytest.fixture()
def manifest() -> list[dict]:
    return _load_manifest()


def test_manifest_exists_and_covers_every_fixture(manifest: list[dict]) -> None:
    assert len(manifest) == 16
    filenames = {entry["filename"] for entry in manifest}
    assert filenames == {
        "DL_Auda_format_1_assessment.docx",
        "DL_Repair_Invoice_format_1.docx",
        "DL_Auda_format_2_assessment.docx",
        "DL_Invoice_2_request_for_payment.docx",
        "DL_Auda_format_3_assessment.docx",
        "DL_Invoice_3_request_for_payment.docx",
        "DL_Auda_format_4_assessment.docx",
        "DL_Invoice_4_request_for_payment.docx",
        "DL_Auda_format_5_assessment.docx",
        "DL_Repair_Invoice_format_5.docx",
        "DL_Auda_format_6_assessment.docx",
        "DL_Repair_Invoice_format_6.docx",
        "DL_Auda_format_7_assessment.docx",
        "DL_Repair_Invoice_format_7.docx",
        "EXL_demo_engineer_report.docx",
        "EXL_demo_invoice.docx",
    }
    for entry in manifest:
        assert (FIXTURES_DIR / entry["filename"]).is_file()


@pytest.mark.parametrize(
    "filename",
    [entry["filename"] for entry in _load_manifest()],
)
def test_fixture_converts_and_contains_manifest_identity(
    filename: str, manifest: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = next(item for item in manifest if item["filename"] == filename)
    text = _converted_text(monkeypatch, FIXTURES_DIR / filename)

    assert entry["claim_reference"] in text
    assert entry["registration"] in text
    if entry["gross_total"] is not None:
        # The manifest records amounts unpunctuated; the EXL report's
        # Summary Calculation is the one block in the corpus that prints a
        # thousands separator ("Grand Total: 5,068.87"), so both spellings
        # of the same figure count as present.
        grouped = f"{Decimal(entry['gross_total']):,}"
        assert entry["gross_total"] in text or grouped in text
