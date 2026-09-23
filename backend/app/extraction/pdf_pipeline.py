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
    ExtractedEngineerAssessment,
    ExtractedInvoice,
    OCRWord,
    PageAnalysis,
    PageType,
)
from app.llm.base import LLMProviderError
from app.llm.invoice_extraction import MultimodalInvoiceExtractor, merge_invoice_extractions

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
    vision_max_batches: int = 3
    text_max_batches: int = 3
    assessment_document: bool = False


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
            "engineer report",
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
        return PageType.INVOICE, 0.72, [_MONEY_TABLE_SIGNAL, f"{money_count} amounts"]
    return PageType.OTHER, 0.55, ["no decisive document keywords"]


def _group_key(page_type: PageType, text: str, page_number: int) -> str | None:
    if page_type not in {PageType.INVOICE, PageType.ESTIMATE, PageType.CREDIT_NOTE}:
        return None
    # ponytail: `~` must survive inside an invoice number (e.g. "343653726836/1~3538");
    # widen the character class rather than adding a second pattern.
    patterns = (
        r"Invoice\s*(?:No\.?|Number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/~-]{2,})",
        r"Document No\.?\s*[:#]?\s*([A-Z0-9/~-]{3,})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
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


_SCHEDULE_HEADING_PATTERN = re.compile(r"(?im)^\s*(?:parts|extras)\b")
_PRICED_ROW_AMOUNT_PATTERN = re.compile(r"(?:£|gbp)?\s*\d[\d,]*\.\d{2}\s*$", re.IGNORECASE)
_GOVERNED_OPERATION_ROW_PATTERN = re.compile(r"(?im)^\s*op\|")
_ASSESSMENT_IDENTITY_PATTERN = re.compile(
    r"(?im)^\s*(?:summary information|assessment report|assessment number|"
    r"report type\s*:?\s*full report|engineer report|estimate details|estimate id)"
)
_NON_LINE_ROW_TOKENS = ("total", "deduction", "discount", "vat", "balance", "payment")
#: A schedule row's trailing figure is not always money: a LABOUR schedule
#: prints work units ("REPAIR REAR BUMPER   30.0"), so the continuation test
#: accepts any trailing number, not just a two-decimal amount.
_SCHEDULE_ROW_NUMBER_PATTERN = re.compile(
    r"(?:£|gbp)?\s*\d[\d,]*(?:\.\d+)?\s*$", re.IGNORECASE
)
#: The signal ``classify_page`` leaves when a page was called an invoice on
#: the strength of its amounts alone -- no invoice, credit-note or estimate
#: wording anywhere on it.  It is the weakest invoice verdict there is, and
#: the only one an authorised assessment's own schedule can trip.
_MONEY_TABLE_SIGNAL = "financial table"
#: Wording that makes a page a document in its own right rather than the tail
#: of the schedule on the page before it.
_STANDALONE_DOCUMENT_PATTERN = re.compile(
    r"(?i)\b(?:invoice|credit note|remittance|payment advice|statement of account|"
    r"quotation|estimate\s*/\s*order|amount due|please pay|sort code)\b"
)
_ASSESSMENT_CONTINUATION_HINTS = re.compile(
    r"(?i)\b(?:model\s+options?|vehicle\s+condition|vehicle\s+details|repair\s+information|"
    r"repair\s+(?:left|right|front|rear)|corrosion\s+protection|labour|paint\s+work|parts|"
    r"extras|assessment\s+number|with\s+a/c|without\s+alarm|heated\s+windscreen|"
    r"parking\s+sensor)\b"
)


def _schedule_row_count(text: str, pattern: re.Pattern[str]) -> int:
    """Count rows that read as individual schedule lines, not totals."""

    count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.casefold()
        if not line or any(token in lower for token in _NON_LINE_ROW_TOKENS):
            continue
        if not re.search(r"[A-Za-z]{3}", line):
            continue
        if pattern.search(line):
            count += 1
    return count


def _priced_row_count(text: str) -> int:
    """Count rows that read as individually priced schedule lines, not totals."""

    return _schedule_row_count(text, _PRICED_ROW_AMOUNT_PATTERN)


def _is_schedule_continuation(text: str) -> bool:
    """Does this page read as the tail of the schedule on the page before it?

    A repair schedule runs onto pages that carry no identity marker of their
    own -- a bare continuation of the table and nothing else -- which the
    classifier can only call OTHER. Such a page is recognised by its shape:
    several code/description rows ending in a number, and none of the wording
    that would make it a document in its own right.
    """

    if _STANDALONE_DOCUMENT_PATTERN.search(text):
        return False
    return _schedule_row_count(text, _SCHEDULE_ROW_NUMBER_PATTERN) >= 2


def _reclassify_priced_assessment_pages(pages: list[PageAnalysis]) -> None:
    """Mixed documents: assessment classification must not suppress priced pages.

    Audatex-style "Full Report" documents repeat the assessment header on every
    page, so genuinely priced pages (a PARTS schedule, an EXTRAS charge list)
    classify as ENGINEER_ASSESSMENT and never reach invoice extraction. For a
    genuinely mixed bundle (assessment content alongside unrelated priced
    pages that are not part of an authorised estimate) those pages are
    flipped to INVOICE — plus OTHER pages carrying multiple currency
    amounts — so they enter the standard invoice extraction ladder with
    correct page provenance. Pages holding governed ``OP|`` operation rows
    remain assessment evidence for the deterministic assessment parser.

    An authorised Audatex estimate (identified by a "Summary Information" /
    "Assessment Report" / "Assessment Number" / "Report Type: Full Report" /
    "Engineer Report" / "Estimate Details" / "Estimate ID" heading on any
    page) is a different case entirely: its PARTS/EXTRAS/LABOUR schedules
    are assessment evidence, not invoice units, and must never be flipped —
    see the client requirement recorded in
    tests/acceptance/test_auda_style_documents.py. That check only ever
    skips ENGINEER_ASSESSMENT pages, though: the OTHER-page rescue below
    must keep running for the rest of the document, because a genuinely
    mixed bundle can carry both an authorised assessment and unrelated
    priced pages.

    The reverse case is settled here too. An authorised assessment's schedule
    runs onto pages with no identity marker of their own, which classify as
    OTHER; left that way the page is fed to the assessment parser while the
    document says it is something else, so its operations point at an OTHER
    page and a configured vision extractor reads the same page a second time
    as an invoice. An OTHER page directly following an assessment page in an
    authorised assessment, that reads as a continuation of the schedule, is
    therefore reclassified ENGINEER_ASSESSMENT -- page type, source page,
    the invoice ladder and the vision-candidate list then all agree.
    """

    if not any(page.page_type == PageType.ENGINEER_ASSESSMENT for page in pages):
        return
    is_authorised_assessment = any(
        _ASSESSMENT_IDENTITY_PATTERN.search(page.text) for page in pages
    )
    previous_type: PageType | None = None
    for page in pages:
        if _GOVERNED_OPERATION_ROW_PATTERN.search(page.text):
            previous_type = page.page_type
            continue
        if page.page_type == PageType.ENGINEER_ASSESSMENT:
            if is_authorised_assessment:
                previous_type = page.page_type
                continue
            if (
                not _SCHEDULE_HEADING_PATTERN.search(page.text)
                or _priced_row_count(page.text) < 3
            ):
                previous_type = page.page_type
                continue
            signal = "priced schedule in assessment document"
        elif (
            is_authorised_assessment
            and page.page_type == PageType.INVOICE
            and _MONEY_TABLE_SIGNAL in page.classification_signals
            and previous_type == PageType.ENGINEER_ASSESSMENT
            and not _STANDALONE_DOCUMENT_PATTERN.search(page.text)
            and (
                _is_schedule_continuation(page.text)
                or _ASSESSMENT_CONTINUATION_HINTS.search(page.text)
            )
        ):
            # The same continuation rescue as below, for the page that carries
            # so much money it tripped the amounts-only invoice heuristic
            # instead of landing on OTHER. Client format 4's third page is one:
            # it opens mid-PAINT WORK and runs through Material cost paint,
            # PARTS and EXTRAS without reprinting the assessment header, so
            # left as an invoice it takes a third of the report's schedule out
            # of the assessment -- the paint-materials and parts breakdowns go
            # empty and a phantom numberless invoice appears on the claim.
            # Only the weakest invoice verdict is overturned: a page saying
            # "invoice", "amount due" or "remittance" anywhere on it fails
            # ``_is_schedule_continuation`` and stays an invoice.
            page.page_type = PageType.ENGINEER_ASSESSMENT
            page.classification_signals.append("assessment continuation")
            page.classification_confidence = max(page.classification_confidence, 0.72)
            page.group_key = None
            previous_type = page.page_type
            continue
        elif page.page_type == PageType.OTHER:
            if (
                is_authorised_assessment
                and previous_type == PageType.ENGINEER_ASSESSMENT
                and not _STANDALONE_DOCUMENT_PATTERN.search(page.text)
                and _priced_row_count(page.text) < 2
                and (
                    _is_schedule_continuation(page.text)
                    or _ASSESSMENT_CONTINUATION_HINTS.search(page.text)
                )
            ):
                page.page_type = PageType.ENGINEER_ASSESSMENT
                page.classification_signals.append("assessment continuation")
                page.classification_confidence = max(page.classification_confidence, 0.72)
                page.group_key = None
                previous_type = page.page_type
                continue
            if _priced_row_count(page.text) < 2:
                previous_type = page.page_type
                continue
            signal = "priced rows in assessment document"
        else:
            previous_type = page.page_type
            continue
        page.page_type = PageType.INVOICE
        page.classification_signals.append(signal)
        page.classification_confidence = max(page.classification_confidence, 0.72)
        page.group_key = _group_key(PageType.INVOICE, page.text, page.page_number)
        previous_type = page.page_type


def _relink_invoice_continuation_pages(pages: list[PageAnalysis]) -> None:
    """Keep a continued invoice in one extraction group after Word reflow.

    LibreOffice can move an invoice's totals and the tail of its charges onto
    a second PDF page. That page still contains ``Invoice total`` and enough
    money values to classify as an invoice, but no longer repeats the invoice
    number. Without this pass it receives a fresh ``invoice:page-N`` key and
    becomes a phantom second invoice.

    A continuation must immediately follow the same document type, have only
    the fallback page key, carry no new document identity or heading, and
    contain a closing total/VAT signal. A genuinely separate numberless
    invoice headed ``INVOICE`` therefore remains its own reviewable document.
    """

    previous: PageAnalysis | None = None
    explicit_identity = re.compile(
        r"(?im)^\s*(?:invoice\s*(?:no\.?|number)|document\s+no\.?)\s*[:#]?\s*\S+"
    )
    document_heading = re.compile(
        r"(?im)^\s*(?:sales\s+invoice|tax\s+invoice|invoice|credit\s+note|quotation)\s*$"
    )
    closing_totals = re.compile(
        r"(?i)\b(?:invoice\s+total|total\s+due|amount\s+equivalent\s+to\s+vat|"
        r"vat\s*@?|subtotal|balance\s+due)\b"
    )
    for page in pages:
        fallback_key = f"{page.page_type.value}:page-{page.page_number}"
        previous_fallback = (
            f"{previous.page_type.value}:page-{previous.page_number}" if previous else None
        )
        may_continue = (
            previous is not None
            and page.page_number == previous.page_number + 1
            and page.page_type == previous.page_type
            and page.page_type in {PageType.INVOICE, PageType.ESTIMATE, PageType.CREDIT_NOTE}
            and page.extraction_method in {"native", "azure_layout"}
            and previous.extraction_method in {"native", "azure_layout"}
            and page.group_key == fallback_key
            and previous.group_key is not None
            and previous.group_key != previous_fallback
            and not explicit_identity.search(page.text)
            and not document_heading.search(page.text)
            and closing_totals.search(page.text) is not None
        )
        if may_continue:
            page.group_key = previous.group_key
            page.classification_signals.append("invoice continuation")
            page.classification_confidence = max(page.classification_confidence, 0.8)
        previous = page


def _merge_assessment_batches(
    batches: list[ExtractedEngineerAssessment],
) -> ExtractedEngineerAssessment | None:
    if not batches:
        return None
    fields = batches[0].fields.model_dump()
    operations = []
    page_numbers: set[int] = set()
    confidence = 1.0
    for batch in batches:
        for name, value in batch.fields.model_dump().items():
            if fields.get(name) is None or fields.get(name) == "" or fields.get(name) == []:
                if value is not None and value != "" and value != []:
                    fields[name] = value
        for operation in batch.operations:
            operations.append(
                operation.model_copy(update={"sequence_no": len(operations) + 1})
            )
        page_numbers.update(batch.page_numbers)
        confidence = min(confidence, batch.extraction_confidence)
    return batches[0].model_copy(
        update={
            "fields": batches[0].fields.model_copy(update=fields),
            "operations": operations,
            "page_numbers": sorted(page_numbers),
            "extraction_confidence": confidence,
        }
    )


def _has_usable_lines(invoice: ExtractedInvoice) -> bool:
    """Return whether the deterministic parse yielded at least one priced line."""

    return any(
        line.line_total_net is not None and line.line_total_net > 0
        for line in invoice.line_items
    )


def _group_has_readable_text(pages: list[PageAnalysis]) -> bool:
    """Return whether a page group has enough text for the text-only LLM tier to read."""

    combined = " ".join(page.text for page in pages)
    return len(combined.strip()) >= 20


class PDFPipeline:
    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        cloud_ocr: AzureDocumentIntelligenceOCR | None = None,
        vision_extractor: MultimodalInvoiceExtractor | None = None,
        text_extractor: MultimodalInvoiceExtractor | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.vision_extractor = vision_extractor
        self.text_extractor = text_extractor
        self.parser = InvoiceParser(vision_extractor)
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
                    if self.vision_extractor is None:
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
            elif self.cloud_ocr is not None and self.vision_extractor is None:
                raise OCRUnavailableError(
                    "Azure Document Intelligence returned no readable OCR result for "
                    f"page {index + 1}. Check that the model is exactly "
                    "'prebuilt-layout' and try again."
                )
            elif self.config.ocr_enabled and self.cloud_ocr is None:
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
        _reclassify_priced_assessment_pages(pages)
        _relink_invoice_continuation_pages(pages)

        # Apply the explicit upload role before selecting any extraction tier.
        # Otherwise unfamiliar report headings bypass the assessment readers;
        # relabelling them later in persistence is too late to recover evidence.
        if self.config.assessment_document:
            for page in pages:
                page.page_type = PageType.ENGINEER_ASSESSMENT
                page.group_key = None
                page.classification_signals.append("upload:engineer_assessment")

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
        group_invoice_index: list[tuple[list[PageAnalysis], int]] = []
        for key, grouped_pages in groups.items():
            role = "estimate" if key.startswith(PageType.ESTIMATE.value) else "invoice"
            try:
                invoice = self.parser.parse_group(source, grouped_pages, document_role=role)
            except Exception:
                # A single malformed invoice unit must not abort the rest of the document.
                continue
            analysis.invoices.append(invoice)
            group_invoice_index.append((grouped_pages, len(analysis.invoices) - 1))

        # Universal reader tier: retry groups that have no benchmarkable part row,
        # even when deterministic parsing found plausible labour/summary charges.
        # This is the adaptive path for Audatex/Type-7 variants where a changed
        # layout can otherwise look "successful" while omitting the real parts.
        # Calls remain bounded so one document cannot trigger unlimited LLM spend.
        text_calls = 0
        if self.text_extractor is not None:
            extract_text = getattr(self.text_extractor, "extract_from_text", None)
            if callable(extract_text):
                for grouped_pages, index in group_invoice_index:
                    if text_calls >= self.config.text_max_batches:
                        break
                    invoice = analysis.invoices[index]
                    if invoice.has_benchmarkable_part_lines() or not _group_has_readable_text(
                        grouped_pages
                    ):
                        continue
                    text_calls += 1
                    try:
                        text_result = extract_text(grouped_pages, role_hint=invoice.document_role)
                    except LLMProviderError as exc:
                        analysis.llm_failures.append(exc.code)
                        continue
                    if text_result is not None:
                        analysis.invoices[index] = merge_invoice_extractions(
                            invoice, text_result, include_vision_lines=True
                        )

        if self.vision_extractor is not None:
            assessment_pages = [
                page for page in pages if page.page_type == PageType.ENGINEER_ASSESSMENT
            ]
            assessment_batches: list[ExtractedEngineerAssessment] = []
            extract_assessment = getattr(
                self.vision_extractor, "extract_assessment", None
            )
            max_pages = max(1, getattr(self.vision_extractor, "max_pages", 8))
            vision_calls = 0
            if callable(extract_assessment):
                for batch_index in range(0, len(assessment_pages), max_pages):
                    if vision_calls >= self.config.vision_max_batches:
                        break
                    vision_calls += 1
                    try:
                        extracted_assessment = extract_assessment(
                            assessment_pages[batch_index : batch_index + max_pages]
                        )
                    except LLMProviderError as exc:
                        analysis.llm_failures.append(exc.code)
                        continue
                    if extracted_assessment is not None:
                        assessment_batches.append(extracted_assessment)

            grouped_numbers = {
                page.page_number for grouped_pages in groups.values() for page in grouped_pages
            }
            candidates = [
                page
                for page in pages
                if page.page_number not in grouped_numbers
                and page.page_type not in {
                    PageType.ENGINEER_ASSESSMENT,
                    PageType.BLANK,
                    PageType.SERVICE_HISTORY,
                }
                and (
                    page.extraction_method == "vision_required"
                    or page.page_type in {PageType.OTHER, PageType.PHOTO}
                )
            ]
            # Ungrouped pages have no reliable evidence that they belong to one
            # document. Process them individually to prevent cross-invoice mixing.
            for page in candidates:
                if vision_calls >= self.config.vision_max_batches:
                    break
                vision_calls += 1
                try:
                    extracted = self.vision_extractor.extract([page])
                except LLMProviderError as exc:
                    analysis.llm_failures.append(exc.code)
                    continue
                if extracted is not None:
                    analysis.invoices.append(extracted)
                    continue
                if not callable(extract_assessment):
                    continue
                try:
                    extracted_assessment = extract_assessment([page])
                except LLMProviderError as exc:
                    analysis.llm_failures.append(exc.code)
                    continue
                if extracted_assessment is not None:
                    assessment_batches.append(extracted_assessment)

            merged_assessment = _merge_assessment_batches(assessment_batches)
            if merged_assessment is not None:
                analysis.engineer_assessments.append(merged_assessment)
                assessment_numbers = set(merged_assessment.page_numbers)
                for page in pages:
                    if page.page_number in assessment_numbers:
                        page.page_type = PageType.ENGINEER_ASSESSMENT
                        page.group_key = None
                        page.classification_signals.append("vision:engineer_assessment")
                        page.classification_confidence = max(
                            page.classification_confidence,
                            merged_assessment.extraction_confidence,
                        )

        # Engineer assessments get the same universal reader fallback: only attempted
        # when nothing above (deterministic parsing happens later in document_processing,
        # vision above) has already produced an assessment.
        if self.text_extractor is not None and not analysis.engineer_assessments:
            extract_assessment_text = getattr(
                self.text_extractor, "extract_assessment_from_text", None
            )
            assessment_pages = [
                page for page in pages if page.page_type == PageType.ENGINEER_ASSESSMENT
            ]
            if callable(extract_assessment_text) and assessment_pages:
                max_pages = max(1, getattr(self.text_extractor, "max_pages", 8))
                text_assessment_batches: list[ExtractedEngineerAssessment] = []
                for batch_index in range(0, len(assessment_pages), max_pages):
                    if text_calls >= self.config.text_max_batches:
                        break
                    text_calls += 1
                    try:
                        extracted_assessment = extract_assessment_text(
                            assessment_pages[batch_index : batch_index + max_pages]
                        )
                    except LLMProviderError as exc:
                        analysis.llm_failures.append(exc.code)
                        continue
                    if extracted_assessment is not None:
                        text_assessment_batches.append(extracted_assessment)
                merged_text_assessment = _merge_assessment_batches(text_assessment_batches)
                if merged_text_assessment is not None:
                    analysis.engineer_assessments.append(merged_text_assessment)
                    assessment_numbers = set(merged_text_assessment.page_numbers)
                    for page in pages:
                        if page.page_number in assessment_numbers:
                            page.page_type = PageType.ENGINEER_ASSESSMENT
                            page.group_key = None
                            page.classification_signals.append("llm_text:engineer_assessment")
                            page.classification_confidence = max(
                                page.classification_confidence,
                                merged_text_assessment.extraction_confidence,
                            )

        # Every parsed invoice is retained, however weak its evidence, so no document
        # dead-ends: partially-benchmarkable invoices keep all their lines, and wholly
        # non-benchmarkable ones fall through to manual_review_reason below rather than
        # being discarded outright.
        has_engineer_assessment = bool(analysis.engineer_assessments) or any(
            page.page_type == PageType.ENGINEER_ASSESSMENT for page in pages
        )
        has_benchmarkable_invoice = any(
            invoice.has_benchmarkable_part_lines() for invoice in analysis.invoices
        )
        if not has_benchmarkable_invoice and not has_engineer_assessment:
            has_invoice_page = any(
                page.page_type in {PageType.INVOICE, PageType.ESTIMATE}
                for page in pages
            )
            analysis.manual_review_reason = (
                "Line-item information is not available. The invoice appears to be "
                "rolled up and cannot be benchmarked automatically."
                if has_invoice_page
                else "No benchmarkable invoice line items were detected in this document."
            )
        return analysis
