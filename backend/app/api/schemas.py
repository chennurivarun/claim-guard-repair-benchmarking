from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SAMPLE_DATA_DIR = Path(__file__).resolve().parents[3] / "sample-data"


class ClaimPartyInput(BaseModel):
    role: str
    name: str | None = None
    insurer_name: str | None = None
    policy_number: str | None = None
    address: str | None = None


class ClaimVehicleInput(BaseModel):
    role: str
    registration: str | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    manufacture_year: int | None = Field(default=None, ge=1886, le=2200)
    official_vehicle_class: str | None = Field(default=None, max_length=12)
    bodywork_code: str | None = Field(default=None, max_length=8)
    market_segment: str | None = Field(default=None, max_length=120)
    classification_source: str | None = Field(default=None, max_length=240)
    policy_number: str | None = None
    insurer_name: str | None = None
    damage_description: str | None = None

    @model_validator(mode="after")
    def classification_has_source(self):
        values = (self.official_vehicle_class, self.bodywork_code, self.market_segment)
        if any(values) and not (self.classification_source or "").strip():
            raise ValueError("Vehicle classification requires a source")
        return self


class VehicleClassificationRequest(BaseModel):
    registration: str = Field(min_length=1, max_length=32)
    official_vehicle_class: str | None = Field(default=None, max_length=12)
    bodywork_code: str | None = Field(default=None, max_length=8)
    market_segment: str | None = Field(default=None, max_length=120)
    classification_source: str = Field(min_length=3, max_length=240)
    verified_by: str = Field(min_length=1, max_length=160)


class ClaimCreateRequest(BaseModel):
    case_reference: str
    claim_number: str
    paying_insurer_name: str | None = None
    claiming_insurer_name: str | None = None
    third_party_name: str | None = None
    paying_policy_number: str | None = None
    claiming_policy_number: str | None = None
    accident_at: datetime | None = None
    accident_location: str | None = None
    accident_description: str | None = None
    damage_description: str | None = None
    created_by: str = "pilot.handler"
    notes: str | None = None
    parties: list[ClaimPartyInput] = Field(default_factory=list)
    vehicles: list[ClaimVehicleInput] = Field(default_factory=list)


class LiabilityDecisionRequest(BaseModel):
    status: str
    confirmed_by: str
    rationale: str
    split_liability_percentage: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def split_requires_percentage(self):
        if self.status.replace(" ", "_").upper() == "SPLIT_LIABILITY":
            if self.split_liability_percentage is None:
                raise ValueError("Split liability requires a percentage.")
        return self


class InvoiceLineCorrectionRequest(BaseModel):
    actor: str
    reason: str
    raw_description: str | None = None
    item_kind: str | None = None
    part_number: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price_net: Decimal | None = None
    line_total_net: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_applicable: bool | None = None


class ExtractionDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "undo"]
    actor: str = Field(min_length=1, max_length=160)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def rejection_requires_reason(self):
        if self.decision == "rejected" and not (self.reason or "").strip():
            raise ValueError("Rejecting an extraction requires a reason.")
        return self


class PageCorrectionRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=3, max_length=1000)
    page_type: str | None = None
    group_id: str | None = Field(default=None, max_length=120)
    rotation: int | None = None

    @model_validator(mode="after")
    def correction_is_explicit(self):
        correction_fields = {"page_type", "group_id", "rotation"} & self.model_fields_set
        if not correction_fields:
            raise ValueError(
                "Provide a page classification, group identifier or rotation correction."
            )
        if "page_type" in correction_fields and self.page_type is None:
            raise ValueError("Page classification cannot be null.")
        if "rotation" in correction_fields and self.rotation not in {0, 90, 180, 270}:
            raise ValueError("Rotation must be 0, 90, 180 or 270 degrees.")
        return self


class SettlementLineInput(BaseModel):
    line_item_id: str
    agreed_amount_net: Decimal = Field(ge=0)
    agreed_vat: Decimal | None = Field(default=None, ge=0)


class SettlementCreateRequest(BaseModel):
    agreed_amount_net: Decimal = Field(ge=0)
    agreed_vat: Decimal | None = Field(default=None, ge=0)
    agreed_at: datetime
    recorded_by: str
    note: str | None = None
    negotiation_reference: str | None = None
    lines: list[SettlementLineInput] = Field(default_factory=list)


class BundleComponentInput(BaseModel):
    ontology_item_id: str = Field(min_length=1)
    allocated_net: Decimal | None = Field(default=None, ge=0)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = None

    @model_validator(mode="after")
    def allocation_or_quantity_is_explicit(self):
        if self.allocated_net is None and self.quantity is None:
            raise ValueError("Each bundle component needs an explicit net allocation or quantity.")
        return self


class MappingDecisionRequest(BaseModel):
    actor: str = Field(min_length=1)
    ontology_item_id: str | None = None
    decision: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    bundle_components: list[BundleComponentInput] = Field(default_factory=list)


class ResearchTriggerRequest(BaseModel):
    requested_by: str
    note: str | None = None


class ResearchApprovalRequest(BaseModel):
    approved_by: str
    canonical_name: str
    item_type: str
    category: str
    unit: str
    price_net: Decimal = Field(gt=0)
    source_url_or_ref: str
    vehicle_applicability: str | None = None
    part_number: str | None = None
    rationale: str


class ManualResearchEvidenceRequest(BaseModel):
    source_uri: str
    title: str
    captured_at: datetime | None = None
    minimal_excerpt: str | None = None
    source_record_id: str | None = None
    price_net: Decimal | None = Field(default=None, ge=0)
    original_price: Decimal | None = Field(default=None, ge=0)
    currency: str = "GBP"
    vat_basis: str = "net"
    unit: str | None = None
    part_number: str | None = None
    fitment: dict[str, Any] | None = None
    quality_tier: str | None = None
    condition: str | None = None
    shipping: Decimal | None = Field(default=None, ge=0)
    stock_status: str | None = None


class ManualResearchSuggestionRequest(BaseModel):
    canonical_name: str
    item_type: str
    category: str
    unit: str
    price_net: Decimal = Field(ge=0)
    date_checked: date
    rationale: str
    vat_basis: str = "net"
    price_scope: str = "unit"
    part_number: str | None = None
    vehicle_compatibility: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    currency: str = "GBP"
    region: str = "UK"
    quality_tier: str | None = None


class ManualResearchRequest(BaseModel):
    requested_by: str
    query_text: str
    suggestion: ManualResearchSuggestionRequest
    evidence: list[ManualResearchEvidenceRequest] = Field(min_length=1)
    source_allow_list_version: str = "pilot-manual-sources-v1"


class ResearchItemApprovalRequest(BaseModel):
    approved_by: str
    reviewer_note: str | None = None


class SeedImportRequest(BaseModel):
    ontology_path: str = str(SAMPLE_DATA_DIR / "ontology_seed.xlsx")
    historical_path: str = str(SAMPLE_DATA_DIR / "historical_claims_seed.xlsx")
    adapter_key: str = "excel_seed"


class ReviewDecisionRequest(BaseModel):
    actor: str
    approved: bool = True
    rationale: str
    challenge_price_net: Decimal | None = Field(default=None, ge=0)


class FinaliseCaseRequest(BaseModel):
    finalised_by: str
    note: str | None = None


class ReprocessCaseRequest(BaseModel):
    actor: str = Field(min_length=1)
    ontology_version_id: str | None = None
