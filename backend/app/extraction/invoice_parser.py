from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from app.domain.money import as_decimal, money
from app.domain.normalisation import (
    normalise_description,
    normalise_unit,
    strip_scan_artifacts,
)
from app.extraction.schemas import (
    BoundingBox,
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
    PageAnalysis,
)
from app.llm.base import LLMProviderError
from app.llm.invoice_extraction import MultimodalInvoiceExtractor, merge_invoice_extractions

MONEY_PATTERN = r"(?:£\s*)?([0-9][0-9,]*\.\d{2})"


def _parse_date(value: str | None):
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _search_money(text: str, label: str) -> Decimal | None:
    patterns = [
        rf"{label}\s*[:£]?\s*([0-9][0-9,]*\.\d{{2}})",
        rf"{label}\s*\n\s*([0-9][0-9,]*\.\d{{2}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return money(match.group(1))
    return None


def _clean_cell(value: str | None) -> str:
    return strip_scan_artifacts(value or "")


def _column_index(headers: list[str], *labels: str) -> int | None:
    return next(
        (
            index
            for index, value in enumerate(headers)
            if value in labels or any(label in value for label in labels)
        ),
        None,
    )


def _guess_item_kind(section: str, description: str) -> str:
    section = section.lower()
    description_lower = description.lower()
    if "labour" in section:
        return "labour"
    # Generic invoice tables often put every row under a "Part" heading even
    # when the description clearly represents an operation. Preserve the
    # governed part/service boundary by recognising explicit operation wording
    # before falling back to the section label.
    if description_lower.startswith("fit "):
        return "labour"
    if description_lower.startswith(("carried out ", "carry out ")) and "service" in description_lower:
        return "service"
    if "mot" in section or "mot test" in description_lower:
        return "service"
    if "disposal" in description_lower or {
        "waste",
        "oil",
        "filter",
    }.issubset(description_lower.split()):
        return "disposal"
    if "paint" in description_lower:
        return "paint"
    if "service" in section:
        return "service"
    return "part" if "part" in section else "unknown"


def _token(value: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", value.lower().replace(",", ""))


def _target_tokens(value: str) -> list[str]:
    return [token for token in (_token(item) for item in value.split()) if token]


def _union_bbox(boxes: list[BoundingBox]) -> BoundingBox | None:
    if not boxes:
        return None
    return BoundingBox(
        x0=min(box.x0 for box in boxes),
        y0=min(box.y0 for box in boxes),
        x1=max(box.x1 for box in boxes),
        y1=max(box.y1 for box in boxes),
    )


def _matching_words(page: PageAnalysis, value: str, *, prefer_last: bool = False):
    wanted = _target_tokens(value)
    words = [word for word in page.words if _token(word.text)]
    if not wanted or not words:
        return []
    matches = []
    keys = [_token(word.text) for word in words]
    for index in range(len(keys) - len(wanted) + 1):
        if keys[index : index + len(wanted)] == wanted:
            matches.append(words[index : index + len(wanted)])
    if not matches:
        return []
    return matches[-1] if prefer_last else matches[0]


def _row_words(page: PageAnalysis, anchor: BoundingBox) -> list:
    anchor_centre = (anchor.y0 + anchor.y1) / 2
    anchor_height = max(anchor.y1 - anchor.y0, 1)
    return [
        word
        for word in page.words
        if abs(((word.bbox.y0 + word.bbox.y1) / 2) - anchor_centre)
        <= max(anchor_height, word.bbox.y1 - word.bbox.y0) * 1.15
    ]


def _region_in_words(words: list, value: str, *, prefer_last: bool = False):
    wanted = _target_tokens(value)
    filtered = [word for word in words if _token(word.text)]
    keys = [_token(word.text) for word in filtered]
    matches = []
    for index in range(len(keys) - len(wanted) + 1):
        if wanted and keys[index : index + len(wanted)] == wanted:
            matches.append(filtered[index : index + len(wanted)])
    if not matches:
        return None
    selected = matches[-1] if prefer_last else matches[0]
    return _union_bbox([word.bbox for word in selected])


def _line_source(
    page: PageAnalysis,
    *,
    description: str,
    quantity: str,
    unit_price: str,
    line_total: str,
    raw_text: str,
    extraction_method: str,
    confidence: float,
) -> FieldSource:
    description_words = _matching_words(page, description)
    description_bbox = _union_bbox([word.bbox for word in description_words])
    if description_bbox is None:
        return FieldSource(
            page_number=page.page_number,
            raw_text=raw_text,
            extraction_method=extraction_method,
            confidence=confidence,
            precision="approximate",
        )
    row_words = _row_words(page, description_bbox)
    regions = {"description": description_bbox}
    quantity_bbox = _region_in_words(row_words, quantity)
    unit_price_bbox = _region_in_words(row_words, unit_price)
    line_total_bbox = _region_in_words(row_words, line_total, prefer_last=True)
    if quantity_bbox:
        regions["quantity"] = quantity_bbox
    if unit_price_bbox:
        regions["unit_price"] = unit_price_bbox
    if line_total_bbox:
        regions["line_total"] = line_total_bbox
    row_bbox = _union_bbox([word.bbox for word in row_words]) or description_bbox
    regions["row"] = row_bbox
    return FieldSource(
        page_number=page.page_number,
        bbox=row_bbox,
        regions=regions,
        raw_text=raw_text,
        extraction_method=extraction_method,
        confidence=confidence,
        precision="exact" if line_total_bbox else "approximate",
    )


def _group_words_by_line(page: PageAnalysis) -> list[list]:
    groups: list[list] = []
    for word in sorted(page.words, key=lambda item: (item.bbox.y0, item.bbox.x0)):
        centre = (word.bbox.y0 + word.bbox.y1) / 2
        target = next(
            (
                group
                for group in reversed(groups[-4:])
                if abs(
                    centre - sum((item.bbox.y0 + item.bbox.y1) / 2 for item in group) / len(group)
                )
                <= max(word.bbox.y1 - word.bbox.y0, 1) * 0.8
            ),
            None,
        )
        if target is None:
            groups.append([word])
        else:
            target.append(word)
    return [sorted(group, key=lambda item: item.bbox.x0) for group in groups]


def _total_source(
    pages: list[PageAnalysis],
    labels: tuple[str, ...],
    value: Decimal | None,
) -> FieldSource | None:
    if value is None:
        return None
    value_token = _token(f"{value:.2f}")
    for page in reversed(pages):
        for words in reversed(_group_words_by_line(page)):
            keys = [_token(word.text) for word in words]
            joined = " ".join(keys)
            if not any(all(token in joined for token in _target_tokens(label)) for label in labels):
                continue
            value_words = [word for word in words if _token(word.text) == value_token]
            if not value_words:
                continue
            value_bbox = _union_bbox([word.bbox for word in value_words[-1:]])
            return FieldSource(
                page_number=page.page_number,
                bbox=value_bbox,
                regions={"value": value_bbox} if value_bbox else {},
                raw_text=" ".join(word.text for word in words),
                extraction_method=page.extraction_method,
                confidence=page.extraction_confidence,
                precision="exact",
            )
    return None


def _vehicle_row(text: str) -> dict[str, str | int | None]:
    """Read the values beneath the stable vehicle-detail header in visual order."""

    match = None
    for line in text.splitlines():
        cleaned = strip_scan_artifacts(line)
        candidate = re.match(
            r"^([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3})\s+(.+?)\s+"
            r"([A-Z0-9]{12,20})\s+([0-9]{3,5})\s+([0-9,]{3,})$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if candidate:
            match = candidate
            break
    if not match:
        for line in text.splitlines():
            cleaned = strip_scan_artifacts(line)
            compact = re.match(
                r"^([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3})\s*[-–—]\s*([A-Z][A-Z0-9 .'-]+)$",
                cleaned,
                flags=re.IGNORECASE,
            )
            if compact:
                make_model = strip_scan_artifacts(compact.group(2))
                make, _, model = make_model.partition(" ")
                return {
                    "registration": strip_scan_artifacts(compact.group(1)).upper(),
                    "vehicle_make": make or None,
                    "vehicle_model": model or None,
                    "vin": None,
                    "engine_cc": None,
                    "mileage": None,
                }
        return {}
    make_model = strip_scan_artifacts(match.group(2))
    make, _, model = make_model.partition(" ")
    return {
        "registration": strip_scan_artifacts(match.group(1)).upper(),
        "vehicle_make": make or None,
        "vehicle_model": model or None,
        "vin": match.group(3),
        "engine_cc": int(match.group(4)),
        "mileage": int(match.group(5).replace(",", "")),
    }


def _line_tax(
    line_total: Decimal | None, vat_rate: Decimal, applies: bool
) -> tuple[Decimal, Decimal]:
    net = line_total or Decimal("0")
    vat = money(net * vat_rate / Decimal("100")) if applies else Decimal("0.00")
    vat = vat or Decimal("0.00")
    return vat, money(net + vat) or Decimal("0.00")


class InvoiceParser:
    def __init__(self, vision_extractor: MultimodalInvoiceExtractor | None = None) -> None:
        self.vision_extractor = vision_extractor

    def parse_group(
        self,
        pdf_path: Path,
        pages: list[PageAnalysis],
        *,
        document_role: str = "invoice",
    ) -> ExtractedInvoice:
        raw_text = "\n".join(page.text for page in pages)
        page_numbers = [page.page_number for page in pages]
        extraction_method = (
            "native_table" if all(page.extraction_method == "native" for page in pages) else "ocr"
        )
        lines: list[ExtractedLine] = []
        layout_text_parts: list[str] = []

        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_info in pages:
                    pdf_page = pdf.pages[page_info.page_number - 1]
                    layout_text_parts.append(pdf_page.extract_text(layout=True) or page_info.text)
                    if page_info.extraction_method == "native":
                        lines.extend(self._native_table_lines(pdf_page, page_info, len(lines) + 1))
                    else:
                        lines.extend(self._ocr_lines(page_info, len(lines) + 1))
        except Exception:
            if self.vision_extractor is None:
                raise
            layout_text_parts.extend(page.text for page in pages)

        layout_text = "\n".join(layout_text_parts)
        totals = self._totals(layout_text + "\n" + raw_text, pages)
        if totals.non_vatable is not None and not any(
            line.item_kind == "service" and "mot" in line.normalised_description for line in lines
        ):
            source_page = pages[-1]
            mot_words = _matching_words(source_page, "MOT")
            mot_bbox = _union_bbox([word.bbox for word in mot_words])
            lines.append(
                ExtractedLine(
                    sequence_no=len(lines) + 1,
                    raw_description="MOT test",
                    normalised_description="mot test",
                    item_kind="service",
                    quantity=Decimal("1"),
                    unit="test",
                    unit_price_net=totals.non_vatable,
                    line_total_net=totals.non_vatable,
                    vat_rate=Decimal("0"),
                    vat_amount=Decimal("0.00"),
                    gross_amount=totals.non_vatable,
                    vat_applicable=False,
                    source=FieldSource(
                        page_number=source_page.page_number,
                        bbox=mot_bbox,
                        regions={"row": mot_bbox, "description": mot_bbox} if mot_bbox else {},
                        raw_text="MOT",
                        extraction_method=source_page.extraction_method,
                        confidence=source_page.extraction_confidence,
                        precision="approximate",
                    ),
                )
            )

        header = self._header(layout_text + "\n" + raw_text)
        confidence = sum(page.extraction_confidence for page in pages) / len(pages)
        deterministic = ExtractedInvoice(
            header=header,
            totals=totals,
            line_items=lines,
            page_numbers=page_numbers,
            document_role=document_role,
            extraction_method=extraction_method,
            extraction_confidence=confidence,
        )
        usable_lines = [
            line
            for line in deterministic.line_items
            if line.line_total_net is not None and line.line_total_net > 0
        ]
        stated_subtotal = deterministic.totals.subtotal_net
        extracted_subtotal = sum(
            (
                line.line_total_net
                for line in usable_lines
                if line.vat_applicable and line.line_total_net is not None
            ),
            Decimal("0"),
        )
        recover_lines = not usable_lines or (
            stated_subtotal is not None
            and abs(extracted_subtotal - stated_subtotal) > Decimal("0.05")
        )
        if self.vision_extractor is None or (
            not recover_lines
            and deterministic.header.invoice_date is not None
            and deterministic.header.supplier_name
            and (
                deterministic.totals.subtotal_net is not None
                or deterministic.totals.total_gross is not None
            )
        ):
            return deterministic
        try:
            vision = self.vision_extractor.extract(pages, role_hint=document_role)
        except LLMProviderError:
            return deterministic
        return merge_invoice_extractions(
            deterministic,
            vision,
            include_vision_lines=recover_lines,
        )

    def _native_table_lines(self, pdf_page, page: PageAnalysis, start: int) -> list[ExtractedLine]:
        return self._table_lines(
            pdf_page.extract_tables() or [],
            page,
            start,
            extraction_method="native_table",
            confidence=0.98,
        )

    def _table_lines(
        self,
        tables: list[list[list[str | None]]],
        page: PageAnalysis,
        start: int,
        *,
        extraction_method: str,
        confidence: float,
    ) -> list[ExtractedLine]:
        output: list[ExtractedLine] = []
        sequence = start
        for table in tables:
            if not table:
                continue
            header_cells = [_clean_cell(cell) for cell in table[0]]
            normalised_headers = [re.sub(r"\s+", " ", cell.lower()).strip() for cell in header_cells]
            header = " ".join(cell for cell in header_cells if cell)
            header_lower = header.lower()

            description_index = _column_index(
                normalised_headers, "description", "operation", "item"
            )
            quantity_index = _column_index(normalised_headers, "qty", "quantity")
            unit_price_index = _column_index(
                normalised_headers, "unit price", "unit cost", "rate", "price"
            )
            line_total_index = _column_index(
                normalised_headers, "line total", "subtotal", "sub total", "amount"
            )
            if line_total_index is None:
                line_total_index = _column_index(normalised_headers, "total")
            part_number_index = _column_index(
                normalised_headers, "part number", "part no", "part #"
            )
            generic_parts_table = (
                description_index is not None
                and quantity_index is not None
                and line_total_index is not None
            )
            governed_table = "sub total" in header_lower and any(
                key in header_lower for key in ("parts", "labour", "service")
            )
            if not generic_parts_table and not governed_table:
                continue
            section = "labour" if "labour" in header_lower else "parts"
            for row in table[1:]:
                cells = [_clean_cell(cell) for cell in row]
                if not cells or not cells[0]:
                    continue
                if generic_parts_table:
                    required_index = max(description_index, quantity_index, line_total_index)
                    if len(cells) <= required_index:
                        continue
                    description = cells[description_index]
                    quantity = cells[quantity_index]
                    line_total = cells[line_total_index]
                    unit_price = (
                        cells[unit_price_index]
                        if unit_price_index is not None and unit_price_index < len(cells)
                        else ""
                    )
                    part_number = (
                        cells[part_number_index]
                        if part_number_index is not None and part_number_index < len(cells)
                        else ""
                    )
                elif section == "parts" and len(cells) >= 6:
                    description, part_number, quantity, unit_price, _, line_total = cells[:6]
                elif section == "labour" and len(cells) >= 5:
                    description, quantity, unit_price, _, line_total = cells[:5]
                    part_number = ""
                else:
                    continue
                try:
                    qty = as_decimal(quantity)
                    unit_price_value = money(unit_price)
                    line_total_value = money(line_total)
                except ValueError:
                    continue
                if not description or line_total_value is None:
                    continue
                if unit_price_value is None and qty and qty > 0:
                    unit_price_value = line_total_value / qty
                output.append(
                    ExtractedLine(
                        sequence_no=sequence,
                        raw_description=description,
                        normalised_description=normalise_description(description),
                        item_kind=_guess_item_kind(section, description),
                        part_number=part_number or None,
                        quantity=qty,
                        unit=normalise_unit(None, item_kind=_guess_item_kind(section, description)),
                        unit_price_net=unit_price_value,
                        line_total_net=line_total_value,
                        vat_rate=Decimal("20"),
                        vat_amount=_line_tax(line_total_value, Decimal("20"), True)[0],
                        gross_amount=_line_tax(line_total_value, Decimal("20"), True)[1],
                        vat_applicable=True,
                        source=_line_source(
                            page,
                            description=description,
                            quantity=quantity,
                            unit_price=unit_price,
                            line_total=line_total,
                            raw_text=" | ".join(cells),
                            extraction_method=extraction_method,
                            confidence=confidence,
                        ),
                    )
                )
                sequence += 1
        return output

    def _ocr_lines(self, page: PageAnalysis, start: int) -> list[ExtractedLine]:
        table_lines = self._table_lines(
            page.tables,
            page,
            start,
            extraction_method="ocr",
            confidence=page.extraction_confidence,
        )
        if table_lines:
            return table_lines

        output: list[ExtractedLine] = []
        current_section = "unknown"
        sequence = start
        for raw_line in page.text.splitlines():
            line = strip_scan_artifacts(raw_line)
            lower = line.lower()
            if not line:
                continue
            if lower in {"labour", "parts", "service", "work performed"}:
                current_section = lower
                continue
            amounts = re.findall(MONEY_PATTERN, line)
            if not amounts or not re.search(r"[A-Za-z]{3}", line):
                continue
            if any(token in lower for token in ("subtotal", "total", "vat", "balance", "payment")):
                continue
            line_total = money(amounts[-1])
            unit_price = money(amounts[-2]) if len(amounts) > 1 else line_total
            description = re.sub(MONEY_PATTERN, " ", line)
            description = re.sub(r"\b\d+(?:\.\d+)?\b", " ", description)
            description = strip_scan_artifacts(description)
            if len(description) < 3:
                continue
            quantity = Decimal("1")
            if unit_price and line_total and unit_price > 0:
                candidate = line_total / unit_price
                if candidate <= Decimal("50"):
                    quantity = candidate
            output.append(
                ExtractedLine(
                    sequence_no=sequence,
                    raw_description=description,
                    normalised_description=normalise_description(description),
                    item_kind=_guess_item_kind(current_section, description),
                    quantity=quantity,
                    unit=normalise_unit(
                        None, item_kind=_guess_item_kind(current_section, description)
                    ),
                    unit_price_net=unit_price,
                    line_total_net=line_total,
                    vat_rate=Decimal("0") if "mot" in lower else Decimal("20"),
                    vat_amount=_line_tax(
                        line_total,
                        Decimal("0") if "mot" in lower else Decimal("20"),
                        "mot" not in lower,
                    )[0],
                    gross_amount=_line_tax(
                        line_total,
                        Decimal("0") if "mot" in lower else Decimal("20"),
                        "mot" not in lower,
                    )[1],
                    vat_applicable="mot" not in lower,
                    source=_line_source(
                        page,
                        description=description,
                        quantity=str(quantity),
                        unit_price=str(unit_price or ""),
                        line_total=str(line_total or ""),
                        raw_text=raw_line,
                        extraction_method="ocr",
                        confidence=page.extraction_confidence,
                    ),
                )
            )
            sequence += 1
        return output

    def _header(self, text: str) -> InvoiceHeader:
        compact = strip_scan_artifacts(text)
        vehicle = _vehicle_row(text)
        invoice_number = None
        for pattern in (
            r"Invoice\s*(?:No\.?|Number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]{2,})",
            r"SALES INVOICE.*?Invoice No\s*[:#]?\s*([A-Z0-9/-]+)",
        ):
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if match and match.group(1).lower() not in {"date", "name"}:
                invoice_number = match.group(1)
                break
        date_match = re.search(
            r"(?:Invoice Date|Date of Work|Date)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            compact,
            flags=re.IGNORECASE,
        )
        registration_match = re.search(
            r"(?<!VAT\s)(?:Registration|Reg\.?\s*No\.?)\s*:?\s*([A-Z]{1,3}[0-9]{1,3}\s?[A-Z]{1,3})",
            compact,
            flags=re.IGNORECASE,
        )
        mileage_match = re.search(r"Mileage\s*:?\s*([0-9,]{3,})", compact, flags=re.IGNORECASE)
        vat_number_match = re.search(
            r"VAT\s*(?:Reg(?:istration)?\s*(?:No\.)?|Number)\s*[:.]?\s*([0-9 ]{8,15})",
            compact,
            flags=re.IGNORECASE,
        )
        supplier = None
        for line in text.splitlines():
            cleaned = strip_scan_artifacts(line)
            if re.search(r"(clinic|garage|autosolutions|mot centre|mini service)", cleaned, re.I):
                supplier = cleaned
                break
        customer_match = re.search(
            r"(?:Clinic|Garage|Autosolutions|MOT Centre)\s+(.+?)\s+Invoice\s+[A-Z0-9/-]+",
            compact,
            flags=re.IGNORECASE,
        )
        return InvoiceHeader(
            invoice_number=invoice_number,
            invoice_date=_parse_date(date_match.group(1) if date_match else None),
            supplier_name=supplier,
            supplier_vat_number=vat_number_match.group(1).strip() if vat_number_match else None,
            customer_name=strip_scan_artifacts(customer_match.group(1)) if customer_match else None,
            registration=vehicle.get("registration")
            or (registration_match.group(1).strip() if registration_match else None),
            vin=vehicle.get("vin"),
            vehicle_make=vehicle.get("vehicle_make"),
            vehicle_model=vehicle.get("vehicle_model"),
            engine_cc=vehicle.get("engine_cc"),
            mileage=vehicle.get("mileage")
            or (int(mileage_match.group(1).replace(",", "")) if mileage_match else None),
        )

    def _totals(self, text: str, pages: list[PageAnalysis]) -> InvoiceTotals:
        subtotal = _search_money(text, r"Sub\s*Total")
        vat_amount = _search_money(text, r"VAT\s*(?:\([^)]*\))?")
        non_vatable = _search_money(text, r"MOT")
        total_matches = re.findall(
            rf"(?<!Sub)\bTotal\b\s*[:£]?\s*{MONEY_PATTERN}", text, flags=re.IGNORECASE
        )
        total = money(total_matches[-1]) if total_matches else None
        vat_rate_match = re.search(r"VAT\s*\((\d+(?:\.\d+)?)%\)", text, re.I)
        labour_net = _search_money(text, r"Labour")
        parts_net = _search_money(text, r"Parts")
        if subtotal is None and (labour_net is not None or parts_net is not None):
            subtotal = (labour_net or Decimal("0")) + (parts_net or Decimal("0"))
        totals = InvoiceTotals(
            labour_net=labour_net,
            parts_net=parts_net,
            subtotal_net=subtotal,
            vat_rate=as_decimal(vat_rate_match.group(1)) if vat_rate_match else Decimal("20"),
            vat_amount=vat_amount,
            non_vatable=non_vatable,
            total_gross=total,
        )
        candidates = {
            "labour_net": _total_source(pages, ("labour",), labour_net),
            "parts_net": _total_source(pages, ("parts",), parts_net),
            "subtotal_net": _total_source(pages, ("sub total", "subtotal"), subtotal),
            "vat_amount": _total_source(pages, ("vat",), vat_amount),
            "non_vatable": _total_source(pages, ("mot",), non_vatable),
            "total_gross": _total_source(pages, ("total", "invoice total"), total),
        }
        totals.sources = {key: source for key, source in candidates.items() if source is not None}
        return totals
