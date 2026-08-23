"""ClaimGuard v1.4 relational domain model.

The schema is deliberately normalised around immutable source evidence and
versioned derived results. Exact monetary values use :class:`DecimalString`, so
SQLite never stores money in binary floating-point columns.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.db_types import (
    MoneyString,
    QuantityString,
    RateString,
    UTCDateTime,
    WeightString,
    utc_now,
)
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
    DocumentKind,
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


def new_uuid() -> str:
    return str(uuid4())


def enum_type(enum_class: type[Any], name: str) -> SAEnum:
    """Create a constrained string enum that persists each member's value."""

    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class Case(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (Index("ix_cases_status_created_at", "status", "created_at"),)

    case_reference: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[CaseStatus] = mapped_column(
        enum_type(CaseStatus, "case_status"),
        nullable=False,
        default=CaseStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    current_processing_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("processing_runs.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    finalised_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents: Mapped[list[Document]] = relationship(
        back_populates="case", cascade="all, delete-orphan", passive_deletes=True
    )
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="case", cascade="all, delete-orphan", passive_deletes=True
    )
    claim_context: Mapped[ClaimContext | None] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    processing_runs: Mapped[list[ProcessingRun]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="ProcessingRun.case_id",
    )


class ClaimContext(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Claim facts that must be human-confirmed before price validation."""

    __tablename__ = "claim_contexts"
    __table_args__ = (
        UniqueConstraint("case_id", name="uq_claim_contexts_case_id"),
        Index("ix_claim_contexts_claim_number", "claim_number"),
        Index("ix_claim_contexts_gate_status", "liability_gate_status"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    claim_number: Mapped[str] = mapped_column(String(120), nullable=False)
    paying_insurer_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    claiming_insurer_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    third_party_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    paying_policy_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claiming_policy_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accident_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    accident_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    accident_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    damage_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    liability_gate_status: Mapped[LiabilityGateStatus] = mapped_column(
        enum_type(LiabilityGateStatus, "liability_gate_status"),
        nullable=False,
        default=LiabilityGateStatus.NOT_STARTED,
    )
    human_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    human_confirmed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    human_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    case: Mapped[Case] = relationship(back_populates="claim_context")
    parties: Mapped[list[ClaimParty]] = relationship(
        back_populates="claim_context",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    vehicles: Mapped[list[ClaimVehicle]] = relationship(
        back_populates="claim_context",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    liability_assessments: Mapped[list[LiabilityAssessment]] = relationship(
        back_populates="claim_context",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    evidence: Mapped[list[LiabilityEvidence]] = relationship(
        back_populates="claim_context",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    consistency_findings: Mapped[list[ClaimConsistencyFinding]] = relationship(
        back_populates="claim_context",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClaimParty(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_parties"
    __table_args__ = (Index("ix_claim_parties_context_role", "claim_context_id", "party_role"),)

    claim_context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim_contexts.id", ondelete="CASCADE"), nullable=False
    )
    party_role: Mapped[ClaimPartyRole] = mapped_column(
        enum_type(ClaimPartyRole, "claim_party_role"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    insurer_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    driving_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "claim_party_review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )

    claim_context: Mapped[ClaimContext] = relationship(back_populates="parties")


class ClaimVehicle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_vehicles"
    __table_args__ = (
        Index("ix_claim_vehicles_context_role", "claim_context_id", "vehicle_role"),
        Index("ix_claim_vehicles_registration", "registration"),
    )

    claim_context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim_contexts.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_role: Mapped[ClaimVehicleRole] = mapped_column(
        enum_type(ClaimVehicleRole, "claim_vehicle_role"), nullable=False
    )
    driver_party_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("claim_parties.id", ondelete="SET NULL"), nullable=True
    )
    registration: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    make: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    manufacture_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    official_vehicle_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bodywork_code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    market_segment: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classification_source: Mapped[str | None] = mapped_column(String(240), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    insurer_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    damage_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "claim_vehicle_review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )

    claim_context: Mapped[ClaimContext] = relationship(back_populates="vehicles")


class LiabilityAssessment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Preserves an AI suggestion separately from the human liability decision."""

    __tablename__ = "liability_assessments"
    __table_args__ = (
        CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ai_confidence_range",
        ),
        CheckConstraint(
            "human_confirmed = 0 OR human_status IS NOT NULL",
            name="confirmed_requires_human_status",
        ),
        Index("ix_liability_assessments_context_created", "claim_context_id", "created_at"),
    )

    claim_context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim_contexts.id", ondelete="CASCADE"), nullable=False
    )
    processing_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("liability_assessments.id", ondelete="SET NULL"), nullable=True
    )
    ai_suggested_status: Mapped[LiabilityStatus | None] = mapped_column(
        enum_type(LiabilityStatus, "liability_ai_status"), nullable=True
    )
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_suggestion_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    human_status: Mapped[LiabilityStatus | None] = mapped_column(
        enum_type(LiabilityStatus, "liability_human_status"), nullable=True
    )
    human_correction_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    human_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    effective_status: Mapped[LiabilityStatus] = mapped_column(
        enum_type(LiabilityStatus, "liability_effective_status"),
        nullable=False,
        default=LiabilityStatus.HUMAN_REVIEW_REQUIRED,
    )
    split_liability_percentage: Mapped[str | None] = mapped_column(RateString, nullable=True)
    evidence_snapshot_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    claim_context: Mapped[ClaimContext] = relationship(back_populates="liability_assessments")


class LiabilityEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Non-invoice evidence used for liability; invoices are excluded by enum design."""

    __tablename__ = "liability_evidence"
    __table_args__ = (
        Index("ix_liability_evidence_context_type", "claim_context_id", "evidence_type"),
        Index("ix_liability_evidence_content_hash", "content_hash"),
    )

    claim_context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim_contexts.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    page_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True
    )
    evidence_type: Mapped[LiabilityEvidenceType] = mapped_column(
        enum_type(LiabilityEvidenceType, "liability_evidence_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_uri_or_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    extracted_facts_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supports_status: Mapped[LiabilityStatus | None] = mapped_column(
        enum_type(LiabilityStatus, "liability_evidence_supports_status"), nullable=True
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "liability_evidence_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    claim_context: Mapped[ClaimContext] = relationship(back_populates="evidence")


class ClaimConsistencyFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claim_consistency_findings"
    __table_args__ = (
        Index("ix_claim_consistency_context_status", "claim_context_id", "status"),
        Index("ix_claim_consistency_code", "finding_code"),
    )

    claim_context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("claim_contexts.id", ondelete="CASCADE"), nullable=False
    )
    finding_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        enum_type(Severity, "claim_consistency_severity"),
        nullable=False,
        default=Severity.WARNING,
    )
    status: Mapped[ConsistencyFindingStatus] = mapped_column(
        enum_type(ConsistencyFindingStatus, "claim_consistency_status"),
        nullable=False,
        default=ConsistencyFindingStatus.OPEN,
    )
    field_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    expected_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    claim_context: Mapped[ClaimContext] = relationship(back_populates="consistency_findings")


class SourceProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_providers"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="priority_non_negative"),
        Index("ix_source_providers_type_enabled", "provider_type", "enabled"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    provider_type: Mapped[SourceProviderType] = mapped_column(
        enum_type(SourceProviderType, "source_provider_type"), nullable=False
    )
    adapter_name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    licence_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    permitted_use: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    configuration_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_healthcheck_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Document(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("case_id", "sha256", name="uq_documents_case_sha256"),
        CheckConstraint("file_size >= 0", name="file_size_non_negative"),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="page_count_non_negative"),
        Index("ix_documents_case_role", "case_id", "document_role"),
        Index("ix_documents_sha256", "sha256"),
        Index("ix_documents_upload_status", "upload_status"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    document_role: Mapped[DocumentRole] = mapped_column(
        enum_type(DocumentRole, "document_role"),
        nullable=False,
        default=DocumentRole.CURRENT,
    )
    document_kind: Mapped[DocumentKind] = mapped_column(
        enum_type(DocumentKind, "document_kind"),
        nullable=False,
        default=DocumentKind.UNKNOWN,
    )
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False, default="application/pdf")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_status: Mapped[UploadStatus] = mapped_column(
        enum_type(UploadStatus, "upload_status"),
        nullable=False,
        default=UploadStatus.PENDING,
    )
    source_provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_providers.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review_briefing_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    case: Mapped[Case] = relationship(back_populates="documents")
    pages: Mapped[list[DocumentPage]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentPage.page_number",
    )
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    engineer_assessment: Mapped[EngineerAssessment | None] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_pages_number"),
        CheckConstraint("page_number >= 1", name="page_number_positive"),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        CheckConstraint("rotation IN (0, 90, 180, 270)", name="valid_rotation"),
        CheckConstraint(
            "classification_confidence IS NULL OR "
            "(classification_confidence >= 0 AND classification_confidence <= 1)",
            name="classification_confidence_range",
        ),
        CheckConstraint(
            "image_coverage IS NULL OR (image_coverage >= 0 AND image_coverage <= 1)",
            name="image_coverage_range",
        ),
        Index("ix_document_pages_document_type", "document_id", "page_type"),
        Index("ix_document_pages_group_id", "group_id"),
        Index("ix_document_pages_page_hash", "page_hash"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    native_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        enum_type(ExtractionMethod, "page_extraction_method"),
        nullable=False,
        default=ExtractionMethod.PENDING,
    )
    page_type: Mapped[PageType] = mapped_column(
        enum_type(PageType, "page_type"), nullable=False, default=PageType.OTHER
    )
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "document_page_review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )
    classification_model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    classification_prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)

    document: Mapped[Document] = relationship(back_populates="pages")


class EngineerAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured, non-invoice evidence extracted from an engineer report."""

    __tablename__ = "engineer_assessments"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_engineer_assessment_document"),
        Index("ix_engineer_assessment_case_claim", "case_id", "claim_reference"),
        Index("ix_engineer_assessment_registration", "registration"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    paired_invoice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    pair_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unpaired")
    pair_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    pair_reasons_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    assessment_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    claim_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    policy_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    incident_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    authorisation_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    registration: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_make: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    vehicle_variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pre_accident_condition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    impact_severity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    roadworthiness: Mapped[str | None] = mapped_column(String(120), nullable=True)
    damage_areas_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    labour_rate: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    paint_rate: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    labour_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    paint_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    parts_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    extras_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    subtotal_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    vat_rate: Mapped[str | None] = mapped_column(RateString, nullable=True)
    vat_total: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    gross_total: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "engineer_assessment_review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )
    extraction_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    document: Mapped[Document] = relationship(back_populates="engineer_assessment")
    paired_invoice: Mapped[Invoice | None] = relationship(foreign_keys=[paired_invoice_id])
    operations: Mapped[list[AssessmentOperation]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan", passive_deletes=True,
        order_by="AssessmentOperation.sequence_no",
    )


class AssessmentOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assessment_operations"
    __table_args__ = (
        UniqueConstraint("assessment_id", "sequence_no", name="uq_assessment_operation_sequence"),
        Index("ix_assessment_operation_assessment", "assessment_id"),
    )

    assessment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("engineer_assessments.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    operation_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_description: Mapped[str] = mapped_column(Text, nullable=False)
    work_units: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    hours: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    quantity: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    unit_price_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    total_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    source_page_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True
    )
    source_bbox_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    assessment: Mapped[EngineerAssessment] = relationship(back_populates="operations")
    source_page: Mapped[DocumentPage | None] = relationship()
    variances: Mapped[list[AssessmentInvoiceVariance]] = relationship(
        back_populates="assessment_operation", cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AssessmentInvoiceVariance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assessment_invoice_variances"
    __table_args__ = (
        UniqueConstraint(
            "assessment_operation_id", "invoice_line_item_id",
            name="uq_assessment_invoice_variance_pair",
        ),
        Index("ix_assessment_invoice_variance_invoice", "invoice_id"),
    )

    assessment_operation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assessment_operations.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    invoice_line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=False
    )
    matching_method: Mapped[str] = mapped_column(String(40), nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    engineer_amount: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    invoice_amount: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    difference_amount: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    difference_percentage: Mapped[str | None] = mapped_column(RateString, nullable=True)
    threshold_status: Mapped[str] = mapped_column(String(40), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    assessment_operation: Mapped[AssessmentOperation] = relationship(back_populates="variances")
    invoice: Mapped[Invoice] = relationship(foreign_keys=[invoice_id])
    invoice_line_item: Mapped[InvoiceLineItem] = relationship(foreign_keys=[invoice_line_item_id])


class Vehicle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_registration", "registration"),
        Index("ix_vehicles_vin", "vin"),
        CheckConstraint(
            "manufacture_year IS NULL OR (manufacture_year >= 1886 AND manufacture_year <= 2200)",
            name="manufacture_year_range",
        ),
        CheckConstraint("mileage IS NULL OR mileage >= 0", name="mileage_non_negative"),
    )

    case_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    registration: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registration_redacted: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vin: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vin_redacted: Mapped[str | None] = mapped_column(String(64), nullable=True)
    make: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    manufacture_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    official_vehicle_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bodywork_code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    market_segment: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classification_source: Mapped[str | None] = mapped_column(String(240), nullable=True)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    engine_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    engine_cc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    insurance_group_range: Mapped[str | None] = mapped_column(String(32), nullable=True)
    insurance_group_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    insurance_group_source: Mapped[str | None] = mapped_column(String(240), nullable=True)
    insurance_group_match_status: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verification_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "vehicle_verification_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )


class VehicleCategoryLookup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vehicle_category_lookup"
    __table_args__ = (
        UniqueConstraint(
            "normalised_make",
            "normalised_model",
            name="uq_vehicle_category_make_model",
        ),
        Index(
            "ix_vehicle_category_lookup_normalised",
            "normalised_make",
            "normalised_model",
        ),
    )

    make: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    normalised_make: Mapped[str] = mapped_column(String(120), nullable=False)
    normalised_model: Mapped[str] = mapped_column(String(160), nullable=False)
    group_range: Mapped[str] = mapped_column(String(32), nullable=False)
    group_category: Mapped[str] = mapped_column(String(80), nullable=False)
    body_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    aliases_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(240), nullable=False)


invoice_page_links = Table(
    "invoice_page_links",
    Base.metadata,
    Column(
        "invoice_id",
        String(36),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "page_id",
        String(36),
        ForeignKey("document_pages.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("page_order", Integer, nullable=False),
    CheckConstraint("page_order >= 1", name="page_order_positive"),
    UniqueConstraint("invoice_id", "page_order", name="uq_invoice_page_links_order"),
)


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("document_id", "document_group_id", name="uq_invoices_document_group"),
        CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="extraction_confidence_range",
        ),
        Index("ix_invoices_case_date", "case_id", "invoice_date"),
        Index("ix_invoices_number", "invoice_number"),
        Index("ix_invoices_document_role", "document_role"),
        Index("ix_invoices_review_status", "review_status"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_group_id: Mapped[str] = mapped_column(String(120), nullable=False)
    document_role: Mapped[InvoiceDocumentRole] = mapped_column(
        enum_type(InvoiceDocumentRole, "invoice_document_role"),
        nullable=False,
        default=InvoiceDocumentRole.INVOICE,
    )
    invoice_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supplier_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_vat_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    customer_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    claim_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")
    vehicle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    parts_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    labour_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    other_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    subtotal_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    vat_rate: Mapped[str | None] = mapped_column(RateString, nullable=True)
    vat_total: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    non_vat_total: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    gross_total: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        enum_type(ExtractionMethod, "invoice_extraction_method"),
        nullable=False,
        default=ExtractionMethod.PENDING,
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "invoice_review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )
    page_numbers_json: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    extraction_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    case: Mapped[Case] = relationship(back_populates="invoices")
    document: Mapped[Document] = relationship(back_populates="invoices")
    vehicle: Mapped[Vehicle | None] = relationship()
    pages: Mapped[list[DocumentPage]] = relationship(secondary=invoice_page_links)
    line_items: Mapped[list[InvoiceLineItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvoiceLineItem.sequence_no",
    )
    math_findings: Mapped[list[MathFinding]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", passive_deletes=True
    )
    settlements: Mapped[list[Settlement]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", passive_deletes=True
    )


class InvoiceLineItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (
        UniqueConstraint("invoice_id", "sequence_no", name="uq_invoice_lines_sequence"),
        CheckConstraint("sequence_no >= 1", name="sequence_positive"),
        CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="extraction_confidence_range",
        ),
        Index("ix_invoice_lines_invoice_kind", "invoice_id", "item_kind"),
        Index("ix_invoice_lines_part_number", "part_number"),
        Index("ix_invoice_lines_normalised_description", "normalised_description"),
        Index("ix_invoice_lines_source_page", "source_page_id"),
    )

    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    bundle_parent_line_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="SET NULL"), nullable=True
    )
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    normalised_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    item_kind: Mapped[LineItemKind] = mapped_column(
        enum_type(LineItemKind, "invoice_line_item_kind"),
        nullable=False,
        default=LineItemKind.UNKNOWN,
    )
    part_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quantity: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price_scope: Mapped[PriceScope] = mapped_column(
        enum_type(PriceScope, "invoice_line_price_scope"),
        nullable=False,
        default=PriceScope.LINE_TOTAL,
    )
    unit_price_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    discount_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    line_total_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    vat_rate: Mapped[str | None] = mapped_column(RateString, nullable=True)
    vat_amount: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    line_gross: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    vat_applicable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    derived_net: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_quantity_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_unit_price_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_line_total_text: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_page_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_pages.id", ondelete="SET NULL"), nullable=True
    )
    source_bbox_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    source_regions_json: Mapped[dict[str, list[float]] | None] = mapped_column(JSON, nullable=True)
    source_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        enum_type(ExtractionMethod, "line_extraction_method"),
        nullable=False,
        default=ExtractionMethod.PENDING,
    )
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, "invoice_line_review_status"),
        nullable=False,
        default=ReviewStatus.PENDING,
    )

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")
    source_page: Mapped[DocumentPage | None] = relationship()
    math_findings: Mapped[list[MathFinding]] = relationship(
        back_populates="line_item", passive_deletes=True
    )


class MathFinding(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "math_findings"
    __table_args__ = (
        Index("ix_math_findings_invoice_status", "invoice_id", "status"),
        Index("ix_math_findings_check_code", "check_code"),
        Index("ix_math_findings_line_item", "line_item_id"),
    )

    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=True
    )
    check_code: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[CheckStatus] = mapped_column(
        enum_type(CheckStatus, "math_finding_status"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        enum_type(Severity, "math_finding_severity"),
        nullable=False,
        default=Severity.WARNING,
    )
    expected_value: Mapped[str | None] = mapped_column(String(160), nullable=True)
    observed_value: Mapped[str | None] = mapped_column(String(160), nullable=True)
    difference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tolerance: Mapped[str | None] = mapped_column(String(80), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    is_challengeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_values_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="math_findings")
    line_item: Mapped[InvoiceLineItem | None] = relationship(back_populates="math_findings")


class SourceImport(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "source_imports"
    __table_args__ = (
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        CheckConstraint("accepted_count >= 0", name="accepted_count_non_negative"),
        CheckConstraint("rejected_count >= 0", name="rejected_count_non_negative"),
        CheckConstraint("quarantined_count >= 0", name="quarantined_count_non_negative"),
        Index("ix_source_imports_provider_status", "provider_id", "status"),
        Index("ix_source_imports_dataset_version", "dataset_version"),
    )

    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_providers.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    dataset_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        enum_type(ImportStatus, "source_import_status"),
        nullable=False,
        default=ImportStatus.PENDING,
    )


class OntologyVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ontology_versions"
    __table_args__ = (Index("ix_ontology_versions_status_created", "status", "created_at"),)

    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[OntologyVersionStatus] = mapped_column(
        enum_type(OntologyVersionStatus, "ontology_version_status"),
        nullable=False,
        default=OntologyVersionStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_import_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_imports.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    parent: Mapped[OntologyVersion | None] = relationship(remote_side="OntologyVersion.id")


class OntologyItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ontology_items"
    __table_args__ = (
        Index("ix_ontology_items_name", "canonical_name"),
        Index("ix_ontology_items_type_category", "item_type", "category"),
        Index("ix_ontology_items_part_number", "manufacturer_part_number"),
        Index("ix_ontology_items_status", "status"),
    )

    canonical_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    item_type: Mapped[LineItemKind] = mapped_column(
        enum_type(LineItemKind, "ontology_item_type"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(160), nullable=False)
    subcategory: Mapped[str | None] = mapped_column(String(160), nullable=True)
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    manufacturer_part_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quality_tier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    part_grade: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    typical_labour_hours: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    standard_labour_rate: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    paint_material_allowance: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    repair_or_replace_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str] = mapped_column(String(120), nullable=False, default="UK")
    reference_price_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    price_vat_basis: Mapped[PriceVatBasis] = mapped_column(
        enum_type(PriceVatBasis, "ontology_price_vat_basis"),
        nullable=False,
        default=PriceVatBasis.NET,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")
    price_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url_or_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[OntologyItemStatus] = mapped_column(
        enum_type(OntologyItemStatus, "ontology_item_status"),
        nullable=False,
        default=OntologyItemStatus.PROVISIONAL,
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "ontology_item_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        enum_type(ConfidenceLevel, "ontology_item_confidence_level"),
        nullable=False,
        default=ConfidenceLevel.LOW,
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_in_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="RESTRICT"), nullable=False
    )
    retired_in_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="SET NULL"), nullable=True
    )

    synonyms: Mapped[list[OntologySynonym]] = relationship(
        back_populates="ontology_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    vehicle_applicability: Mapped[list[VehicleApplicability]] = relationship(
        back_populates="ontology_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    price_observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="ontology_item", passive_deletes=True
    )
    superseded_by: Mapped[OntologyItem | None] = relationship(
        remote_side="OntologyItem.id", foreign_keys=[superseded_by_id]
    )


class OntologySynonym(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ontology_synonyms"
    __table_args__ = (
        UniqueConstraint(
            "ontology_item_id", "normalised_synonym", name="uq_ontology_synonyms_item_value"
        ),
        Index("ix_ontology_synonyms_normalised", "normalised_synonym"),
        Index("ix_ontology_synonyms_approval", "approval_status"),
        Index(
            "uq_ontology_synonyms_learned_normalised",
            "normalised_synonym",
            unique=True,
            sqlite_where=text("source_type = 'handler_approved_invoice_mapping'"),
            postgresql_where=text("source_type = 'handler_approved_invoice_mapping'"),
        ),
    )

    ontology_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="CASCADE"), nullable=False
    )
    synonym: Mapped[str] = mapped_column(String(500), nullable=False)
    normalised_synonym: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "ontology_synonym_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )
    created_in_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="RESTRICT"), nullable=False
    )

    ontology_item: Mapped[OntologyItem] = relationship(back_populates="synonyms")


class VehicleApplicability(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "vehicle_applicability"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint("year_from IS NULL OR year_from >= 1886", name="year_from_valid"),
        CheckConstraint("year_to IS NULL OR year_to >= 1886", name="year_to_valid"),
        CheckConstraint(
            "year_from IS NULL OR year_to IS NULL OR year_from <= year_to",
            name="year_range_valid",
        ),
        Index("ix_vehicle_applicability_make_model", "make", "model"),
        Index("ix_vehicle_applicability_item", "ontology_item_id"),
    )

    ontology_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="CASCADE"), nullable=False
    )
    make: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    engine_cc_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_cc_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    vin_pattern: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "vehicle_applicability_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )

    ontology_item: Mapped[OntologyItem] = relationship(back_populates="vehicle_applicability")


class PriceObservation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        Index(
            "ix_price_observations_item_effective",
            "ontology_item_id",
            "effective_from",
        ),
        Index("ix_price_observations_approval_kind", "approval_status", "observation_kind"),
        Index("ix_price_observations_source_record", "source_provider_id", "source_record_id"),
    )

    ontology_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="SET NULL"), nullable=True
    )
    price_net: Mapped[str] = mapped_column(MoneyString, nullable=False)
    original_price: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")
    vat_basis: Mapped[PriceVatBasis] = mapped_column(
        enum_type(PriceVatBasis, "price_observation_vat_basis"), nullable=False
    )
    unit: Mapped[str] = mapped_column(String(80), nullable=False)
    price_scope: Mapped[PriceScope] = mapped_column(
        enum_type(PriceScope, "price_observation_scope"),
        nullable=False,
        default=PriceScope.UNIT,
    )
    source_provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_providers.id", ondelete="SET NULL"), nullable=True
    )
    source_import_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_imports.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url_or_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    region: Mapped[str] = mapped_column(String(120), nullable=False, default="UK")
    quality_tier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shipping_included: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "price_observation_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )
    observation_kind: Mapped[PriceObservationKind] = mapped_column(
        enum_type(PriceObservationKind, "price_observation_kind"), nullable=False
    )
    evidence_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("external_evidence.id", ondelete="SET NULL"), nullable=True
    )
    created_in_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="SET NULL"), nullable=True
    )

    ontology_item: Mapped[OntologyItem | None] = relationship(back_populates="price_observations")


class HistoricalObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "historical_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_import_id", "source_record_id", name="uq_historical_source_record"
        ),
        Index("ix_historical_observations_ontology_date", "ontology_item_id", "invoice_date"),
        Index("ix_historical_observations_part_number", "part_number"),
        Index("ix_historical_observations_vehicle", "vehicle_make", "vehicle_model"),
        Index("ix_historical_observations_vehicle_class", "official_vehicle_class"),
        Index("ix_historical_observations_settlement", "settlement_status"),
    )

    source_import_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_imports.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    source_invoice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    source_line_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="SET NULL"), nullable=True
    )
    source_record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    claim_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    observation_type: Mapped[InvoiceDocumentRole] = mapped_column(
        enum_type(InvoiceDocumentRole, "historical_observation_type"),
        nullable=False,
        default=InvoiceDocumentRole.HISTORICAL,
    )
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ontology_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="SET NULL"), nullable=True
    )
    part_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_make: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vehicle_variant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    vehicle_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # These values deliberately preserve the source classification separately
    # from the repair ontology.  UK regulatory class/bodywork and commercial
    # market segments are useful dimensions, but they must never be inferred
    # from a repair description.
    official_vehicle_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bodywork_code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    market_segment: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classification_source: Mapped[str | None] = mapped_column(String(240), nullable=True)
    repair_operation: Mapped[str | None] = mapped_column(String(300), nullable=True)
    workshop_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str] = mapped_column(String(120), nullable=False, default="UK")
    part_grade: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quantity: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price_scope: Mapped[PriceScope] = mapped_column(
        enum_type(PriceScope, "historical_price_scope"),
        nullable=False,
        default=PriceScope.LINE_TOTAL,
    )
    unit_price_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    line_total_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    approved_amount_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    settled_amount_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    labour_hours: Mapped[str | None] = mapped_column(QuantityString, nullable=True)
    labour_rate: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    discount_applied: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    vat_basis: Mapped[PriceVatBasis] = mapped_column(
        enum_type(PriceVatBasis, "historical_vat_basis"),
        nullable=False,
        default=PriceVatBasis.NET,
    )
    settlement_status: Mapped[SettlementStatus] = mapped_column(
        enum_type(SettlementStatus, "historical_settlement_status"),
        nullable=False,
        default=SettlementStatus.PROPOSED,
    )
    comparability_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "historical_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )


class ConfigVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("kind", "version", name="uq_config_versions_kind_version"),
        Index("ix_config_versions_kind_status", "kind", "status"),
        Index(
            "uq_config_versions_active_kind",
            "kind",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    kind: Mapped[ConfigKind] = mapped_column(
        enum_type(ConfigKind, "config_version_kind"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(120), nullable=False)
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ConfigStatus] = mapped_column(
        enum_type(ConfigStatus, "config_version_status"),
        nullable=False,
        default=ConfigStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegulatoryRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "regulatory_rules"
    __table_args__ = (
        UniqueConstraint(
            "rule_name", "jurisdiction", "effective_from", name="uq_regulatory_rule_period"
        ),
        Index("ix_regulatory_rules_lookup", "jurisdiction", "rule_name", "effective_from"),
    )

    config_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True
    )
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False, default="UK")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    value_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str] = mapped_column(Text, nullable=False)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "regulatory_rule_approval_status"),
        nullable=False,
        default=ApprovalStatus.APPROVED,
    )


class ProcessingRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        Index("ix_processing_runs_case_started", "case_id", "started_at"),
        Index("ix_processing_runs_status", "status"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    run_type: Mapped[RunType] = mapped_column(
        enum_type(RunType, "processing_run_type"),
        nullable=False,
        default=RunType.FULL,
    )
    application_version: Mapped[str] = mapped_column(String(120), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ontology_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="SET NULL"), nullable=True
    )
    benchmark_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_config_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True
    )
    model_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "processing_run_status"),
        nullable=False,
        default=RunStatus.PENDING,
    )
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_import_versions_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )

    case: Mapped[Case] = relationship(back_populates="processing_runs", foreign_keys=[case_id])
    mapping_runs: Mapped[list[MappingRun]] = relationship(
        back_populates="processing_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    comparisons: Mapped[list[PriceComparison]] = relationship(
        back_populates="processing_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MappingRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mapping_runs"
    __table_args__ = (
        Index("ix_mapping_runs_processing", "processing_run_id"),
        Index("ix_mapping_runs_status", "status"),
    )

    processing_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("processing_runs.id", ondelete="CASCADE"), nullable=False
    )
    ontology_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="RESTRICT"), nullable=False
    )
    model_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "mapping_run_status"),
        nullable=False,
        default=RunStatus.PENDING,
    )

    processing_run: Mapped[ProcessingRun] = relationship(back_populates="mapping_runs")
    mappings: Mapped[list[OntologyMapping]] = relationship(
        back_populates="mapping_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class OntologyMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ontology_mappings"
    __table_args__ = (
        UniqueConstraint(
            "mapping_run_id", "invoice_line_item_id", name="uq_ontology_mappings_run_line"
        ),
        CheckConstraint(
            "retrieval_similarity IS NULL OR "
            "(retrieval_similarity >= 0 AND retrieval_similarity <= 1)",
            name="retrieval_similarity_range",
        ),
        CheckConstraint(
            "llm_confidence IS NULL OR (llm_confidence >= 0 AND llm_confidence <= 1)",
            name="llm_confidence_range",
        ),
        CheckConstraint(
            "combined_confidence IS NULL OR "
            "(combined_confidence >= 0 AND combined_confidence <= 1)",
            name="combined_confidence_range",
        ),
        Index("ix_ontology_mappings_line", "invoice_line_item_id"),
        Index("ix_ontology_mappings_selected_item", "selected_ontology_item_id"),
        Index("ix_ontology_mappings_final_status", "final_status"),
    )

    mapping_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mapping_runs.id", ondelete="CASCADE"), nullable=False
    )
    invoice_line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=False
    )
    selected_ontology_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[MappingDecision] = mapped_column(
        enum_type(MappingDecision, "ontology_mapping_decision"), nullable=False
    )
    retrieval_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    combined_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternative_candidates_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    flags_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ai_output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    is_bundled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bundle_components_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    final_status: Mapped[MappingStatus] = mapped_column(
        enum_type(MappingStatus, "ontology_mapping_status"),
        nullable=False,
        default=MappingStatus.REVIEW,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    mapping_run: Mapped[MappingRun] = relationship(back_populates="mappings")
    invoice_line_item: Mapped[InvoiceLineItem] = relationship()
    selected_ontology_item: Mapped[OntologyItem | None] = relationship()


class PriceComparison(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "price_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "processing_run_id", "invoice_line_item_id", name="uq_price_comparisons_run_line"
        ),
        CheckConstraint("n_comparables >= 0", name="n_comparables_non_negative"),
        Index("ix_price_comparisons_line", "invoice_line_item_id"),
        Index("ix_price_comparisons_status", "status"),
        Index("ix_price_comparisons_policy", "benchmark_policy_version"),
    )

    processing_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("processing_runs.id", ondelete="CASCADE"), nullable=False
    )
    invoice_line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=False
    )
    ontology_mapping_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_mappings.id", ondelete="SET NULL"), nullable=True
    )
    invoice_unit_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    invoice_line_net: Mapped[str] = mapped_column(MoneyString, nullable=False)
    ontology_unit_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    ontology_line_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    historical_median_unit_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    historical_line_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    historical_p25_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    historical_p75_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    historical_lowest_recent_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    market_median_unit_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    market_line_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    n_comparables: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_benchmark_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    benchmark_unit_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    benchmark_line_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    benchmark_policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    ontology_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_versions.id", ondelete="SET NULL"), nullable=True
    )
    benchmark_formula_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    eligibility_flags_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[ComparisonStatus] = mapped_column(
        enum_type(ComparisonStatus, "price_comparison_status"),
        nullable=False,
        default=ComparisonStatus.PENDING,
    )

    processing_run: Mapped[ProcessingRun] = relationship(back_populates="comparisons")
    invoice_line_item: Mapped[InvoiceLineItem] = relationship()
    comparables: Mapped[list[ComparisonComparable]] = relationship(
        back_populates="price_comparison",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    challenge_results: Mapped[list[ChallengeResult]] = relationship(
        back_populates="price_comparison", passive_deletes=True
    )


class ComparisonComparable(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "comparison_comparables"
    __table_args__ = (
        CheckConstraint(
            "(price_observation_id IS NOT NULL AND historical_observation_id IS NULL) OR "
            "(price_observation_id IS NULL AND historical_observation_id IS NOT NULL)",
            name="exactly_one_observation_source",
        ),
        Index("ix_comparison_comparables_comparison", "price_comparison_id"),
        Index("ix_comparison_comparables_price_observation", "price_observation_id"),
        Index("ix_comparison_comparables_historical", "historical_observation_id"),
    )

    price_comparison_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("price_comparisons.id", ondelete="CASCADE"), nullable=False
    )
    price_observation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("price_observations.id", ondelete="CASCADE"), nullable=True
    )
    historical_observation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("historical_observations.id", ondelete="CASCADE"), nullable=True
    )
    comparable_class: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[str] = mapped_column(WeightString, nullable=False)
    original_line_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    normalised_line_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    adjustments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stale_data_warning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eligibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_comparison: Mapped[PriceComparison] = relationship(back_populates="comparables")


class ChallengeResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "challenge_results"
    __table_args__ = (
        CheckConstraint(
            "(price_comparison_id IS NOT NULL AND invoice_id IS NULL) OR "
            "(price_comparison_id IS NULL AND invoice_id IS NOT NULL)",
            name="line_or_invoice_result",
        ),
        UniqueConstraint("price_comparison_id", name="uq_challenge_results_comparison"),
        UniqueConstraint(
            "processing_run_id", "invoice_id", name="uq_challenge_results_run_invoice"
        ),
        CheckConstraint(
            "evidence_strength_score >= 0 AND evidence_strength_score <= 100",
            name="evidence_score_range",
        ),
        Index("ix_challenge_results_status", "status"),
        Index("ix_challenge_results_invoice", "invoice_id"),
    )

    processing_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("processing_runs.id", ondelete="CASCADE"), nullable=False
    )
    price_comparison_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("price_comparisons.id", ondelete="CASCADE"), nullable=True
    )
    invoice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True
    )
    challenge_net: Mapped[str] = mapped_column(MoneyString, nullable=False)
    challenge_vat: Mapped[str] = mapped_column(MoneyString, nullable=False, default="0.00")
    challenge_gross: Mapped[str] = mapped_column(MoneyString, nullable=False)
    challenge_percentage: Mapped[str] = mapped_column(RateString, nullable=False)
    evidence_strength_score: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_label: Mapped[str] = mapped_column(String(80), nullable=False)
    recommended_payable_net: Mapped[str] = mapped_column(MoneyString, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    findings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[ChallengeStatus] = mapped_column(
        enum_type(ChallengeStatus, "challenge_result_status"),
        nullable=False,
        default=ChallengeStatus.DRAFT,
    )
    reviewer_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    price_comparison: Mapped[PriceComparison | None] = relationship(
        back_populates="challenge_results"
    )


class ReviewTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="priority_non_negative"),
        Index("ix_review_tasks_queue", "status", "priority", "created_at"),
        Index("ix_review_tasks_case", "case_id"),
        Index("ix_review_tasks_entity", "entity_type", "entity_id"),
        Index("ix_review_tasks_assigned", "assigned_to", "status"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    status: Mapped[ReviewTaskStatus] = mapped_column(
        enum_type(ReviewTaskStatus, "review_task_status"),
        nullable=False,
        default=ReviewTaskStatus.OPEN,
    )
    assigned_to: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    decisions: Mapped[list[ReviewDecision]] = relationship(
        back_populates="review_task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReviewDecision.created_at",
    )


class ReviewDecision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        Index("ix_review_decisions_task_created", "review_task_id", "created_at"),
        Index("ix_review_decisions_actor", "actor_id"),
    )

    review_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("review_tasks.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[ReviewAction] = mapped_column(
        enum_type(ReviewAction, "review_decision_action"), nullable=False
    )
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_task: Mapped[ReviewTask] = relationship(back_populates="decisions")


class ResearchTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_tasks"
    __table_args__ = (
        Index("ix_research_tasks_case_status", "case_id", "status"),
        Index("ix_research_tasks_line", "invoice_line_item_id"),
    )

    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    invoice_line_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False)
    initiated_automatically: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_allow_list_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[ResearchStatus] = mapped_column(
        enum_type(ResearchStatus, "research_task_status"),
        nullable=False,
        default=ResearchStatus.PENDING,
    )
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    suggestion: Mapped[ResearchItem | None] = relationship(
        back_populates="research_task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    evidence: Mapped[list[ExternalEvidence]] = relationship(
        back_populates="research_task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ResearchItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_items"
    __table_args__ = (
        UniqueConstraint("research_task_id", name="uq_research_items_task"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_research_items_status", "status"),
    )

    research_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_tasks.id", ondelete="CASCADE"), nullable=False
    )
    provisional_ontology_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ontology_items.id", ondelete="SET NULL"), nullable=True
    )
    suggested_canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    suggested_item_type: Mapped[LineItemKind] = mapped_column(
        enum_type(LineItemKind, "research_item_type"), nullable=False
    )
    suggested_category: Mapped[str] = mapped_column(String(160), nullable=False)
    suggested_unit: Mapped[str] = mapped_column(String(80), nullable=False)
    suggested_part_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    vehicle_compatibility_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    suggested_price_net: Mapped[str] = mapped_column(MoneyString, nullable=False)
    vat_basis: Mapped[PriceVatBasis] = mapped_column(
        enum_type(PriceVatBasis, "research_item_vat_basis"), nullable=False
    )
    source_urls_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    date_checked: Mapped[date] = mapped_column(Date, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    raw_suggestion_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ResearchStatus] = mapped_column(
        enum_type(ResearchStatus, "research_item_status"),
        nullable=False,
        default=ResearchStatus.PROVISIONAL,
    )
    reviewer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    research_task: Mapped[ResearchTask] = relationship(back_populates="suggestion")


class ExternalEvidence(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "external_evidence"
    __table_args__ = (
        Index("ix_external_evidence_research", "research_task_id"),
        Index("ix_external_evidence_content_hash", "content_hash"),
        Index("ix_external_evidence_part_number", "part_number"),
    )

    research_task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_tasks.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_providers.id", ondelete="SET NULL"), nullable=True
    )
    source_record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    minimal_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fitment_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    price_net: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    original_price: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="GBP")
    vat_basis: Mapped[PriceVatBasis] = mapped_column(
        enum_type(PriceVatBasis, "external_evidence_vat_basis"),
        nullable=False,
        default=PriceVatBasis.UNKNOWN,
    )
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quality_tier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shipping: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    validation_flags_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "external_evidence_approval_status"),
        nullable=False,
        default=ApprovalStatus.PROVISIONAL,
    )

    research_task: Mapped[ResearchTask] = relationship(back_populates="evidence")


class Settlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settlements"
    __table_args__ = (
        Index("ix_settlements_invoice_status", "invoice_id", "status"),
        Index("ix_settlements_line", "line_item_id"),
        Index("ix_settlements_agreed_at", "agreed_at"),
    )

    invoice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("invoice_line_items.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[SettlementStatus] = mapped_column(
        enum_type(SettlementStatus, "settlement_status"),
        nullable=False,
        default=SettlementStatus.SETTLED,
    )
    agreed_amount_net: Mapped[str] = mapped_column(MoneyString, nullable=False)
    agreed_vat: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    agreed_amount_gross: Mapped[str | None] = mapped_column(MoneyString, nullable=True)
    agreed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(160), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    negotiation_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    historical_observation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("historical_observations.id", ondelete="SET NULL"), nullable=True
    )

    invoice: Mapped[Invoice] = relationship(back_populates="settlements")


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only, optionally hash-chained audit record."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_case_created", "case_id", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_processing_run", "processing_run_id"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_hash", "event_hash"),
    )

    case_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="SET NULL"), nullable=True
    )
    processing_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("processing_runs.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[AuditActorType] = mapped_column(
        enum_type(AuditActorType, "audit_actor_type"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    event_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


def _prevent_audit_mutation(mapper: object, connection: object, target: AuditEvent) -> None:
    raise RuntimeError("audit_events are append-only")


def _hash_audit_event(mapper: object, connection: object, target: AuditEvent) -> None:
    """Seal each new audit row to the previous sealed row for the same case."""

    target.created_at = target.created_at or utc_now()
    target.event_payload_json = target.event_payload_json or {}
    previous_hash = connection.execute(
        AuditEvent.__table__.select()
        .with_only_columns(AuditEvent.__table__.c.event_hash)
        .where(
            AuditEvent.__table__.c.case_id.is_(None)
            if target.case_id is None
            else AuditEvent.__table__.c.case_id == target.case_id,
            AuditEvent.__table__.c.event_hash.is_not(None),
        )
        .order_by(
            AuditEvent.__table__.c.created_at.desc(),
            AuditEvent.__table__.c.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    target.previous_event_hash = previous_hash
    canonical = json.dumps(
        {
            "case_id": target.case_id,
            "processing_run_id": target.processing_run_id,
            "actor_type": getattr(target.actor_type, "value", target.actor_type),
            "actor_id": target.actor_id,
            "event_type": target.event_type,
            "entity_type": target.entity_type,
            "entity_id": target.entity_id,
            "before": target.before_json,
            "after": target.after_json,
            "payload": target.event_payload_json,
            "correlation_id": target.correlation_id,
            "created_at": target.created_at,
            "previous_event_hash": previous_hash,
        },
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    target.event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()


event.listen(AuditEvent, "before_insert", _hash_audit_event)
event.listen(AuditEvent, "before_update", _prevent_audit_mutation)
event.listen(AuditEvent, "before_delete", _prevent_audit_mutation)


# Compatibility names used by earlier PRD drafts and pipeline modules.
CalculationCheck = MathFinding
HistoricalClaimLine = HistoricalObservation


__all__ = [
    "AuditEvent",
    "CalculationCheck",
    "Case",
    "ChallengeResult",
    "ClaimConsistencyFinding",
    "ClaimContext",
    "ClaimParty",
    "ClaimVehicle",
    "ComparisonComparable",
    "ConfigVersion",
    "Document",
    "DocumentPage",
    "ExternalEvidence",
    "HistoricalClaimLine",
    "HistoricalObservation",
    "Invoice",
    "InvoiceLineItem",
    "LiabilityAssessment",
    "LiabilityEvidence",
    "MappingRun",
    "MathFinding",
    "OntologyItem",
    "OntologyMapping",
    "OntologySynonym",
    "OntologyVersion",
    "PriceComparison",
    "PriceObservation",
    "ProcessingRun",
    "RegulatoryRule",
    "ResearchItem",
    "ResearchTask",
    "ReviewDecision",
    "ReviewTask",
    "Settlement",
    "SourceImport",
    "SourceProvider",
    "Vehicle",
    "VehicleApplicability",
    "invoice_page_links",
]
