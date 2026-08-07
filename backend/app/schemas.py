"""Pydantic v2 response contracts for the ClaimGuard API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.enums import (
    ApprovalStatus,
    AuditActorType,
    CaseStatus,
    ChallengeStatus,
    CheckStatus,
    ClaimPartyRole,
    ClaimVehicleRole,
    ComparisonStatus,
    ConfidenceLevel,
    ConfigKind,
    ConfigStatus,
    ConsistencyFindingStatus,
    DocumentRole,
    ExtractionMethod,
    ImportStatus,
    InvoiceDocumentRole,
    LiabilityEvidenceType,
    LiabilityGateStatus,
    LiabilityStatus,
    LineItemKind,
    MappingDecision,
    MappingStatus,
    OntologyItemStatus,
    OntologyVersionStatus,
    PageType,
    PriceObservationKind,
    PriceScope,
    PriceVatBasis,
    ResearchStatus,
    ReviewAction,
    ReviewStatus,
    ReviewTaskStatus,
    RunStatus,
    RunType,
    SettlementStatus,
    Severity,
    SourceProviderType,
    UploadStatus,
)

MoneyText = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{2}$")]
QuantityText = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{4}$")]
RateText = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{4}$")]
WeightText = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{6}$")]


class ORMResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=False)


class TimestampedResponse(ORMResponse):
    id: str
    created_at: datetime
    updated_at: datetime


class CreatedResponse(ORMResponse):
    id: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    database: str
    ai_provider: str
    ai_model: str
    ai_status: str
    ocr_provider: str
    ocr_status: str
    timestamp: datetime


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None
    detail: dict[str, Any] | None = None


class PaginationMeta(BaseModel):
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    meta: PaginationMeta


class ClaimPartyResponse(TimestampedResponse):
    claim_context_id: str
    party_role: ClaimPartyRole
    name: str | None = None
    insurer_name: str | None = None
    policy_number: str | None = None
    address: str | None = None
    contact_json: dict[str, Any] | None = None
    driving_role: str | None = None
    source_json: dict[str, Any] | None = None
    review_status: ReviewStatus


class ClaimVehicleResponse(TimestampedResponse):
    claim_context_id: str
    vehicle_role: ClaimVehicleRole
    driver_party_id: str | None = None
    registration: str | None = None
    vin: str | None = None
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    manufacture_year: int | None = None
    policy_number: str | None = None
    insurer_name: str | None = None
    damage_description: str | None = None
    source_json: dict[str, Any] | None = None
    review_status: ReviewStatus


class LiabilityAssessmentResponse(CreatedResponse):
    claim_context_id: str
    processing_run_id: str | None = None
    supersedes_id: str | None = None
    ai_suggested_status: LiabilityStatus | None = None
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    ai_rationale: str | None = None
    ai_suggestion_json: dict[str, Any] | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    human_status: LiabilityStatus | None = None
    human_correction_json: dict[str, Any] | None = None
    human_rationale: str | None = None
    human_confirmed: bool
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    effective_status: LiabilityStatus
    split_liability_percentage: RateText | None = None
    evidence_snapshot_json: list[dict[str, Any]] | None = None


class LiabilityEvidenceResponse(TimestampedResponse):
    claim_context_id: str
    document_id: str | None = None
    page_id: str | None = None
    evidence_type: LiabilityEvidenceType
    title: str
    description: str | None = None
    source_uri_or_path: str | None = None
    content_hash: str | None = None
    captured_at: datetime | None = None
    extracted_facts_json: dict[str, Any] | None = None
    supports_status: LiabilityStatus | None = None
    approval_status: ApprovalStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class ClaimConsistencyFindingResponse(TimestampedResponse):
    claim_context_id: str
    finding_code: str
    severity: Severity
    status: ConsistencyFindingStatus
    field_name: str | None = None
    expected_value: str | None = None
    observed_value: str | None = None
    source_entity_type: str | None = None
    source_entity_id: str | None = None
    explanation: str
    resolution_note: str | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class ClaimContextResponse(TimestampedResponse):
    case_id: str
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
    liability_gate_status: LiabilityGateStatus
    human_confirmed: bool
    human_confirmed_by: str | None = None
    human_confirmed_at: datetime | None = None
    parties: list[ClaimPartyResponse] = Field(default_factory=list)
    vehicles: list[ClaimVehicleResponse] = Field(default_factory=list)
    liability_assessments: list[LiabilityAssessmentResponse] = Field(default_factory=list)
    evidence: list[LiabilityEvidenceResponse] = Field(default_factory=list)
    consistency_findings: list[ClaimConsistencyFindingResponse] = Field(default_factory=list)


class CaseResponse(TimestampedResponse):
    case_reference: str
    status: CaseStatus
    created_by: str
    current_processing_run_id: str | None = None
    finalised_at: datetime | None = None
    notes: str | None = None


class CaseDetailResponse(CaseResponse):
    claim_context: ClaimContextResponse | None = None


class SourceProviderResponse(TimestampedResponse):
    name: str
    provider_type: SourceProviderType
    adapter_name: str
    enabled: bool
    priority: int
    licence_status: str | None = None
    permitted_use: str | None = None
    requires_human_approval: bool
    configuration_json: dict[str, Any] | None = None
    last_healthcheck_at: datetime | None = None


class DocumentPageResponse(TimestampedResponse):
    document_id: str
    page_number: int
    width: float | None = None
    height: float | None = None
    rotation: int
    native_char_count: int | None = None
    image_coverage: float | None = None
    extraction_method: ExtractionMethod
    page_type: PageType
    classification_confidence: float | None = Field(default=None, ge=0, le=1)
    group_id: str | None = None
    raw_text_path: str | None = None
    rendered_image_path: str | None = None
    page_hash: str | None = None
    review_status: ReviewStatus
    classification_model_id: str | None = None
    classification_prompt_version: str | None = None


class DocumentResponse(CreatedResponse):
    case_id: str
    document_role: DocumentRole
    original_filename: str
    storage_path: str
    sha256: str
    mime_type: str
    file_size: int
    page_count: int | None = None
    upload_status: UploadStatus
    source_provider_id: str | None = None
    metadata_json: dict[str, Any] | None = None


class DocumentDetailResponse(DocumentResponse):
    pages: list[DocumentPageResponse] = Field(default_factory=list)


class VehicleResponse(TimestampedResponse):
    case_id: str | None = None
    registration: str | None = None
    registration_redacted: str | None = None
    vin: str | None = None
    vin_redacted: str | None = None
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    manufacture_year: int | None = None
    registration_date: date | None = None
    engine_code: str | None = None
    engine_cc: int | None = None
    fuel_type: str | None = None
    mileage: int | None = None
    source: str | None = None
    verification_status: ReviewStatus


class InvoiceLineItemResponse(TimestampedResponse):
    invoice_id: str
    sequence_no: int
    bundle_parent_line_id: str | None = None
    raw_description: str
    normalised_description: str | None = None
    raw_category: str | None = None
    item_kind: LineItemKind
    part_number: str | None = None
    quantity: QuantityText | None = None
    unit: str | None = None
    price_scope: PriceScope
    unit_price_net: MoneyText | None = None
    discount_net: MoneyText | None = None
    line_total_net: MoneyText | None = None
    vat_rate: RateText | None = None
    vat_amount: MoneyText | None = None
    line_gross: MoneyText | None = None
    vat_applicable: bool | None = None
    derived_net: bool
    raw_quantity_text: str | None = None
    raw_unit_price_text: str | None = None
    raw_line_total_text: str | None = None
    source_page_id: str | None = None
    source_bbox_json: list[float] | None = None
    source_regions_json: dict[str, list[float]] | None = None
    source_raw_text: str | None = None
    extraction_method: ExtractionMethod
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    user_corrected: bool
    status: ReviewStatus


class MathFindingResponse(CreatedResponse):
    invoice_id: str
    line_item_id: str | None = None
    check_code: str
    status: CheckStatus
    severity: Severity
    expected_value: str | None = None
    observed_value: str | None = None
    difference: str | None = None
    tolerance: str | None = None
    explanation: str
    is_challengeable: bool
    source_values_json: dict[str, Any] | None = None


class InvoiceResponse(TimestampedResponse):
    case_id: str
    document_id: str
    document_group_id: str
    document_role: InvoiceDocumentRole
    invoice_number: str | None = None
    invoice_date: date | None = None
    supplier_name: str | None = None
    supplier_address: str | None = None
    supplier_vat_number: str | None = None
    customer_name: str | None = None
    customer_reference: str | None = None
    claim_reference: str | None = None
    currency: str
    vehicle_id: str | None = None
    parts_net: MoneyText | None = None
    labour_net: MoneyText | None = None
    other_net: MoneyText | None = None
    subtotal_net: MoneyText | None = None
    vat_rate: RateText | None = None
    vat_total: MoneyText | None = None
    non_vat_total: MoneyText | None = None
    gross_total: MoneyText | None = None
    extraction_method: ExtractionMethod
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: ReviewStatus
    page_numbers_json: list[int] | None = None


class InvoiceDetailResponse(InvoiceResponse):
    vehicle: VehicleResponse | None = None
    line_items: list[InvoiceLineItemResponse] = Field(default_factory=list)
    math_findings: list[MathFindingResponse] = Field(default_factory=list)


class SourceImportResponse(CreatedResponse):
    provider_id: str
    document_id: str | None = None
    dataset_version: str | None = None
    row_count: int
    accepted_count: int
    rejected_count: int
    quarantined_count: int
    validation_report_json: dict[str, Any] | None = None
    status: ImportStatus


class OntologyVersionResponse(CreatedResponse):
    sequence_number: int
    label: str
    parent_id: str | None = None
    status: OntologyVersionStatus
    created_by: str
    change_summary: str | None = None
    source_import_id: str | None = None
    published_at: datetime | None = None


class OntologySynonymResponse(CreatedResponse):
    ontology_item_id: str
    synonym: str
    normalised_synonym: str
    source_type: str | None = None
    source_reference: str | None = None
    approval_status: ApprovalStatus
    created_in_version_id: str


class VehicleApplicabilityResponse(CreatedResponse):
    ontology_item_id: str
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine_code: str | None = None
    engine_cc_from: int | None = None
    engine_cc_to: int | None = None
    fuel_type: str | None = None
    vin_pattern: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_reference: str | None = None
    approval_status: ApprovalStatus


class PriceObservationResponse(CreatedResponse):
    ontology_item_id: str | None = None
    price_net: MoneyText
    original_price: MoneyText | None = None
    currency: str
    vat_basis: PriceVatBasis
    unit: str
    price_scope: PriceScope
    source_provider_id: str | None = None
    source_import_id: str | None = None
    source_type: str
    source_record_id: str | None = None
    source_url_or_ref: str | None = None
    observed_at: datetime | None = None
    effective_from: date
    effective_to: date | None = None
    region: str
    quality_tier: str | None = None
    condition: str | None = None
    shipping_included: bool | None = None
    approval_status: ApprovalStatus
    observation_kind: PriceObservationKind
    evidence_id: str | None = None
    created_in_version_id: str | None = None


class OntologyItemResponse(TimestampedResponse):
    canonical_code: str
    canonical_name: str
    item_type: LineItemKind
    category: str
    subcategory: str | None = None
    unit: str
    manufacturer: str | None = None
    manufacturer_part_number: str | None = None
    quality_tier: str | None = None
    part_grade: str | None = None
    description: str | None = None
    typical_labour_hours: QuantityText | None = None
    standard_labour_rate: MoneyText | None = None
    paint_material_allowance: MoneyText | None = None
    repair_or_replace_rule: str | None = None
    region: str
    reference_price_net: MoneyText | None = None
    price_vat_basis: PriceVatBasis
    currency: str
    price_source: str | None = None
    source_url_or_ref: str | None = None
    effective_date: date | None = None
    status: OntologyItemStatus
    approval_status: ApprovalStatus
    confidence_level: ConfidenceLevel
    created_by: str
    created_in_version_id: str
    retired_in_version_id: str | None = None
    superseded_by_id: str | None = None


class OntologyItemDetailResponse(OntologyItemResponse):
    synonyms: list[OntologySynonymResponse] = Field(default_factory=list)
    vehicle_applicability: list[VehicleApplicabilityResponse] = Field(default_factory=list)
    price_observations: list[PriceObservationResponse] = Field(default_factory=list)


class HistoricalObservationResponse(TimestampedResponse):
    source_import_id: str | None = None
    source_document_id: str | None = None
    source_invoice_id: str | None = None
    source_line_item_id: str | None = None
    source_record_id: str | None = None
    claim_reference: str | None = None
    observation_type: InvoiceDocumentRole
    invoice_date: date | None = None
    ontology_item_id: str | None = None
    part_number: str | None = None
    raw_description: str
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_variant: str | None = None
    vehicle_year: int | None = None
    repair_operation: str | None = None
    workshop_category: str | None = None
    region: str
    part_grade: str | None = None
    quantity: QuantityText | None = None
    unit: str | None = None
    price_scope: PriceScope
    unit_price_net: MoneyText | None = None
    line_total_net: MoneyText | None = None
    approved_amount_net: MoneyText | None = None
    settled_amount_net: MoneyText | None = None
    labour_hours: QuantityText | None = None
    labour_rate: MoneyText | None = None
    discount_applied: MoneyText | None = None
    vat_basis: PriceVatBasis
    settlement_status: SettlementStatus
    comparability_metadata_json: dict[str, Any] | None = None
    approval_status: ApprovalStatus


class ConfigVersionResponse(CreatedResponse):
    kind: ConfigKind
    version: str
    yaml_text: str
    config_hash: str
    status: ConfigStatus
    created_by: str
    activated_at: datetime | None = None
    supersedes_id: str | None = None
    change_summary: str | None = None


class RegulatoryRuleResponse(TimestampedResponse):
    config_version_id: str | None = None
    rule_name: str
    jurisdiction: str
    effective_from: date
    effective_to: date | None = None
    value: str
    value_type: str
    source_reference: str
    approval_status: ApprovalStatus


class ProcessingRunResponse(ORMResponse):
    id: str
    case_id: str
    run_type: RunType
    application_version: str
    configuration_hash: str
    ontology_version_id: str | None = None
    benchmark_policy_version: str
    policy_config_version_id: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    extraction_version: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    status: RunStatus
    error_summary: str | None = None
    metrics_json: dict[str, Any] | None = None
    source_import_versions_json: list[dict[str, Any]] | None = None


class MappingRunResponse(ORMResponse):
    id: str
    processing_run_id: str
    ontology_version_id: str
    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str
    started_at: datetime
    completed_at: datetime | None = None
    status: RunStatus


class OntologyMappingResponse(TimestampedResponse):
    mapping_run_id: str
    invoice_line_item_id: str
    selected_ontology_item_id: str | None = None
    decision: MappingDecision
    retrieval_similarity: float | None = Field(default=None, ge=0, le=1)
    llm_confidence: float | None = Field(default=None, ge=0, le=1)
    combined_confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = None
    alternative_candidates_json: list[dict[str, Any]] | None = None
    flags_json: dict[str, Any] | None = None
    ai_output_json: dict[str, Any] | None = None
    is_bundled: bool
    bundle_components_json: list[dict[str, Any]] | None = None
    final_status: MappingStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


class ComparisonComparableResponse(CreatedResponse):
    price_comparison_id: str
    price_observation_id: str | None = None
    historical_observation_id: str | None = None
    comparable_class: str
    weight: WeightText
    original_line_net: MoneyText | None = None
    normalised_line_net: MoneyText | None = None
    adjustments_json: dict[str, Any]
    stale_data_warning: bool
    eligibility_reason: str | None = None


class PriceComparisonResponse(TimestampedResponse):
    processing_run_id: str
    invoice_line_item_id: str
    ontology_mapping_id: str | None = None
    invoice_unit_net: MoneyText | None = None
    invoice_line_net: MoneyText
    ontology_unit_net: MoneyText | None = None
    ontology_line_net: MoneyText | None = None
    historical_median_unit_net: MoneyText | None = None
    historical_line_net: MoneyText | None = None
    historical_p25_net: MoneyText | None = None
    historical_p75_net: MoneyText | None = None
    historical_lowest_recent_net: MoneyText | None = None
    market_median_unit_net: MoneyText | None = None
    market_line_net: MoneyText | None = None
    n_comparables: int
    selected_benchmark_source: str | None = None
    benchmark_unit_net: MoneyText | None = None
    benchmark_line_net: MoneyText | None = None
    benchmark_policy_version: str
    ontology_version_id: str | None = None
    benchmark_formula_json: dict[str, Any]
    eligibility_flags_json: dict[str, Any]
    status: ComparisonStatus
    comparables: list[ComparisonComparableResponse] = Field(default_factory=list)


class ChallengeResultResponse(TimestampedResponse):
    processing_run_id: str
    price_comparison_id: str | None = None
    invoice_id: str | None = None
    challenge_net: MoneyText
    challenge_vat: MoneyText
    challenge_gross: MoneyText
    challenge_percentage: RateText
    evidence_strength_score: int = Field(ge=0, le=100)
    evidence_label: str
    recommended_payable_net: MoneyText
    narrative: str | None = None
    score_breakdown_json: dict[str, Any]
    findings_json: dict[str, Any]
    status: ChallengeStatus
    reviewer_approved: bool
    approved_by: str | None = None
    approved_at: datetime | None = None


class ReviewDecisionResponse(CreatedResponse):
    review_task_id: str
    actor_id: str
    action: ReviewAction
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    reason_code: str | None = None
    note: str | None = None


class ReviewTaskResponse(TimestampedResponse):
    case_id: str
    entity_type: str
    entity_id: str
    reason_code: str
    priority: int
    status: ReviewTaskStatus
    assigned_to: str | None = None
    resolved_at: datetime | None = None
    resolution_summary: str | None = None
    decisions: list[ReviewDecisionResponse] = Field(default_factory=list)


class ResearchItemResponse(TimestampedResponse):
    research_task_id: str
    provisional_ontology_item_id: str | None = None
    suggested_canonical_name: str
    suggested_item_type: LineItemKind
    suggested_category: str
    suggested_unit: str
    suggested_part_number: str | None = None
    vehicle_compatibility_json: dict[str, Any] | None = None
    suggested_price_net: MoneyText
    vat_basis: PriceVatBasis
    source_urls_json: list[str]
    date_checked: date
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str
    raw_suggestion_json: dict[str, Any] | None = None
    status: ResearchStatus
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    reviewer_note: str | None = None


class ExternalEvidenceResponse(CreatedResponse):
    research_task_id: str
    provider_id: str | None = None
    source_record_id: str | None = None
    source_uri: str
    captured_at: datetime
    title: str
    minimal_excerpt: str | None = None
    content_hash: str
    part_number: str | None = None
    fitment_json: dict[str, Any] | None = None
    price_net: MoneyText | None = None
    original_price: MoneyText | None = None
    currency: str
    vat_basis: PriceVatBasis
    unit: str | None = None
    quality_tier: str | None = None
    condition: str | None = None
    shipping: MoneyText | None = None
    stock_status: str | None = None
    validation_flags_json: dict[str, Any] | None = None
    approval_status: ApprovalStatus


class ResearchTaskResponse(TimestampedResponse):
    case_id: str
    invoice_line_item_id: str
    requested_by: str
    initiated_automatically: bool
    query_text: str
    source_allow_list_version: str
    status: ResearchStatus
    model_id: str | None = None
    prompt_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_summary: str | None = None
    suggestion: ResearchItemResponse | None = None
    evidence: list[ExternalEvidenceResponse] = Field(default_factory=list)


class SettlementResponse(TimestampedResponse):
    invoice_id: str
    line_item_id: str | None = None
    status: SettlementStatus
    agreed_amount_net: MoneyText
    agreed_vat: MoneyText | None = None
    agreed_amount_gross: MoneyText | None = None
    agreed_at: datetime
    recorded_by: str
    note: str | None = None
    negotiation_reference: str | None = None
    historical_observation_id: str | None = None


class AuditEventResponse(ORMResponse):
    id: str
    case_id: str | None = None
    processing_run_id: str | None = None
    actor_type: AuditActorType
    actor_id: str
    event_type: str
    entity_type: str
    entity_id: str | None = None
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    event_payload_json: dict[str, Any]
    correlation_id: str | None = None
    created_at: datetime
    previous_event_hash: str | None = None
    event_hash: str | None = None


# Names used by the build-ready PRD and frontend contract.
InvoiceUnitResponse = InvoiceResponse
LineItemResponse = InvoiceLineItemResponse
CalculationCheckResponse = MathFindingResponse
MappingResponse = OntologyMappingResponse


__all__ = [name for name in globals() if name.endswith("Response")]
