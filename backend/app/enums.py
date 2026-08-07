"""Stable domain enumerations used by both persistence and API schemas."""

from __future__ import annotations

from enum import StrEnum


class DomainEnum(StrEnum):
    """String enum with predictable JSON and SQLite representations."""


class CaseStatus(DomainEnum):
    DRAFT = "draft"
    CLAIM_REVIEW = "claim_review"
    LIABILITY_REVIEW = "liability_review"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTION_REVIEW = "extraction_review"
    MAPPING_REVIEW = "mapping_review"
    COMPARISON_REVIEW = "comparison_review"
    READY_FOR_OUTPUT = "ready_for_output"
    FINALISED = "finalised"
    FAILED = "failed"
    ARCHIVED = "archived"


class DocumentRole(DomainEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    REFERENCE = "reference"
    LIABILITY_EVIDENCE = "liability_evidence"
    SUPPORTING = "supporting"


class UploadStatus(DomainEnum):
    PENDING = "pending"
    STORED = "stored"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class PageType(DomainEnum):
    INVOICE = "invoice"
    ESTIMATE_OR_ORDER = "estimate_or_order"
    CREDIT_NOTE = "credit_note"
    VEHICLE_DOCUMENT = "vehicle_document"
    SERVICE_HISTORY = "service_history"
    MOT = "mot"
    PHOTO = "photo"
    BLANK = "blank"
    OTHER = "other"


class ExtractionMethod(DomainEnum):
    PENDING = "pending"
    NATIVE_TEXT = "native_text"
    NATIVE_TABLE = "native_table"
    LAYOUT_REPAIR = "layout_repair"
    OCR = "ocr"
    VISION = "vision"
    IMPORTED = "imported"
    MANUAL = "manual"


class ReviewStatus(DomainEnum):
    PENDING = "pending"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"
    WAIVED = "waived"


class InvoiceDocumentRole(DomainEnum):
    INVOICE = "invoice"
    ESTIMATE = "estimate"
    CREDIT_NOTE = "credit_note"
    HISTORICAL = "historical"


class LineItemKind(DomainEnum):
    PART = "part"
    LABOUR = "labour"
    PAINT = "paint"
    SERVICE = "service"
    FEE = "fee"
    DISPOSAL = "disposal"
    CONSUMABLE = "consumable"
    RECOVERY = "recovery"
    STORAGE = "storage"
    SUBCONTRACT = "subcontract"
    DIAGNOSTIC = "diagnostic"
    DISCOUNT = "discount"
    UNKNOWN = "unknown"


class PriceScope(DomainEnum):
    UNIT = "unit"
    LINE_TOTAL = "line_total"
    JOB = "job"
    HOURLY = "hourly"


class CheckStatus(DomainEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class Severity(DomainEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class OntologyVersionStatus(DomainEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class OntologyItemStatus(DomainEnum):
    PROVISIONAL = "provisional"
    APPROVED = "approved"
    RETIRED = "retired"
    MERGED = "merged"
    REJECTED = "rejected"


class ApprovalStatus(DomainEnum):
    PROVISIONAL = "provisional"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class ConfidenceLevel(DomainEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PriceVatBasis(DomainEnum):
    NET = "net"
    GROSS = "gross"
    EXEMPT = "exempt"
    UNKNOWN = "unknown"


class PriceObservationKind(DomainEnum):
    REFERENCE = "reference"
    HISTORICAL = "historical"
    SETTLED = "settled"
    PROVISIONAL = "provisional"
    CONTRACTED = "contracted"
    MARKET = "market"


class SourceProviderType(DomainEnum):
    EXCEL = "excel"
    CSV = "csv"
    PDF = "pdf"
    WEB = "web"
    LICENSED = "licensed"
    INTERNAL = "internal"
    API = "api"
    MANUAL = "manual"


class ImportStatus(DomainEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    IMPORTED = "imported"
    PARTIAL = "partial"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class RunStatus(DomainEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunType(DomainEnum):
    FULL = "full"
    REPROCESS = "reprocess"
    EXTRACTION = "extraction"
    MAPPING = "mapping"
    COMPARISON = "comparison"
    EXPORT = "export"
    IMPORT = "import"


class MappingDecision(DomainEnum):
    EXACT_PART_NUMBER = "exact_part_number"
    SYNONYM = "synonym"
    FUZZY = "fuzzy"
    LLM = "llm"
    MANUAL = "manual"
    NO_MATCH = "no_match"
    BUNDLED = "bundled"


class MappingStatus(DomainEnum):
    AUTO_ACCEPTED = "auto_accepted"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    MISSING = "missing"
    SUPERSEDED = "superseded"


class ComparisonStatus(DomainEnum):
    PENDING = "pending"
    PROVISIONAL = "provisional"
    REVIEW = "review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"
    FINAL = "final"


class ChallengeStatus(DomainEnum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"
    SETTLED = "settled"


class ReviewTaskStatus(DomainEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    WAIVED = "waived"


class ReviewAction(DomainEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    DEFER = "defer"
    WAIVE = "waive"
    REASSIGN = "reassign"


class ResearchStatus(DomainEnum):
    PENDING = "pending"
    RUNNING = "running"
    PROVISIONAL = "provisional"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SettlementStatus(DomainEnum):
    PROPOSED = "proposed"
    NEGOTIATED = "negotiated"
    SETTLED = "settled"
    REOPENED = "reopened"
    VOID = "void"


class ConfigKind(DomainEnum):
    POLICY = "policy"
    PROVIDERS = "providers"
    FEATURE_FLAGS = "feature_flags"
    ABBREVIATIONS = "abbreviations"
    REGULATORY = "regulatory"
    RESEARCH_SOURCES = "research_sources"
    APPLICATION = "application"


class ConfigStatus(DomainEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class AuditActorType(DomainEnum):
    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
    IMPORT = "import"


class LiabilityStatus(DomainEnum):
    """The mandatory liability gate values; deliberately persisted uppercase."""

    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    SPLIT_LIABILITY = "SPLIT_LIABILITY"
    PENDING = "PENDING"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class LiabilityGateStatus(DomainEnum):
    NOT_STARTED = "not_started"
    AWAITING_EVIDENCE = "awaiting_evidence"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    CONFIRMED = "confirmed"
    BLOCKED = "blocked"


class ClaimPartyRole(DomainEnum):
    PAYING_INSURER = "paying_insurer"
    CLAIMING_INSURER = "claiming_insurer"
    INSURED_POLICYHOLDER = "insured_policyholder"
    INSURED_DRIVER = "insured_driver"
    CLAIMANT = "claimant"
    CLAIMANT_DRIVER = "claimant_driver"
    THIRD_PARTY = "third_party"
    WITNESS = "witness"
    OTHER = "other"


class ClaimVehicleRole(DomainEnum):
    INSURED_VEHICLE = "insured_vehicle"
    CLAIMANT_VEHICLE = "claimant_vehicle"
    THIRD_PARTY_VEHICLE = "third_party_vehicle"
    OTHER = "other"


class LiabilityEvidenceType(DomainEnum):
    """Invoices are intentionally absent: invoice content cannot determine fault."""

    ACCIDENT_REPORT = "accident_report"
    CLAIM_FORM = "claim_form"
    ADMISSION_CORRESPONDENCE = "admission_correspondence"
    WITNESS_STATEMENT = "witness_statement"
    DASHCAM = "dashcam"
    PHOTO = "photo"
    POLICE_REPORT = "police_report"
    ENGINEER_REPORT = "engineer_report"
    POLICY_RECORD = "policy_record"
    OTHER = "other"


class ConsistencyFindingStatus(DomainEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
