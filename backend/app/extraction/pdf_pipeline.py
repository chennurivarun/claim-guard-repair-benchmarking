from __future__ import annotations

import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image

from app.extraction.azure_document_intelligence import (
    AzureDocumentIntelligenceOCR,
    CloudOCRPage,
)
from app.extraction.invoice_parser import InvoiceParser
from app.extraction.schemas import (
    BoundingBox,
    DocumentAnalysis,
    OCRWord,
    PageAnalysis,
    PageType,
)

try:
    import pytesseract
    from pytesseract import Output
except ImportError:  # pragma: no cover - exercised in no-OCR deployments
    pytesseract = None
    Output = None


class OCRUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PipelineConfig:
    native_min_characters: int = 80
    native_min_words: int = 20
    render_dpi: int = 150
    ocr_dpi: int = 300
    ocr_enabled: bool = True
    max_pages: int = 100


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_words(page: fitz.Page) -> list[OCRWord]:
    words: list[OCRWord] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if text.strip():
            words.append(
                OCRWord(
                    text=text,
                    confidence=1.0,
                    bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                )
            )
    return words


def _render_page(page: fitz.Page, dpi: int) -> Image.Image:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")


def _ocr_image(
    image: Image.Image,
    *,
    target_width: float,
    target_height: float,
) -> tuple[str, list[OCRWord], float, int]:
    if pytesseract is None or Output is None:
        raise OCRUnavailableError(
            "Local Tesseract OCR is unavailable. Configure Azure Document Intelligence "
            "or upload a PDF with embedded text."
        )
    rotation = 0
    try:
        osd = pytesseract.image_to_osd(image, output_type=Output.DICT)
        rotation = int(osd.get("rotate", 0) or 0)
        if rotation:
            image = image.rotate(rotation, expand=True, fillcolor="white")
    except Exception:
        rotation = 0
    scale_x = target_width / image.width
    scale_y = target_height / image.height
    data = pytesseract.image_to_data(image, lang="eng", output_type=Output.DICT, config="--psm 6")
    lines: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    words: list[OCRWord] = []
    confidences: list[float] = []
    for index, raw_text in enumerate(data["text"]):
        text = raw_text.strip()
        try:
            confidence = max(float(data["conf"][index]), 0.0) / 100
        except (TypeError, ValueError):
            confidence = 0.0
        if not text:
            continue
        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])
        words.append(
            OCRWord(
                text=text,
                confidence=confidence,
                bbox=BoundingBox(
                    x0=left * scale_x,
                    y0=top * scale_y,
                    x1=(left + width) * scale_x,
                    y1=(top + height) * scale_y,
                ),
            )
        )
        lines[(data["block_num"][index], data["par_num"][index], data["line_num"][index])].append(
            (left, text)
        )
        if confidence > 0:
            confidences.append(confidence)
    text_lines = [" ".join(word for _, word in sorted(line)) for line in lines.values()]
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return "\n".join(text_lines), words, mean_confidence, rotation


def classify_page(text: str, *, image_only: bool) -> tuple[PageType, float, list[str]]:
    lower = text.lower()
    signals: list[str] = []
    strong_keyword_groups = {
        PageType.ENGINEER_ASSESSMENT: (
            "engineer assessment report",
            "audatex system using manufacturer times",
            "assessment number",
        ),
        PageType.CREDIT_NOTE: ("credit note",),
        PageType.ESTIMATE: (
            "estimate/order",
            "estimate / order",
            "quotation",
        ),
        PageType.INVOICE: (
            "sales invoice",
            "tax invoice",
            "invoice total",
        ),
        PageType.MOT: ("mot test certificate", "ministry of transport"),
        PageType.VEHICLE_DOCUMENT: ("v5c", "vehicle registration certificate", "dvla"),
        PageType.SERVICE_HISTORY: ("service history", "work history", "service record"),
    }
    for page_type, keywords in strong_keyword_groups.items():
        found = [keyword for keyword in keywords if keyword in lower]
        if found:
            signals.extend(found)
            confidence = min(0.72 + 0.08 * len(found), 0.99)
            return page_type, confidence, signals
    if "invoice" in lower:
        return PageType.INVOICE, 0.78, ["invoice"]
    if any(keyword in lower for keyword in ("estimate", "quote")):
        found = [keyword for keyword in ("estimate", "quote") if keyword in lower]
        return PageType.ESTIMATE, 0.72, found
    if len(lower.strip()) < 5:
        return (PageType.PHOTO if image_only else PageType.BLANK), 0.62, ["no readable text"]
    money_count = len(re.findall(r"£?\d+[,.]\d{2}", lower))
    if money_count >= 4 and any(word in lower for word in ("vat", "total", "qty")):
        return PageType.INVOICE, 0.72, ["financial table", f"{money_count} amounts"]
    return PageType.OTHER, 0.55, ["no decisive document keywords"]


def _group_key(page_type: PageType, text: str, page_number: int) -> str | None:
    if page_type not in {PageType.INVOICE, PageType.ESTIMATE, PageType.CREDIT_NOTE}:
        return None
    patterns = (
        r"Invoice\s*(?:No\.?|Number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]{2,})",
        r"Document No\.?\s*[:#]?\s*([A-Z0-9/-]{3,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).upper()
            if any(character.isdigit() for character in candidate):
                return f"{page_type.value}:{candidate}"
    return f"{page_type.value}:page-{page_number}"


def _label_rotated_service_sequences(pages: list[PageAnalysis]) -> None:
    """Use page-neighbour context for rotated service-book spreads with sparse OCR."""

    run: list[PageAnalysis] = []

    def apply(candidate_run: list[PageAnalysis]) -> None:
        if len(candidate_run) < 2:
            return
        combined = " ".join(page.text.lower() for page in candidate_run)
        service_signals = ("service", "workshop", "inspection", "maintenance")
        if not any(signal in combined for signal in service_signals):
            return
        for candidate in candidate_run:
            if candidate.page_type == PageType.OTHER:
                candidate.page_type = PageType.SERVICE_HISTORY
                candidate.classification_confidence = max(candidate.classification_confidence, 0.68)
                candidate.classification_signals.append("rotated service-book sequence")

    for page in pages:
        if page.rotation in {90, 270} and (not run or page.page_number == run[-1].page_number + 1):
            run.append(page)
        else:
            apply(run)
            run = [page] if page.rotation in {90, 270} else []
    apply(run)


class PDFPipeline:
    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        cloud_ocr: AzureDocumentIntelligenceOCR | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.parser = InvoiceParser()
        self.cloud_ocr = cloud_ocr

    def analyse(self, pdf_path: str | Path, output_dir: str | Path) -> DocumentAnalysis:
        source = Path(pdf_path).resolve()
        if source.suffix.lower() != ".pdf" or source.read_bytes()[:5] != b"%PDF-":
            raise ValueError("Only valid PDF files are accepted.")
        document = fitz.open(source)
        if document.needs_pass:
            raise ValueError("Encrypted PDFs are not supported.")
        if len(document) > self.config.max_pages:
            raise ValueError(f"PDF exceeds the {self.config.max_pages}-page limit.")

        render_dir = Path(output_dir)
        render_dir.mkdir(parents=True, exist_ok=True)
        page_dimensions = {
            index + 1: (page.rect.width, page.rect.height) for index, page in enumerate(document)
        }
        cloud_pages: dict[int, CloudOCRPage] = {}
        if self.cloud_ocr is not None:
            ocr_page_dimensions = {
                index + 1: page_dimensions[index + 1]
                for index, page in enumerate(document)
                if (
                    len(page.get_text("text").strip()) < self.config.native_min_characters
                    or len(_native_words(page)) < self.config.native_min_words
                )
            }
            if ocr_page_dimensions:
                try:
                    cloud_pages = self.cloud_ocr.analyse(source, ocr_page_dimensions)
                except Exception as exc:
                    raise OCRUnavailableError(
                        f"Azure Document Intelligence OCR failed: {exc}"
                    ) from exc
        pages: list[PageAnalysis] = []
        for index, page in enumerate(document):
            native_text = page.get_text("text").strip()
            native_words = _native_words(page)
            use_native = (
                len(native_text) >= self.config.native_min_characters
                and len(native_words) >= self.config.native_min_words
            )
            preview = _render_page(page, self.config.render_dpi)
            preview_path = render_dir / f"page-{index + 1:03d}.png"
            preview.save(preview_path)
            structured_tables: list[list[list[str]]] = []

            if use_native:
                text = native_text
                words = native_words
                method = "native"
                extraction_confidence = 0.98
                detected_rotation = page.rotation
            elif (cloud_page := cloud_pages.get(index + 1)) is not None:
                text = cloud_page.text
                words = cloud_page.words
                extraction_confidence = cloud_page.confidence
                method = "azure_layout"
                detected_rotation = (page.rotation + cloud_page.rotation) % 360
                structured_tables = cloud_page.tables
            elif self.cloud_ocr is not None:
                raise OCRUnavailableError(
                    "Azure Document Intelligence returned no readable OCR result for "
                    f"page {index + 1}. Check that the model is exactly "
                    "'prebuilt-layout' and try again."
                )
            elif self.config.ocr_enabled:
                try:
                    text, words, extraction_confidence, ocr_rotation = _ocr_image(
                        _render_page(page, self.config.ocr_dpi),
                        target_width=page.rect.width,
                        target_height=page.rect.height,
                    )
                except Exception as exc:
                    raise OCRUnavailableError(
                        "Local Tesseract OCR failed. Configure both the Azure Document "
                        "Intelligence endpoint and API key, set the model to "
                        "'prebuilt-layout', restart FastAPI, and try again."
                    ) from exc
                method = "ocr" if text else "vision_required"
                detected_rotation = (page.rotation + ocr_rotation) % 360
            else:
                text, words, extraction_confidence, detected_rotation = "", [], 0.0, page.rotation
                method = "vision_required"

            page_type, class_confidence, signals = classify_page(text, image_only=not use_native)
            page_info = PageAnalysis(
                page_number=index + 1,
                width=page.rect.width,
                height=page.rect.height,
                rotation=detected_rotation,
                native_character_count=len(native_text),
                positioned_word_count=len(native_words),
                image_count=len(page.get_images(full=True)),
                extraction_method=method,
                extraction_confidence=extraction_confidence,
                text=text,
                page_type=page_type,
                classification_confidence=class_confidence,
                classification_signals=signals,
                group_key=_group_key(page_type, text, index + 1),
                rendered_image_path=preview_path,
                words=words,
                tables=structured_tables,
            )
            pages.append(page_info)

        _label_rotated_service_sequences(pages)

        analysis = DocumentAnalysis(
            source_path=source,
            sha256=sha256_file(source),
            page_count=len(pages),
            pages=pages,
        )
        groups: dict[str, list[PageAnalysis]] = defaultdict(list)
        for page in pages:
            if page.group_key:
                groups[page.group_key].append(page)
        for key, grouped_pages in groups.items():
            role = "estimate" if key.startswith(PageType.ESTIMATE.value) else "invoice"
            try:
                analysis.invoices.append(
                    self.parser.parse_group(source, grouped_pages, document_role=role)
                )
            except Exception:
                # A single malformed invoice unit must not abort the rest of the document.
                continue
        has_engineer_assessment = any(
            page.page_type == PageType.ENGINEER_ASSESSMENT for page in pages
        )
        if not analysis.invoices and not has_engineer_assessment:
            raise ValueError(
                "No readable invoice was found. Check the PDF and OCR configuration, "
                "then try again."
            )
        return analysis
