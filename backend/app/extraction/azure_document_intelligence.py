from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.extraction.schemas import BoundingBox, OCRWord


@dataclass(frozen=True, slots=True)
class CloudOCRPage:
    page_number: int
    text: str
    words: list[OCRWord]
    confidence: float
    rotation: int
    tables: list[list[list[str]]] = field(default_factory=list)


class AzureDocumentIntelligenceOCR:
    """Translate Azure's prebuilt-layout response into ClaimGuard's OCR shape."""

    max_pages_per_request = 2
    min_poll_interval_seconds = 1.0
    max_rate_limit_retries = 4

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str = "prebuilt-layout",
        api_version: str = "2024-11-30",
        timeout_seconds: float = 120,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _polygon_values(polygon: Any) -> list[float]:
        if not isinstance(polygon, list):
            return []
        if polygon and isinstance(polygon[0], dict):
            values: list[float] = []
            for point in polygon:
                values.extend([float(point.get("x", 0)), float(point.get("y", 0))])
            return values
        return [float(value) for value in polygon]

    @classmethod
    def _word(
        cls,
        payload: dict[str, Any],
        *,
        source_width: float,
        source_height: float,
        target_width: float,
        target_height: float,
    ) -> OCRWord | None:
        polygon = cls._polygon_values(payload.get("polygon"))
        if len(polygon) < 4 or not payload.get("content"):
            return None
        xs = polygon[0::2]
        ys = polygon[1::2]
        scale_x = target_width / source_width if source_width else 1
        scale_y = target_height / source_height if source_height else 1
        return OCRWord(
            text=str(payload["content"]),
            confidence=float(payload.get("confidence", 0) or 0),
            bbox=BoundingBox(
                x0=min(xs) * scale_x,
                y0=min(ys) * scale_y,
                x1=max(xs) * scale_x,
                y1=max(ys) * scale_y,
            ),
        )

    @staticmethod
    def _tables_by_page(payloads: list[dict[str, Any]]) -> dict[int, list[list[list[str]]]]:
        tables_by_page: dict[int, list[list[list[str]]]] = {}
        for payload in payloads:
            for table in (payload.get("analyzeResult") or {}).get("tables", []):
                regions = table.get("boundingRegions") or []
                page_number = int((regions[0] if regions else {}).get("pageNumber", 0) or 0)
                if page_number <= 0:
                    continue
                row_count = int(table.get("rowCount", 0) or 0)
                column_count = int(table.get("columnCount", 0) or 0)
                if row_count <= 0 or column_count <= 0:
                    continue
                rows = [["" for _ in range(column_count)] for _ in range(row_count)]
                for cell in table.get("cells", []):
                    row_index = int(cell.get("rowIndex", -1))
                    column_index = int(cell.get("columnIndex", -1))
                    if 0 <= row_index < row_count and 0 <= column_index < column_count:
                        rows[row_index][column_index] = str(cell.get("content", "")).strip()
                tables_by_page.setdefault(page_number, []).append(rows)
        return tables_by_page

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            error = {}
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or "").strip()
        azure_detail = ": ".join(value for value in (code, message) if value)
        status = f"{response.status_code} {response.reason_phrase}".strip()
        return f"Azure Document Intelligence request failed ({status})" + (
            f": {azure_detail}" if azure_detail else ""
        )

    @classmethod
    def _raise_for_status(cls, response: httpx.Response) -> None:
        if response.is_error:
            raise ValueError(cls._error_detail(response))

    @classmethod
    def _retry_delay(cls, response: httpx.Response, retry_number: int) -> float:
        retry_after = response.headers.get("Retry-After", "").strip()
        try:
            requested_delay = float(retry_after)
        except ValueError:
            requested_delay = 0
        return max(
            cls.min_poll_interval_seconds,
            requested_delay,
            min(float(2**retry_number), 8.0),
        )

    def _request_with_rate_limit_retry(
        self,
        request: Callable[[], httpx.Response],
        *,
        deadline: float,
    ) -> httpx.Response:
        for retry_number in range(self.max_rate_limit_retries + 1):
            response = request()
            if response.status_code != 429:
                self._raise_for_status(response)
                return response
            if retry_number == self.max_rate_limit_retries:
                self._raise_for_status(response)
            delay = self._retry_delay(response, retry_number)
            if time.monotonic() + delay >= deadline:
                raise TimeoutError(
                    "Azure Document Intelligence remained rate limited until timeout."
                )
            time.sleep(delay)
        raise AssertionError("Azure rate-limit retry loop exited unexpectedly")

    def _analyse_batch(
        self,
        client: httpx.Client,
        *,
        analyse_url: str,
        headers: dict[str, str],
        pdf_bytes: bytes,
        page_numbers: list[int],
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        params = {
            "api-version": self.api_version,
            "pages": ",".join(str(page_number) for page_number in page_numbers),
        }
        response = self._request_with_rate_limit_retry(
            lambda: client.post(
                analyse_url,
                params=params,
                headers=headers,
                content=pdf_bytes,
            ),
            deadline=deadline,
        )
        operation_url = response.headers.get("operation-location")
        if not operation_url:
            raise ValueError("Azure Document Intelligence did not return an operation location.")

        while time.monotonic() < deadline:
            result = self._request_with_rate_limit_retry(
                lambda: client.get(
                    operation_url,
                    headers={"Ocp-Apim-Subscription-Key": self.api_key},
                ),
                deadline=deadline,
            )
            payload = result.json()
            status = str(payload.get("status", "")).lower()
            if status == "succeeded":
                return payload
            if status in {"failed", "canceled"}:
                error = payload.get("error") or {}
                raise ValueError(str(error.get("message") or "Azure document analysis failed."))
            time.sleep(self.min_poll_interval_seconds)
        raise TimeoutError("Azure document analysis timed out.")

    def analyse(
        self,
        pdf_path: Path,
        page_dimensions: dict[int, tuple[float, float]],
    ) -> dict[int, CloudOCRPage]:
        analyse_url = f"{self.endpoint}/documentintelligence/documentModels/{self.model}:analyze"
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/octet-stream",
        }
        requested_pages = sorted(page_dimensions)
        if not requested_pages:
            return {}
        pdf_bytes = pdf_path.read_bytes()
        payloads: list[dict[str, Any]] = []
        with httpx.Client(timeout=min(self.timeout_seconds, 60)) as client:
            for start in range(0, len(requested_pages), self.max_pages_per_request):
                payloads.append(
                    self._analyse_batch(
                        client,
                        analyse_url=analyse_url,
                        headers=headers,
                        pdf_bytes=pdf_bytes,
                        page_numbers=requested_pages[start : start + self.max_pages_per_request],
                    )
                )

        pages: dict[int, CloudOCRPage] = {}
        tables_by_page = self._tables_by_page(payloads)
        azure_pages = [
            page
            for payload in payloads
            for page in (payload.get("analyzeResult") or {}).get("pages", [])
        ]
        for page in azure_pages:
            page_number = int(page.get("pageNumber", 0) or 0)
            if page_number not in page_dimensions:
                continue
            target_width, target_height = page_dimensions[page_number]
            source_width = float(page.get("width", target_width) or target_width)
            source_height = float(page.get("height", target_height) or target_height)
            words = [
                word
                for item in page.get("words", [])
                if (
                    word := self._word(
                        item,
                        source_width=source_width,
                        source_height=source_height,
                        target_width=target_width,
                        target_height=target_height,
                    )
                )
            ]
            lines = [
                str(line.get("content", "")).strip()
                for line in page.get("lines", [])
                if str(line.get("content", "")).strip()
            ]
            confidences = [word.confidence for word in words if word.confidence > 0]
            pages[page_number] = CloudOCRPage(
                page_number=page_number,
                text="\n".join(lines),
                words=words,
                confidence=sum(confidences) / len(confidences) if confidences else 0,
                rotation=round(float(page.get("angle", 0) or 0)) % 360,
                tables=tables_by_page.get(page_number, []),
            )
        return pages
