from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

    @property
    def benchmarkable(self) -> bool:
        """Return whether this single line carries priced part evidence for benchmarking."""

        return (
            bool(self.raw_description.strip())
            and (self.item_kind.casefold() == "part" or bool(self.part_number))
            and self.line_total_net is not None
            and self.line_total_net > 0
        )


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

    @model_validator(mode="after")
    def reject_implausible_vat(self) -> InvoiceTotals:
        """A VAT amount is only meaningful beside the totals it was charged on.

        Extraction sometimes drops a grand total into the VAT field; a VAT
        figure with no other monetary total, or one exceeding its own base,
        is discarded rather than displayed as fact.
        """

        if self.vat_amount is None:
            return self
        bases = [
            value
            for value in (self.subtotal_net, self.total_gross)
            if value is not None and value > 0
        ]
        other_totals = [
            value
            for value in (
                self.labour_net,
                self.parts_net,
                self.subtotal_net,
                self.total_gross,
            )
            if value is not None and value > 0
        ]
        if not other_totals or any(self.vat_amount > base for base in bases):
            self.vat_amount = None
        return self


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

    @field_validator("invoice_number", mode="before")
    @classmethod
    def reject_generic_invoice_number(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        token = " ".join(re.sub(r"[^a-z0-9]+", " ", cleaned.casefold()).split())
        if token in {
            "",
            "-",
            "claim",
            "claim no",
            "claim number",
            "invoice",
            "invoice claim",
            "invoice no",
            "invoice number",
            "inv",
            "inv no",
            "inv number",
            "n/a",
            "na",
            "none",
            "repair invoice",
            "tax invoice",
            "unknown",
        }:
            return None
        # A claim reference is never an invoice number; models sometimes place
        # "Claim Reference: 2025/ABC/12345"-style values in this field.
        if token.startswith(("claim ", "claim:")) or token.startswith("claim reference"):
            return None
        return cleaned

    @field_validator("supplier_name", mode="before")
    @classmethod
    def reject_generic_supplier_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        token = " ".join(re.sub(r"[^a-z0-9]+", " ", cleaned.casefold()).split())
        if token in {
            "",
            "-",
            "garage",
            "invoice",
            "n/a",
            "na",
            "none",
            "repair invoice",
            "repairer",
            "supplier",
            "unknown",
            "unknown repairer",
        }:
            return None
        return cleaned


class ExtractedInvoice(BaseModel):
    header: InvoiceHeader
    totals: InvoiceTotals
    line_items: list[ExtractedLine] = Field(default_factory=list)
    page_numbers: list[int]
    document_role: str = "invoice"
    extraction_method: str
    extraction_confidence: float = Field(ge=0, le=1)

    def has_benchmarkable_part_lines(self) -> bool:
        """Return whether the invoice contains priced part evidence for benchmarking."""

        return any(line.benchmarkable for line in self.line_items)


class EngineerAssessmentFields(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    assessment_number: str | None = None
    claim_reference: str | None = None
    policy_number: str | None = None
    created_date: date | None = None
    incident_date: date | None = None
    authorisation_status: str | None = None
    registration: str | None = None
    vin: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_variant: str | None = None
    mileage: int | None = None
    pre_accident_condition: str | None = None
    impact_severity: str | None = None
    roadworthiness: str | None = None
    damage_areas: list[str] | None = None
    labour_rate: Decimal | None = None
    paint_rate: Decimal | None = None
    labour_net: Decimal | None = None
    paint_net: Decimal | None = None
    parts_net: Decimal | None = None
    extras_net: Decimal | None = None
    subtotal_net: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_total: Decimal | None = None
    gross_total: Decimal | None = None


class ExtractedAssessmentOperation(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    sequence_no: int
    category: str
    code: str | None = None
    part_number: str | None = None
    description: str
    work_units: Decimal | None = None
    hours: Decimal | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    page_number: int


class ExtractedEngineerAssessment(BaseModel):
    fields: EngineerAssessmentFields
    operations: list[ExtractedAssessmentOperation] = Field(default_factory=list)
    page_numbers: list[int]
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
    tables: list[list[list[str]]] = Field(default_factory=list)


class DocumentAnalysis(BaseModel):
    source_path: Path
    sha256: str
    page_count: int
    pages: list[PageAnalysis]
    invoices: list[ExtractedInvoice] = Field(default_factory=list)
    engineer_assessments: list[ExtractedEngineerAssessment] = Field(default_factory=list)
    manual_review_reason: str | None = None
    llm_failures: list[str] = Field(default_factory=list)


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
