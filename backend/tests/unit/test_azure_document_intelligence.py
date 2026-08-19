from pathlib import Path

import fitz
import httpx
import pytest

import app.extraction.azure_document_intelligence as azure_module
from app.extraction.azure_document_intelligence import AzureDocumentIntelligenceOCR
from app.extraction.pdf_pipeline import OCRUnavailableError, PDFPipeline, PipelineConfig


def test_azure_word_coordinates_scale_into_existing_source_viewer_space() -> None:
    word = AzureDocumentIntelligenceOCR._word(
        {
            "content": "Windscreen",
            "confidence": 0.97,
            "polygon": [1, 2, 3, 2, 3, 4, 1, 4],
        },
        source_width=10,
        source_height=10,
        target_width=100,
        target_height=200,
    )

    assert word is not None
    assert word.text == "Windscreen"
    assert word.confidence == 0.97
    assert word.bbox.model_dump() == {
        "x0": 10.0,
        "y0": 40.0,
        "x1": 30.0,
        "y1": 80.0,
    }


def test_azure_error_includes_service_code_and_message() -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": "InvalidContent",
                "message": "The PDF is damaged or unsupported.",
            }
        },
        request=httpx.Request("POST", "https://azure.test/analyze"),
    )

    with pytest.raises(
        ValueError,
        match="400 Bad Request.*InvalidContent.*damaged or unsupported",
    ):
        AzureDocumentIntelligenceOCR._raise_for_status(response)


def test_azure_layout_tables_are_preserved_by_page() -> None:
    tables = AzureDocumentIntelligenceOCR._tables_by_page(
        [
            {
                "analyzeResult": {
                    "tables": [
                        {
                            "rowCount": 2,
                            "columnCount": 4,
                            "boundingRegions": [{"pageNumber": 2}],
                            "cells": [
                                {"rowIndex": 0, "columnIndex": 0, "content": "Description"},
                                {"rowIndex": 0, "columnIndex": 1, "content": "Qty"},
                                {"rowIndex": 0, "columnIndex": 2, "content": "Unit"},
                                {"rowIndex": 0, "columnIndex": 3, "content": "Subtotal"},
                                {"rowIndex": 1, "columnIndex": 0, "content": "Oil filter"},
                                {"rowIndex": 1, "columnIndex": 1, "content": "1"},
                                {"rowIndex": 1, "columnIndex": 2, "content": "8.95"},
                                {"rowIndex": 1, "columnIndex": 3, "content": "8.95"},
                            ],
                        }
                    ]
                }
            }
        ]
    )

    assert tables[2] == [
        [
            ["Description", "Qty", "Unit", "Subtotal"],
            ["Oil filter", "1", "8.95", "8.95"],
        ]
    ]


def test_azure_batches_two_pages_and_retries_throttled_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "three-pages.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    requested_batches: list[str] = []
    sleeps: list[float] = []
    operations: dict[str, tuple[int, ...]] = {}
    poll_counts: dict[str, int] = {}
    accepted_operations = 0

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, url, *, params, headers, content):
            nonlocal accepted_operations
            requested_batches.append(params["pages"])
            request = httpx.Request("POST", url)
            if len(requested_batches) == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "1"},
                    json={"error": {"code": "429", "message": "Rate limit exceeded"}},
                    request=request,
                )
            accepted_operations += 1
            operation_url = f"https://azure.test/operations/{accepted_operations}"
            operations[operation_url] = tuple(
                int(page_number) for page_number in params["pages"].split(",")
            )
            return httpx.Response(
                202,
                headers={"operation-location": operation_url},
                request=request,
            )

        def get(self, url, *, headers):
            poll_counts[url] = poll_counts.get(url, 0) + 1
            request = httpx.Request("GET", url)
            if url.endswith("/1") and poll_counts[url] == 1:
                return httpx.Response(200, json={"status": "running"}, request=request)
            pages = [
                {
                    "pageNumber": page_number,
                    "width": 100,
                    "height": 200,
                    "lines": [{"content": f"Page {page_number}"}],
                    "words": [],
                }
                for page_number in operations[url]
            ]
            return httpx.Response(
                200,
                json={"status": "succeeded", "analyzeResult": {"pages": pages}},
                request=request,
            )

    monkeypatch.setattr(azure_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(azure_module.time, "sleep", sleeps.append)

    pages = AzureDocumentIntelligenceOCR(
        endpoint="https://azure.test",
        api_key="test-key",
    ).analyse(
        pdf_path,
        {1: (100, 200), 2: (100, 200), 3: (100, 200)},
    )

    assert requested_batches == ["1,2", "1,2", "3"]
    assert sorted(pages) == [1, 2, 3]
    assert pages[3].text == "Page 3"
    assert sleeps and all(delay >= 1 for delay in sleeps)


def test_pipeline_sends_only_low_text_pages_to_cloud_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    document = fitz.open()
    native_page = document.new_page()
    native_page.insert_textbox(
        fitz.Rect(50, 50, 550, 750),
        (
            "Repair invoice vehicle registration AB12 CDE invoice number INV-100 "
            "labour parts paint subtotal VAT total amount due "
        )
        * 8,
    )
    document.new_page()
    document.save(pdf_path)
    document.close()
    requested_pages: list[int] = []

    class RecordingAzure:
        def analyse(self, source, page_dimensions):
            requested_pages.extend(page_dimensions)
            return {}

    with pytest.raises(OCRUnavailableError, match="page 2"):
        PDFPipeline(
            PipelineConfig(ocr_enabled=True),
            cloud_ocr=RecordingAzure(),
        ).analyse(pdf_path, tmp_path / "pages")

    assert requested_pages == [2]
