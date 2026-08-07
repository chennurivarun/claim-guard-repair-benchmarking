from __future__ import annotations

import time
from dataclasses import dataclass
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


class AzureDocumentIntelligenceOCR:
    """Translate Azure's prebuilt-layout response into ClaimGuard's OCR shape."""

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

    def analyse(
        self,
        pdf_path: Path,
        page_dimensions: dict[int, tuple[float, float]],
    ) -> dict[int, CloudOCRPage]:
        analyse_url = (
            f"{self.endpoint}/documentintelligence/documentModels/"
            f"{self.model}:analyze"
        )
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/octet-stream",
        }
        deadline = time.monotonic() + self.timeout_seconds
        with httpx.Client(timeout=min(self.timeout_seconds, 60)) as client:
            response = client.post(
                analyse_url,
                params={"api-version": self.api_version},
                headers=headers,
                content=pdf_path.read_bytes(),
            )
            response.raise_for_status()
            operation_url = response.headers.get("operation-location")
            if not operation_url:
                raise ValueError(
                    "Azure Document Intelligence did not return an operation location."
                )
            payload: dict[str, Any] = {}
            while time.monotonic() < deadline:
                result = client.get(
                    operation_url,
                    headers={"Ocp-Apim-Subscription-Key": self.api_key},
                )
                result.raise_for_status()
                payload = result.json()
                status = str(payload.get("status", "")).lower()
                if status == "succeeded":
                    break
                if status in {"failed", "canceled"}:
                    error = payload.get("error") or {}
                    raise ValueError(
                        str(error.get("message") or "Azure document analysis failed.")
                    )
                time.sleep(0.25)
            else:
                raise TimeoutError("Azure document analysis timed out.")

        pages: dict[int, CloudOCRPage] = {}
        for page in (payload.get("analyzeResult") or {}).get("pages", []):
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
            )
        return pages
