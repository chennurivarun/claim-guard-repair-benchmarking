from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PageType(StrEnum):
    ENGINEER_ASSESSMENT = "engineer_assessment"
    INVOICE = "invoice"
    ESTIMATE = "estimate_or_order"
    CREDIT_NOTE = "credit_note"
    VEHICLE_DOCUMENT = "vehicle_document"
    SERVICE_HISTORY = "service_history"
    MOT = "mot"
    PHOTO = "photo"
    BLANK = "blank"
    OTHER = "other"


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class OCRWord(BaseModel):
    text: str
    confidence: float = Field(ge=0, le=1)
    bbox: BoundingBox


class FieldSource(BaseModel):
    page_number: int
    bbox: BoundingBox | None = None
    regions: dict[str, BoundingBox] = Field(default_factory=dict)
    raw_text: str | None = None
    extraction_method: str
    confidence: float = Field(ge=0, le=1)
    precision: Literal["exact", "approximate"] = "exact"


class ExtractedLine(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    sequence_no: int
    raw_description: str
    normalised_description: str
    item_kind: str = "unknown"
    part_number: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price_net: Decimal | None = None
    line_total_net: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    vat_applicable: bool = True
    derived_net: bool = False
    source: FieldSource


class InvoiceTotals(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    labour_net: Decimal | None = None
    parts_net: Decimal | None = None
    subtotal_net: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    non_vatable: Decimal | None = None
    total_gross: Decimal | None = None
    sources: dict[str, FieldSource] = Field(default_factory=dict)


class InvoiceHeader(BaseModel):
    invoice_number: str | None = None
    invoice_date: date | None = None
    supplier_name: str | None = None
    supplier_vat_number: str | None = None
    customer_name: str | None = None
    registration: str | None = None
    vin: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_variant: str | None = None
    engine_cc: int | None = None
    mileage: int | None = None
    currency: str = "GBP"


class ExtractedInvoice(BaseModel):
    header: InvoiceHeader
    totals: InvoiceTotals
    line_items: list[ExtractedLine] = Field(default_factory=list)
    page_numbers: list[int]
    document_role: str = "invoice"
    extraction_method: str
    extraction_confidence: float = Field(ge=0, le=1)


class PageAnalysis(BaseModel):
    page_number: int
    width: float
    height: float
    rotation: int
    native_character_count: int
    positioned_word_count: int
    image_count: int
    extraction_method: str
    extraction_confidence: float = Field(ge=0, le=1)
    text: str
    page_type: PageType
    classification_confidence: float = Field(ge=0, le=1)
    classification_signals: list[str] = Field(default_factory=list)
    group_key: str | None = None
    rendered_image_path: Path | None = None
    words: list[OCRWord] = Field(default_factory=list)


class DocumentAnalysis(BaseModel):
    source_path: Path
    sha256: str
    page_count: int
    pages: list[PageAnalysis]
    invoices: list[ExtractedInvoice] = Field(default_factory=list)


class MathFinding(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    finding_type: str
    status: str
    expected: Decimal | None = None
    found: Decimal | None = None
    difference: Decimal | None = None
    tolerance: Decimal | None = None
    severity: str
    line_sequence_no: int | None = None
    explanation: str
