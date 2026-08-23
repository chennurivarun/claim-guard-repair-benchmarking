"""Governed reviewer-initiated research workflow for the ClaimGuard pilot.

The pilot does not browse automatically. A reviewer supplies source evidence and a
suggestion, which is persisted as a provisional ontology item. The normal pilot
configuration promotes it on one handler approval; ``two_step_approval`` retains
the same code path but requires a different second approver.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.db_types import utc_now
from app.domain.normalisation import normalise_description
from app.enums import (
    ApprovalStatus,
    AuditActorType,
    ConfidenceLevel,
    LineItemKind,
    OntologyItemStatus,
    OntologyVersionStatus,
    PriceObservationKind,
    PriceScope,
    PriceVatBasis,
    ResearchStatus,
    RunStatus,
    RunType,
)
from app.models import (
    AuditEvent,
    Case,
    ExternalEvidence,
    Invoice,
    InvoiceLineItem,
    OntologyItem,
    OntologyMapping,
    OntologyVersion,
    PriceObservation,
    ProcessingRun,
    ResearchItem,
    ResearchTask,
)
from app.services.comparison_workflow import MappingOverride, run_case_comparison

DEFAULT_SOURCE_ALLOW_LIST_VERSION = "pilot-manual-sources-v1"
_OPEN_RESEARCH_STATUSES = (
    ResearchStatus.PENDING,
    ResearchStatus.RUNNING,
    ResearchStatus.PROVISIONAL,
)
_DEDUP_RESEARCH_STATUSES = (*_OPEN_RESEARCH_STATUSES, ResearchStatus.APPROVED)

# Task B2: source_type/price_source marker for research and price-evidence rows
# created automatically from an unmatched priced invoice line, so they are always
# distinguishable from reviewer-initiated research in audit events and the UI.
AUTO_STAGED_SOURCE_TYPE = "auto_unmatched_invoice_line"
AUTO_STAGE_ALLOW_LIST_VERSION = "internal-invoice-provenance-v1"


MoneyInput = Decimal | str | int
WorkflowStatus = Literal["provisional", "awaiting_second_review", "approved"]
NextAction = Literal["handler_approval", "second_review", "none"]
ComparisonRefreshStatus = Literal[
    "not_requested",
    "skipped_no_completed_run",
    "skipped_source_line_not_comparable",
    "recomputed",
]


@dataclass(frozen=True, slots=True)
class ManualEvidenceInput:
    """A source captured by the reviewer; no web fetch is performed here."""

    source_uri: str
    title: str
    captured_at: datetime | None = None
    minimal_excerpt: str | None = None
    source_record_id: str | None = None
    price_net: MoneyInput | None = None
    original_price: MoneyInput | None = None
    currency: str = "GBP"
    vat_basis: PriceVatBasis = PriceVatBasis.NET
    unit: str | None = None
    part_number: str | None = None
    fitment: dict[str, object] | None = None
    quality_tier: str | None = None
    condition: str | None = None
    shipping: MoneyInput | None = None
    stock_status: str | None = None
    validation_flags: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ResearchSuggestionInput:
    canonical_name: str
    item_type: LineItemKind
    category: str
    unit: str
    price_net: MoneyInput
    date_checked: date
    rationale: str
    vat_basis: PriceVatBasis = PriceVatBasis.NET
    price_scope: PriceScope = PriceScope.UNIT
    part_number: str | None = None
    vehicle_compatibility: dict[str, object] | None = None
    confidence: float | None = None
    currency: str = "GBP"
    region: str = "UK"
    quality_tier: str | None = None


class ComparisonRefreshResult(TypedDict):
    status: ComparisonRefreshStatus
    previous_processing_run_id: str | None
    processing_run_id: str | None
    mapping_run_id: str | None
    ontology_mapping_id: str | None
    reason: str


class ResearchWorkflowResult(TypedDict):
    task_id: str
    research_item_id: str
    ontology_item_id: str
    ontology_version_id: str
    evidence_ids: list[str]
    price_observation_ids: list[str]
    source_urls: list[str]
    date_checked: str
    confidence: float | None
    status: WorkflowStatus
    second_review_required: bool
    next_action: NextAction
    comparison_refresh: ComparisonRefreshResult


class ResearchWorkflowError(ValueError):
    """A stable domain error suitable for translation to an API response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ResearchWorkflowError("INVALID_RESEARCH_INPUT", f"{field_name} must not be blank")
    return cleaned


def _money(value: MoneyInput, field_name: str) -> str:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ResearchWorkflowError(
            "INVALID_RESEARCH_INPUT", f"{field_name} must be a valid amount"
        ) from exc
    if not amount.is_finite() or amount < 0:
        raise ResearchWorkflowError(
            "INVALID_RESEARCH_INPUT", f"{field_name} must be a non-negative amount"
        )
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def _optional_money(value: MoneyInput | None, field_name: str) -> str | None:
    return None if value is None else _money(value, field_name)


def _confidence_level(confidence: float | None) -> ConfidenceLevel:
    if confidence is not None and confidence >= 0.8:
        return ConfidenceLevel.HIGH
    if confidence is not None and confidence >= 0.5:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _validate_url(value: str) -> str:
    cleaned = _required_text(value, "source_uri")
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ResearchWorkflowError(
            "INVALID_RESEARCH_INPUT",
            "source_uri must be an absolute HTTP or HTTPS URL",
        )
    return cleaned


def _normalise_host(value: str) -> str:
    cleaned = value.strip().lower().rstrip(".")
    try:
        return cleaned.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ResearchWorkflowError(
            "SOURCE_ALLOW_LIST_INVALID", f"invalid source host pattern: {value!r}"
        ) from exc


def _resolve_allowed_hosts(
    settings: Settings,
    source_allow_list_version: str,
    explicit_hosts: Sequence[str] | None,
) -> tuple[str, ...]:
    configured = (
        explicit_hosts
        if explicit_hosts is not None
        else settings.research_source_allowlists.get(source_allow_list_version)
    )
    if not configured:
        raise ResearchWorkflowError(
            "SOURCE_ALLOW_LIST_NOT_CONFIGURED",
            f"no source hosts are configured for {source_allow_list_version}",
        )
    result: list[str] = []
    for raw_pattern in configured:
        pattern = _required_text(raw_pattern, "allowed_source_host")
        if pattern == "*":
            raise ResearchWorkflowError(
                "SOURCE_ALLOW_LIST_INVALID",
                "a global wildcard is not permitted in the source allow-list",
            )
        wildcard = pattern.startswith("*.")
        host = _normalise_host(pattern[2:] if wildcard else pattern)
        if not host or "/" in host or ":" in host:
            raise ResearchWorkflowError(
                "SOURCE_ALLOW_LIST_INVALID", f"invalid source host pattern: {pattern!r}"
            )
        normalised = f"*.{host}" if wildcard else host
        if normalised not in result:
            result.append(normalised)
    return tuple(result)


def _source_host(source_uri: str) -> str:
    hostname = urlsplit(source_uri).hostname
    if hostname is None:
        raise ResearchWorkflowError(
            "INVALID_RESEARCH_INPUT", "source_uri does not contain a hostname"
        )
    return _normalise_host(hostname)


def _source_uri_identity(source_uri: str) -> str:
    parsed = urlsplit(source_uri.strip())
    host = _source_host(source_uri)
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (
        parsed.scheme.lower() == "http" and port == 80
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _host_is_allowed(host: str, allowed_hosts: Sequence[str]) -> bool:
    for pattern in allowed_hosts:
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if host == suffix or host.endswith(f".{suffix}"):
                return True
        elif host == pattern:
            return True
    return False


def _enforce_source_allow_list(source_uri: str, allowed_hosts: Sequence[str]) -> str:
    host = _source_host(source_uri)
    if not _host_is_allowed(host, allowed_hosts):
        raise ResearchWorkflowError(
            "SOURCE_HOST_NOT_ALLOWED",
            f"source host {host!r} is not in the configured allow-list",
        )
    return host


def _normalise_identity_text(value: str | None) -> str:
    normalised = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalised))


def _normalise_part_number(value: str | None) -> str:
    return "".join(re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", value or "").casefold()))


def _canonical_identity(
    *,
    item_type: LineItemKind,
    canonical_name: str,
    category: str,
    unit: str,
    part_number: str | None,
) -> tuple[str, ...]:
    normalised_part_number = _normalise_part_number(part_number)
    if normalised_part_number:
        return ("part_number", item_type.value, normalised_part_number)
    return (
        "canonical",
        item_type.value,
        _normalise_identity_text(canonical_name),
        _normalise_identity_text(category),
        _normalise_identity_text(unit),
    )


def _suggestion_identity(suggestion: ResearchSuggestionInput) -> tuple[str, ...]:
    return _canonical_identity(
        item_type=suggestion.item_type,
        canonical_name=suggestion.canonical_name,
        category=suggestion.category,
        unit=suggestion.unit,
        part_number=suggestion.part_number,
    )


def _identity_code(identity: Sequence[str]) -> str:
    digest = hashlib.sha256("\x1f".join(identity).encode("utf-8")).hexdigest()
    return f"RSR-{digest[:16].upper()}"


def _ontology_identity(item: OntologyItem) -> tuple[str, ...]:
    return _canonical_identity(
        item_type=item.item_type,
        canonical_name=item.canonical_name,
        category=item.category,
        unit=item.unit,
        part_number=item.manufacturer_part_number,
    )


def _research_identity(item: ResearchItem) -> tuple[str, ...]:
    return _canonical_identity(
        item_type=item.suggested_item_type,
        canonical_name=item.suggested_canonical_name,
        category=item.suggested_category,
        unit=item.suggested_unit,
        part_number=item.suggested_part_number,
    )


def _content_hash(evidence: ManualEvidenceInput, source_uri: str) -> str:
    canonical = json.dumps(
        {
            "source_uri": _source_uri_identity(source_uri),
            "source_record_id": evidence.source_record_id,
            "title": _normalise_identity_text(evidence.title),
            "minimal_excerpt": _normalise_identity_text(evidence.minimal_excerpt),
            "part_number": _normalise_part_number(evidence.part_number),
            "price_net": (
                _optional_money(evidence.price_net, "evidence.price_net")
                if evidence.price_net is not None
                else None
            ),
            "original_price": (
                _optional_money(evidence.original_price, "evidence.original_price")
                if evidence.original_price is not None
                else None
            ),
            "currency": evidence.currency.upper(),
            "vat_basis": evidence.vat_basis.value,
            "unit": evidence.unit,
            "fitment": evidence.fitment,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_inputs(
    suggestion: ResearchSuggestionInput,
    evidence: Sequence[ManualEvidenceInput],
    allowed_hosts: Sequence[str],
) -> tuple[str, list[str], list[str], list[str]]:
    _required_text(suggestion.canonical_name, "canonical_name")
    _required_text(suggestion.category, "category")
    _required_text(suggestion.unit, "unit")
    _required_text(suggestion.rationale, "rationale")
    price_net = _money(suggestion.price_net, "price_net")
    if suggestion.confidence is not None and not 0 <= suggestion.confidence <= 1:
        raise ResearchWorkflowError("INVALID_RESEARCH_INPUT", "confidence must be between 0 and 1")
    if not evidence:
        raise ResearchWorkflowError(
            "INVALID_RESEARCH_INPUT", "at least one evidence source is required"
        )
    source_urls: list[str] = []
    source_hosts: list[str] = []
    content_hashes: list[str] = []
    for source in evidence:
        _required_text(source.title, "evidence.title")
        source_uri = _validate_url(source.source_uri)
        source_host = _enforce_source_allow_list(source_uri, allowed_hosts)
        if source_uri not in source_urls:
            source_urls.append(source_uri)
        if source_host not in source_hosts:
            source_hosts.append(source_host)
        _optional_money(source.price_net, "evidence.price_net")
        _optional_money(source.original_price, "evidence.original_price")
        _optional_money(source.shipping, "evidence.shipping")
        content_hashes.append(_content_hash(source, source_uri))
    if len(content_hashes) != len(set(content_hashes)):
        raise ResearchWorkflowError(
            "DUPLICATE_EVIDENCE_IN_REQUEST",
            "the same evidence content was supplied more than once",
        )
    return price_net, source_urls, source_hosts, content_hashes


def _ensure_unique_research_identity(
    session: Session,
    suggestion: ResearchSuggestionInput,
    *,
    exclude_ontology_item_id: str | None = None,
    exclude_research_item_id: str | None = None,
) -> None:
    identity = _suggestion_identity(suggestion)
    approved_items = session.scalars(
        select(OntologyItem).where(
            OntologyItem.item_type == suggestion.item_type,
            OntologyItem.approval_status == ApprovalStatus.APPROVED,
        )
    ).all()
    for item in approved_items:
        if item.id != exclude_ontology_item_id and _ontology_identity(item) == identity:
            raise ResearchWorkflowError(
                "ONTOLOGY_ITEM_ALREADY_APPROVED",
                f"canonical identity already exists as approved item {item.canonical_code}",
            )

    open_items = session.scalars(
        select(ResearchItem).where(
            ResearchItem.suggested_item_type == suggestion.item_type,
            ResearchItem.status.in_(_OPEN_RESEARCH_STATUSES),
        )
    ).all()
    for item in open_items:
        if item.id != exclude_research_item_id and _research_identity(item) == identity:
            raise ResearchWorkflowError(
                "RESEARCH_IDENTITY_ALREADY_OPEN",
                f"canonical identity is already being researched in item {item.id}",
            )


def _ensure_unique_evidence_content(session: Session, content_hashes: Sequence[str]) -> None:
    existing = session.scalar(
        select(ExternalEvidence)
        .join(ResearchTask, ResearchTask.id == ExternalEvidence.research_task_id)
        .where(
            ExternalEvidence.content_hash.in_(tuple(content_hashes)),
            ResearchTask.status.in_(_DEDUP_RESEARCH_STATUSES),
        )
        .limit(1)
    )
    if existing is not None:
        raise ResearchWorkflowError(
            "EVIDENCE_CONTENT_ALREADY_RESEARCHED",
            "the supplied evidence content already belongs to an open or approved research task",
        )


def _latest_published_version(session: Session) -> OntologyVersion | None:
    return session.scalar(
        select(OntologyVersion)
        .where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
        .order_by(OntologyVersion.sequence_number.desc())
        .limit(1)
    )


def _new_ontology_version(
    session: Session, task: ResearchTask, requested_by: str
) -> OntologyVersion:
    latest = _latest_published_version(session)
    highest_sequence = session.scalar(select(func.max(OntologyVersion.sequence_number)))
    version = OntologyVersion(
        sequence_number=(highest_sequence if highest_sequence is not None else -1) + 1,
        label=f"research-{task.id}",
        parent_id=latest.id if latest else None,
        status=OntologyVersionStatus.DRAFT,
        created_by=requested_by,
        change_summary=(
            f"Reviewer-initiated provisional ontology suggestion from research task {task.id}."
        ),
    )
    session.add(version)
    session.flush()
    return version


def _not_requested_refresh(reason: str) -> ComparisonRefreshResult:
    return {
        "status": "not_requested",
        "previous_processing_run_id": None,
        "processing_run_id": None,
        "mapping_run_id": None,
        "ontology_mapping_id": None,
        "reason": reason,
    }


def _stored_comparison_refresh(item: ResearchItem) -> ComparisonRefreshResult:
    raw = item.raw_suggestion_json or {}
    workflow = raw.get("approval_workflow") or {}
    stored = workflow.get("comparison_refresh")
    if not isinstance(stored, dict):
        return _not_requested_refresh("approval has not requested comparison refresh")
    status = stored.get("status")
    valid_statuses = {
        "not_requested",
        "skipped_no_completed_run",
        "skipped_source_line_not_comparable",
        "recomputed",
    }
    if status not in valid_statuses:
        return _not_requested_refresh("stored refresh result is invalid")
    return {
        "status": status,
        "previous_processing_run_id": stored.get("previous_processing_run_id"),
        "processing_run_id": stored.get("processing_run_id"),
        "mapping_run_id": stored.get("mapping_run_id"),
        "ontology_mapping_id": stored.get("ontology_mapping_id"),
        "reason": str(stored.get("reason") or ""),
    }


def _workflow_result(
    session: Session,
    item: ResearchItem,
    *,
    status: WorkflowStatus,
    second_review_required: bool,
    next_action: NextAction,
    comparison_refresh: ComparisonRefreshResult | None = None,
) -> ResearchWorkflowResult:
    task = item.research_task
    evidence_ids = list(
        session.scalars(
            select(ExternalEvidence.id)
            .where(ExternalEvidence.research_task_id == task.id)
            .order_by(ExternalEvidence.created_at, ExternalEvidence.id)
        ).all()
    )
    price_ids = list(
        session.scalars(
            select(PriceObservation.id)
            .where(PriceObservation.ontology_item_id == item.provisional_ontology_item_id)
            .order_by(PriceObservation.created_at, PriceObservation.id)
        ).all()
    )
    return {
        "task_id": task.id,
        "research_item_id": item.id,
        "ontology_item_id": item.provisional_ontology_item_id or "",
        "ontology_version_id": (
            session.scalar(
                select(OntologyItem.created_in_version_id).where(
                    OntologyItem.id == item.provisional_ontology_item_id
                )
            )
            or ""
        ),
        "evidence_ids": evidence_ids,
        "price_observation_ids": price_ids,
        "source_urls": list(item.source_urls_json),
        "date_checked": item.date_checked.isoformat(),
        "confidence": item.confidence,
        "status": status,
        "second_review_required": second_review_required,
        "next_action": next_action,
        "comparison_refresh": comparison_refresh or _stored_comparison_refresh(item),
    }


def _auto_stage_identity_marker(raw_suggestion_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw_suggestion_json:
        return None
    workflow = raw_suggestion_json.get("workflow")
    if not isinstance(workflow, dict):
        return None
    marker = workflow.get("auto_stage")
    return marker if isinstance(marker, dict) else None


def find_open_auto_staged_proposal(
    session: Session,
    *,
    case_id: str,
    normalised_description: str,
    part_number_identity: str,
) -> ResearchItem | None:
    """Find an existing open/approved auto-staged proposal for the same line content.

    Dedup key is (case, normalised description, part number) rather than the invoice
    line id, so the same missing part described on several lines in a case (or a
    case reprocess run that re-encounters the same unmatched line) never produces a
    second proposal.
    """

    candidates = session.scalars(
        select(ResearchItem)
        .join(ResearchTask, ResearchTask.id == ResearchItem.research_task_id)
        .where(
            ResearchTask.case_id == case_id,
            ResearchItem.status.in_(_DEDUP_RESEARCH_STATUSES),
        )
    ).all()
    for candidate in candidates:
        marker = _auto_stage_identity_marker(candidate.raw_suggestion_json)
        if marker is None:
            continue
        if (
            marker.get("normalised_description") == normalised_description
            and marker.get("part_number_identity") == part_number_identity
        ):
            return candidate
    return None


def stage_unmatched_line_proposal(
    session: Session,
    *,
    case_id: str,
    line: InvoiceLineItem,
    invoice: Invoice,
    actor_id: str = "claimguard.auto-staging",
    settings: Settings | None = None,
) -> ResearchItem | None:
    """Auto-stage a "new ontology item" proposal for a priced, unmatched invoice line.

    This mirrors the persistence shape ``trigger_manual_research`` builds for a
    reviewer-initiated suggestion (ResearchTask -> ResearchItem -> provisional
    OntologyItem -> PriceObservation -> AuditEvent) so ``approve_research_item``
    promotes staged proposals exactly the way it promotes reviewer research, with
    no separate model. The evidence source differs: there is no ontology candidate
    to research yet, so the "evidence" is the invoice line itself (raw/normalised
    description, part number, unit, quantity, net price, and document/page
    provenance) rather than a reviewer-supplied web source, and no source
    allow-list/URL validation applies. ``price_source``/``source_type`` are marked
    ``AUTO_STAGED_SOURCE_TYPE`` throughout so these rows are always distinguishable
    from reviewer-triggered research in audit events and the workspace UI.

    Governance: the created OntologyItem/PriceObservation/ResearchItem are all
    PROVISIONAL, exactly like reviewer-initiated research, so they never
    contribute price evidence to a comparison until a handler approves them via
    the existing ``approve_research_item`` flow.

    Idempotent on (case, normalised description, part number): if an open or
    already-approved auto-staged proposal exists for the same line content, it is
    returned unchanged instead of creating a duplicate.
    """

    effective_settings = settings or get_settings()
    normalised_description = line.normalised_description or normalise_description(
        line.raw_description
    )
    part_number_identity = _normalise_part_number(line.part_number)

    existing = find_open_auto_staged_proposal(
        session,
        case_id=case_id,
        normalised_description=normalised_description,
        part_number_identity=part_number_identity,
    )
    if existing is not None:
        return existing

    if invoice.invoice_date is None or line.line_total_net is None:
        return None
    line_total_net = Decimal(str(line.line_total_net))
    if line_total_net <= 0:
        return None

    quantity = Decimal(str(line.quantity)) if line.quantity is not None else None
    if line.unit_price_net is not None:
        unit_price = Decimal(str(line.unit_price_net))
    elif quantity and quantity > 0:
        unit_price = (line_total_net / quantity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        unit_price = line_total_net
    price_net = _money(unit_price, "line.unit_price_net")
    currency = (invoice.currency or effective_settings.default_currency).upper()
    unit = (line.unit or "each").strip()
    category = (line.raw_category or line.item_kind.value.replace("_", " ")).strip().title()
    canonical_name = line.raw_description.strip()

    now = utc_now()
    task = ResearchTask(
        case_id=case_id,
        invoice_line_item_id=line.id,
        requested_by=actor_id,
        initiated_automatically=True,
        query_text=(
            f"Auto-staged ontology proposal for an unmatched priced invoice line: "
            f"{canonical_name}"
        ),
        source_allow_list_version=AUTO_STAGE_ALLOW_LIST_VERSION,
        status=ResearchStatus.PROVISIONAL,
        model_id=None,
        prompt_version="auto-stage-unmatched-line-v1",
        started_at=now,
        completed_at=now,
    )
    session.add(task)
    session.flush()

    version = _new_ontology_version(session, task, actor_id)
    canonical_identity = _canonical_identity(
        item_type=line.item_kind,
        canonical_name=canonical_name,
        category=category,
        unit=unit,
        part_number=line.part_number,
    )
    ontology_item = OntologyItem(
        canonical_code=_identity_code(canonical_identity),
        canonical_name=canonical_name,
        item_type=line.item_kind,
        category=category,
        unit=unit,
        manufacturer_part_number=line.part_number,
        description=(
            "Auto-staged proposal from an unmatched priced invoice line; "
            "awaiting handler review before it can price any comparison."
        ),
        region=effective_settings.default_jurisdiction,
        reference_price_net=price_net,
        price_vat_basis=PriceVatBasis.NET,
        currency=currency,
        price_source=AUTO_STAGED_SOURCE_TYPE,
        source_url_or_ref=f"invoice-line:{line.id}",
        effective_date=invoice.invoice_date,
        status=OntologyItemStatus.PROVISIONAL,
        approval_status=ApprovalStatus.PROVISIONAL,
        confidence_level=ConfidenceLevel.LOW,
        created_by=actor_id,
        created_in_version_id=version.id,
    )
    session.add(ontology_item)
    session.flush()

    raw_suggestion = {
        "workflow": {
            "reviewer_initiated": False,
            "initiated_automatically": True,
            "source_type": AUTO_STAGED_SOURCE_TYPE,
            "auto_stage": {
                "normalised_description": normalised_description,
                "part_number_identity": part_number_identity,
            },
        },
        "price_scope": PriceScope.UNIT.value,
        "currency": currency,
        "region": effective_settings.default_jurisdiction,
        "canonical_identity": list(canonical_identity),
        "provenance": {
            "invoice_id": invoice.id,
            "invoice_line_item_id": line.id,
            "document_id": invoice.document_id,
            "invoice_number": invoice.invoice_number,
            "source_page_id": line.source_page_id,
            "page_numbers": invoice.page_numbers_json,
            "raw_description": line.raw_description,
            "normalised_description": normalised_description,
            "part_number": line.part_number,
            "quantity": str(quantity) if quantity is not None else None,
            "unit": unit,
            "unit_price_net": price_net,
            "line_total_net": str(line_total_net),
        },
    }
    research_item = ResearchItem(
        research_task_id=task.id,
        provisional_ontology_item_id=ontology_item.id,
        suggested_canonical_name=canonical_name,
        suggested_item_type=line.item_kind,
        suggested_category=category,
        suggested_unit=unit,
        suggested_part_number=line.part_number,
        vehicle_compatibility_json=None,
        suggested_price_net=price_net,
        vat_basis=PriceVatBasis.NET,
        source_urls_json=[],
        date_checked=invoice.invoice_date,
        confidence=None,
        rationale=(
            "Machine-staged proposal: this priced invoice line had no ontology "
            "candidate meeting the mapping acceptance floor (or none in the closed "
            "ontology bank at all). A handler must review and approve before it "
            "prices any comparison."
        ),
        raw_suggestion_json=raw_suggestion,
        status=ResearchStatus.PROVISIONAL,
    )
    session.add(research_item)
    session.flush()

    evidence_row = ExternalEvidence(
        research_task_id=task.id,
        source_record_id=line.id,
        source_uri=f"invoice-line://{invoice.id}/{line.id}",
        captured_at=now,
        title=f"Invoice {invoice.invoice_number or invoice.id} line: {canonical_name[:400]}",
        minimal_excerpt=line.raw_description,
        content_hash=hashlib.sha256(f"{AUTO_STAGED_SOURCE_TYPE}:{line.id}".encode()).hexdigest(),
        part_number=line.part_number,
        fitment_json=None,
        price_net=price_net,
        currency=currency,
        vat_basis=PriceVatBasis.NET,
        unit=unit,
        validation_flags_json={
            "source_type": AUTO_STAGED_SOURCE_TYPE,
            "source_page_id": line.source_page_id,
            "invoice_id": invoice.id,
            "invoice_line_item_id": line.id,
        },
        approval_status=ApprovalStatus.PROVISIONAL,
    )
    session.add(evidence_row)
    session.flush()

    observation = PriceObservation(
        ontology_item_id=ontology_item.id,
        price_net=price_net,
        currency=currency,
        vat_basis=PriceVatBasis.NET,
        unit=unit,
        price_scope=PriceScope.UNIT,
        source_type=AUTO_STAGED_SOURCE_TYPE,
        source_record_id=line.id,
        source_url_or_ref=evidence_row.source_uri,
        observed_at=now,
        effective_from=invoice.invoice_date,
        region=effective_settings.default_jurisdiction,
        approval_status=ApprovalStatus.PROVISIONAL,
        observation_kind=PriceObservationKind.PROVISIONAL,
        evidence_id=evidence_row.id,
        created_in_version_id=version.id,
    )
    session.add(observation)
    session.flush()

    session.add(
        AuditEvent(
            case_id=case_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=actor_id,
            event_type="RESEARCH_AUTO_STAGED_FROM_UNMATCHED_LINE",
            entity_type="research_item",
            entity_id=research_item.id,
            before_json=None,
            after_json={
                "task_status": task.status.value,
                "research_item_status": research_item.status.value,
                "ontology_item_status": ontology_item.status.value,
            },
            event_payload_json={
                "research_task_id": task.id,
                "invoice_line_item_id": line.id,
                "ontology_item_id": ontology_item.id,
                "ontology_version_id": version.id,
                "source_type": AUTO_STAGED_SOURCE_TYPE,
                "normalised_description": normalised_description,
                "part_number_identity": part_number_identity,
            },
            correlation_id=task.id,
        )
    )
    session.flush()
    return research_item


def trigger_manual_research(
    session: Session,
    *,
    case_id: str,
    invoice_line_item_id: str,
    requested_by: str,
    query_text: str,
    suggestion: ResearchSuggestionInput,
    evidence: Sequence[ManualEvidenceInput],
    source_allow_list_version: str = DEFAULT_SOURCE_ALLOW_LIST_VERSION,
    allowed_source_hosts: Sequence[str] | None = None,
    settings: Settings | None = None,
) -> ResearchWorkflowResult:
    """Persist a reviewer-triggered provisional suggestion and its full lineage.

    This function intentionally has no automatic-search mode. The supplied
    evidence is treated as manual/reviewer evidence and no network request is
    made. The transaction is committed before the result is returned.
    """

    effective_settings = settings or get_settings()
    reviewer = _required_text(requested_by, "requested_by")
    query = _required_text(query_text, "query_text")
    allow_list_version = _required_text(source_allow_list_version, "source_allow_list_version")
    allowed_hosts = _resolve_allowed_hosts(
        effective_settings, allow_list_version, allowed_source_hosts
    )
    price_net, source_urls, source_hosts, content_hashes = _validate_inputs(
        suggestion, evidence, allowed_hosts
    )

    line = session.scalar(
        select(InvoiceLineItem)
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .where(
            InvoiceLineItem.id == invoice_line_item_id,
            Invoice.case_id == case_id,
        )
    )
    if line is None:
        raise ResearchWorkflowError(
            "INVOICE_LINE_NOT_FOUND", "invoice line is not part of the supplied case"
        )
    approved_task = session.scalar(
        select(ResearchTask).where(
            ResearchTask.invoice_line_item_id == invoice_line_item_id,
            ResearchTask.status == ResearchStatus.APPROVED,
        )
    )
    if approved_task is not None:
        raise ResearchWorkflowError(
            "RESEARCH_ALREADY_APPROVED_FOR_LINE",
            "this invoice line already has an approved research outcome",
        )
    # Task B2 auto-stages a provisional proposal for any priced line with no
    # accepted mapping. That machine-initiated task must not block a reviewer
    # from independently researching the same line, so only an open
    # reviewer-initiated task counts as "already open" here.
    open_task = session.scalar(
        select(ResearchTask).where(
            ResearchTask.invoice_line_item_id == invoice_line_item_id,
            ResearchTask.status.in_(_OPEN_RESEARCH_STATUSES),
            ResearchTask.initiated_automatically.is_(False),
        )
    )
    if open_task is not None:
        raise ResearchWorkflowError(
            "RESEARCH_ALREADY_OPEN",
            "this invoice line already has an open research task",
        )
    _ensure_unique_research_identity(session, suggestion)
    _ensure_unique_evidence_content(session, content_hashes)
    canonical_identity = _suggestion_identity(suggestion)

    now = utc_now()
    task = ResearchTask(
        case_id=case_id,
        invoice_line_item_id=invoice_line_item_id,
        requested_by=reviewer,
        initiated_automatically=False,
        query_text=query,
        source_allow_list_version=allow_list_version,
        status=ResearchStatus.PROVISIONAL,
        model_id="manual-evidence-pilot",
        prompt_version="research-manual-v1",
        started_at=now,
        completed_at=now,
    )
    session.add(task)

    try:
        session.flush()
        version = _new_ontology_version(session, task, reviewer)
        ontology_item = OntologyItem(
            canonical_code=_identity_code(canonical_identity),
            canonical_name=suggestion.canonical_name.strip(),
            item_type=suggestion.item_type,
            category=suggestion.category.strip(),
            unit=suggestion.unit.strip(),
            manufacturer_part_number=(
                suggestion.part_number.strip() if suggestion.part_number else None
            ),
            quality_tier=suggestion.quality_tier,
            description=suggestion.rationale.strip(),
            region=suggestion.region.strip().upper(),
            reference_price_net=price_net,
            price_vat_basis=suggestion.vat_basis,
            currency=suggestion.currency.strip().upper(),
            price_source="reviewer_initiated_manual_research",
            source_url_or_ref=source_urls[0],
            effective_date=suggestion.date_checked,
            status=OntologyItemStatus.PROVISIONAL,
            approval_status=ApprovalStatus.PROVISIONAL,
            confidence_level=_confidence_level(suggestion.confidence),
            created_by=reviewer,
            created_in_version_id=version.id,
        )
        session.add(ontology_item)
        session.flush()

        raw_suggestion = {
            "workflow": {
                "reviewer_initiated": True,
                "auto_research_enabled": effective_settings.auto_research,
                "two_step_approval": effective_settings.two_step_approval,
                "source_allow_list_version": allow_list_version,
                "allowed_source_hosts": list(allowed_hosts),
                "validated_source_hosts": source_hosts,
            },
            "price_scope": suggestion.price_scope.value,
            "currency": suggestion.currency.strip().upper(),
            "region": suggestion.region.strip().upper(),
            "quality_tier": suggestion.quality_tier,
            "canonical_identity": list(canonical_identity),
            "canonical_identity_hash": hashlib.sha256(
                "\x1f".join(canonical_identity).encode("utf-8")
            ).hexdigest(),
        }
        research_item = ResearchItem(
            research_task_id=task.id,
            provisional_ontology_item_id=ontology_item.id,
            suggested_canonical_name=suggestion.canonical_name.strip(),
            suggested_item_type=suggestion.item_type,
            suggested_category=suggestion.category.strip(),
            suggested_unit=suggestion.unit.strip(),
            suggested_part_number=(
                suggestion.part_number.strip() if suggestion.part_number else None
            ),
            vehicle_compatibility_json=suggestion.vehicle_compatibility,
            suggested_price_net=price_net,
            vat_basis=suggestion.vat_basis,
            source_urls_json=source_urls,
            date_checked=suggestion.date_checked,
            confidence=suggestion.confidence,
            rationale=suggestion.rationale.strip(),
            raw_suggestion_json=raw_suggestion,
            status=ResearchStatus.PROVISIONAL,
        )
        session.add(research_item)
        session.flush()

        persisted_evidence: list[ExternalEvidence] = []
        for source, content_hash in zip(evidence, content_hashes, strict=True):
            source_uri = _validate_url(source.source_uri)
            captured_at = source.captured_at or datetime.now(UTC)
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=UTC)
            row = ExternalEvidence(
                research_task_id=task.id,
                source_record_id=source.source_record_id,
                source_uri=source_uri,
                captured_at=captured_at,
                title=source.title.strip(),
                minimal_excerpt=source.minimal_excerpt,
                content_hash=content_hash,
                part_number=source.part_number,
                fitment_json=source.fitment,
                price_net=_optional_money(source.price_net, "evidence.price_net"),
                original_price=_optional_money(source.original_price, "evidence.original_price"),
                currency=source.currency.strip().upper(),
                vat_basis=source.vat_basis,
                unit=source.unit,
                quality_tier=source.quality_tier,
                condition=source.condition,
                shipping=_optional_money(source.shipping, "evidence.shipping"),
                stock_status=source.stock_status,
                validation_flags_json={
                    **(source.validation_flags or {}),
                    "allow_list_match": True,
                    "allow_list_version": allow_list_version,
                    "validated_host": _source_host(source_uri),
                },
                approval_status=ApprovalStatus.PROVISIONAL,
            )
            session.add(row)
            persisted_evidence.append(row)
        session.flush()

        observations: list[PriceObservation] = []
        for index, (source, evidence_row) in enumerate(
            zip(evidence, persisted_evidence, strict=True)
        ):
            observation_price = source.price_net
            if observation_price is None and index == 0:
                observation_price = suggestion.price_net
            if observation_price is None:
                continue
            observation = PriceObservation(
                ontology_item_id=ontology_item.id,
                price_net=_money(observation_price, "evidence.price_net"),
                original_price=_optional_money(source.original_price, "evidence.original_price"),
                currency=source.currency.strip().upper(),
                vat_basis=source.vat_basis,
                unit=source.unit or suggestion.unit.strip(),
                price_scope=suggestion.price_scope,
                source_type="reviewer_initiated_manual_research",
                source_record_id=source.source_record_id or evidence_row.id,
                source_url_or_ref=evidence_row.source_uri,
                observed_at=evidence_row.captured_at,
                effective_from=suggestion.date_checked,
                region=suggestion.region.strip().upper(),
                quality_tier=source.quality_tier or suggestion.quality_tier,
                condition=source.condition,
                shipping_included=(
                    source.shipping is not None
                    and Decimal(_money(source.shipping, "evidence.shipping")) == 0
                ),
                approval_status=ApprovalStatus.PROVISIONAL,
                observation_kind=PriceObservationKind.PROVISIONAL,
                evidence_id=evidence_row.id,
                created_in_version_id=version.id,
            )
            session.add(observation)
            observations.append(observation)
        session.flush()

        session.add(
            AuditEvent(
                case_id=case_id,
                actor_type=AuditActorType.USER,
                actor_id=reviewer,
                event_type="RESEARCH_TRIGGERED_BY_REVIEWER",
                entity_type="research_item",
                entity_id=research_item.id,
                before_json=None,
                after_json={
                    "task_status": task.status.value,
                    "research_item_status": research_item.status.value,
                    "ontology_item_status": ontology_item.status.value,
                    "source_urls": source_urls,
                    "date_checked": suggestion.date_checked.isoformat(),
                    "confidence": suggestion.confidence,
                },
                event_payload_json={
                    "research_task_id": task.id,
                    "invoice_line_item_id": invoice_line_item_id,
                    "ontology_item_id": ontology_item.id,
                    "ontology_version_id": version.id,
                    "canonical_identity": list(canonical_identity),
                    "evidence_ids": [row.id for row in persisted_evidence],
                    "price_observation_ids": [row.id for row in observations],
                    "initiated_automatically": False,
                    "auto_research_enabled": effective_settings.auto_research,
                    "source_allow_list_version": allow_list_version,
                    "allowed_source_hosts": list(allowed_hosts),
                    "validated_source_hosts": source_hosts,
                },
                correlation_id=task.id,
            )
        )
        session.flush()
        result = _workflow_result(
            session,
            research_item,
            status="provisional",
            second_review_required=effective_settings.two_step_approval,
            next_action="handler_approval",
        )
        session.commit()
        return result
    except IntegrityError as exc:
        session.rollback()
        raise ResearchWorkflowError(
            "RESEARCH_PERSISTENCE_CONFLICT",
            "the research suggestion conflicted with an existing governed record",
        ) from exc


def _load_research_item(session: Session, research_item_id: str) -> ResearchItem:
    item = session.scalar(
        select(ResearchItem)
        .where(ResearchItem.id == research_item_id)
        .options(selectinload(ResearchItem.research_task).selectinload(ResearchTask.evidence))
    )
    if item is None:
        raise ResearchWorkflowError("RESEARCH_ITEM_NOT_FOUND", "research item was not found")
    return item


def _ensure_item_can_be_promoted(session: Session, item: ResearchItem) -> None:
    identity = _research_identity(item)
    approved_items = session.scalars(
        select(OntologyItem).where(
            OntologyItem.item_type == item.suggested_item_type,
            OntologyItem.approval_status == ApprovalStatus.APPROVED,
            OntologyItem.id != item.provisional_ontology_item_id,
        )
    ).all()
    for approved_item in approved_items:
        if _ontology_identity(approved_item) == identity:
            raise ResearchWorkflowError(
                "ONTOLOGY_ITEM_ALREADY_APPROVED",
                f"canonical identity already exists as approved item {approved_item.canonical_code}",
            )


def _promote_to_bank(
    session: Session,
    item: ResearchItem,
    *,
    approved_by: str,
    reviewer_note: str | None,
    approved_at: datetime,
) -> None:
    ontology_item = session.get(OntologyItem, item.provisional_ontology_item_id)
    if ontology_item is None:
        raise ResearchWorkflowError(
            "ONTOLOGY_ITEM_NOT_FOUND",
            "the provisional ontology item linked to this research item is missing",
        )
    version = session.get(OntologyVersion, ontology_item.created_in_version_id)
    if version is None:
        raise ResearchWorkflowError(
            "ONTOLOGY_VERSION_NOT_FOUND", "the research ontology version is missing"
        )

    item.status = ResearchStatus.APPROVED
    item.reviewer = approved_by
    item.reviewed_at = approved_at
    item.reviewer_note = reviewer_note
    item.research_task.status = ResearchStatus.APPROVED
    item.research_task.completed_at = approved_at
    ontology_item.status = OntologyItemStatus.APPROVED
    ontology_item.approval_status = ApprovalStatus.APPROVED
    version.status = OntologyVersionStatus.PUBLISHED
    version.published_at = approved_at

    for source in item.research_task.evidence:
        source.approval_status = ApprovalStatus.APPROVED
    observations = list(
        session.scalars(
            select(PriceObservation).where(PriceObservation.ontology_item_id == ontology_item.id)
        ).all()
    )
    for observation in observations:
        observation.approval_status = ApprovalStatus.APPROVED
        observation.observation_kind = PriceObservationKind.MARKET


def refresh_comparison_after_research(
    session: Session,
    item: ResearchItem,
    *,
    approved_by: str,
) -> ComparisonRefreshResult:
    """Create an immutable reprocess snapshot and force-map the researched line.

    Existing extraction, mapping, comparison, and challenge rows remain attached
    to the previous processing run. The case is advanced to a new reprocess run,
    so the approved ontology version and recomputed price evidence are auditable.
    """

    task = item.research_task
    case = session.get(Case, task.case_id)
    if case is None:
        raise ResearchWorkflowError("CASE_NOT_FOUND", "research case was not found")
    previous_run = (
        session.get(ProcessingRun, case.current_processing_run_id)
        if case.current_processing_run_id is not None
        else None
    )
    if previous_run is None or previous_run.status != RunStatus.SUCCEEDED:
        return {
            "status": "skipped_no_completed_run",
            "previous_processing_run_id": case.current_processing_run_id,
            "processing_run_id": None,
            "mapping_run_id": None,
            "ontology_mapping_id": None,
            "reason": "case has no completed extraction run to reprocess",
        }
    line = session.get(InvoiceLineItem, task.invoice_line_item_id)
    invoice = session.get(Invoice, line.invoice_id) if line is not None else None
    if (
        line is None
        or invoice is None
        or line.line_total_net is None
        or invoice.invoice_date is None
    ):
        return {
            "status": "skipped_source_line_not_comparable",
            "previous_processing_run_id": previous_run.id,
            "processing_run_id": None,
            "mapping_run_id": None,
            "ontology_mapping_id": None,
            "reason": "source line lacks an invoice date or net line total",
        }
    ontology_item = session.get(OntologyItem, item.provisional_ontology_item_id)
    if ontology_item is None or ontology_item.approval_status != ApprovalStatus.APPROVED:
        raise ResearchWorkflowError(
            "ONTOLOGY_ITEM_NOT_APPROVED",
            "comparison refresh requires the researched ontology item to be approved",
        )

    now = utc_now()
    configuration_hash = hashlib.sha256(
        ":".join(
            (
                previous_run.configuration_hash,
                ontology_item.created_in_version_id,
                task.id,
            )
        ).encode("utf-8")
    ).hexdigest()
    source_versions = list(previous_run.source_import_versions_json or [])
    source_versions.append(
        {
            "kind": "reviewer_research_ontology",
            "ontology_version_id": ontology_item.created_in_version_id,
            "research_task_id": task.id,
        }
    )
    metrics = dict(previous_run.metrics_json or {})
    metrics.update(
        {
            "reused_extraction_run_id": previous_run.id,
            "research_task_id": task.id,
            "research_invoice_line_item_id": line.id,
        }
    )
    refresh_run = ProcessingRun(
        case_id=case.id,
        run_type=RunType.REPROCESS,
        application_version=previous_run.application_version,
        configuration_hash=configuration_hash,
        ontology_version_id=ontology_item.created_in_version_id,
        benchmark_policy_version=previous_run.benchmark_policy_version,
        policy_config_version_id=previous_run.policy_config_version_id,
        model_provider=previous_run.model_provider,
        model_id=previous_run.model_id,
        prompt_version=previous_run.prompt_version,
        extraction_version=previous_run.extraction_version,
        started_at=now,
        completed_at=now,
        status=RunStatus.SUCCEEDED,
        metrics_json=metrics,
        source_import_versions_json=source_versions,
    )
    session.add(refresh_run)
    session.flush()
    case.current_processing_run_id = refresh_run.id
    session.flush()

    approved_research_items = session.scalars(
        select(ResearchItem)
        .join(ResearchTask, ResearchTask.id == ResearchItem.research_task_id)
        .where(
            ResearchTask.case_id == case.id,
            ResearchItem.status == ResearchStatus.APPROVED,
        )
        .options(selectinload(ResearchItem.research_task))
    ).all()
    mapping_overrides: dict[str, MappingOverride] = {}
    for approved_item in approved_research_items:
        if approved_item.provisional_ontology_item_id is None:
            continue
        mapping_overrides[approved_item.research_task.invoice_line_item_id] = MappingOverride(
            ontology_item_id=approved_item.provisional_ontology_item_id,
            actor_id=approved_item.reviewer or approved_by,
            rationale=(
                "Handler-approved reviewer research; source line remapped to its "
                f"bank item from task {approved_item.research_task.id}."
            ),
        )
    comparison = run_case_comparison(
        session,
        case,
        mapping_overrides=mapping_overrides,
    )
    mapping_run_id = comparison.get("mapping_run_id")
    mapping = session.scalar(
        select(OntologyMapping).where(
            OntologyMapping.mapping_run_id == mapping_run_id,
            OntologyMapping.invoice_line_item_id == line.id,
        )
    )
    if mapping is None or mapping.selected_ontology_item_id != ontology_item.id:
        raise ResearchWorkflowError(
            "RESEARCH_COMPARISON_REFRESH_FAILED",
            "the refreshed comparison did not preserve the approved line mapping",
        )
    result: ComparisonRefreshResult = {
        "status": "recomputed",
        "previous_processing_run_id": previous_run.id,
        "processing_run_id": refresh_run.id,
        "mapping_run_id": mapping_run_id,
        "ontology_mapping_id": mapping.id,
        "reason": "approved research mapping applied and case comparison recomputed",
    }
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=refresh_run.id,
            actor_type=AuditActorType.SYSTEM,
            actor_id="claimguard.research-comparison-refresh",
            event_type="RESEARCH_COMPARISON_REFRESHED",
            entity_type="invoice_line_item",
            entity_id=line.id,
            before_json={
                "processing_run_id": previous_run.id,
                "ontology_item_id": None,
            },
            after_json={
                "processing_run_id": refresh_run.id,
                "ontology_item_id": ontology_item.id,
                "ontology_mapping_id": mapping.id,
            },
            event_payload_json={
                "approved_by": approved_by,
                "research_task_id": task.id,
                "ontology_version_id": ontology_item.created_in_version_id,
                "comparison_result": comparison,
            },
            correlation_id=task.id,
        )
    )
    return result


def approve_research_item(
    session: Session,
    *,
    research_item_id: str,
    approved_by: str,
    reviewer_note: str | None = None,
    settings: Settings | None = None,
) -> ResearchWorkflowResult:
    """Record one-click approval and promote when the configured gate is met."""

    effective_settings = settings or get_settings()
    approver = _required_text(approved_by, "approved_by")
    item = _load_research_item(session, research_item_id)
    task = item.research_task

    if item.status == ResearchStatus.APPROVED:
        return _workflow_result(
            session,
            item,
            status="approved",
            second_review_required=False,
            next_action="none",
        )
    if item.status != ResearchStatus.PROVISIONAL:
        raise ResearchWorkflowError(
            "RESEARCH_ITEM_NOT_APPROVABLE",
            f"research item in {item.status.value} status cannot be approved",
        )

    now = utc_now()
    raw = dict(item.raw_suggestion_json or {})
    approval_workflow = dict(raw.get("approval_workflow") or {})
    first_approved_by = approval_workflow.get("first_approved_by")

    if effective_settings.two_step_approval and first_approved_by is None:
        approval_workflow.update(
            {
                "first_approved_by": approver,
                "first_approved_at": now.isoformat(),
                "first_reviewer_note": reviewer_note,
                "second_review_required": True,
            }
        )
        raw["approval_workflow"] = approval_workflow
        item.raw_suggestion_json = raw
        item.reviewer = approver
        item.reviewed_at = now
        item.reviewer_note = reviewer_note
        session.add(
            AuditEvent(
                case_id=task.case_id,
                actor_type=AuditActorType.USER,
                actor_id=approver,
                event_type="RESEARCH_FIRST_APPROVAL_RECORDED",
                entity_type="research_item",
                entity_id=item.id,
                before_json={"status": ResearchStatus.PROVISIONAL.value},
                after_json={
                    "status": ResearchStatus.PROVISIONAL.value,
                    "second_review_required": True,
                },
                event_payload_json={
                    "research_task_id": task.id,
                    "ontology_item_id": item.provisional_ontology_item_id,
                    "first_approved_by": approver,
                    "source_urls": list(item.source_urls_json),
                    "date_checked": item.date_checked.isoformat(),
                    "confidence": item.confidence,
                },
                correlation_id=task.id,
            )
        )
        session.flush()
        result = _workflow_result(
            session,
            item,
            status="awaiting_second_review",
            second_review_required=True,
            next_action="second_review",
        )
        session.commit()
        return result

    if effective_settings.two_step_approval and first_approved_by == approver:
        raise ResearchWorkflowError(
            "SECOND_REVIEWER_MUST_DIFFER",
            "the second approval must be performed by a different reviewer",
        )

    before = {
        "research_item_status": item.status.value,
        "ontology_item_status": OntologyItemStatus.PROVISIONAL.value,
    }
    approval_workflow.update(
        {
            "first_approved_by": first_approved_by or approver,
            "first_approved_at": approval_workflow.get("first_approved_at") or now.isoformat(),
            "second_review_required": effective_settings.two_step_approval,
            "final_approved_by": approver,
            "final_approved_at": now.isoformat(),
        }
    )
    raw["approval_workflow"] = approval_workflow
    item.raw_suggestion_json = raw
    try:
        _ensure_item_can_be_promoted(session, item)
        _promote_to_bank(
            session,
            item,
            approved_by=approver,
            reviewer_note=reviewer_note,
            approved_at=now,
        )
        session.flush()
        comparison_refresh = refresh_comparison_after_research(session, item, approved_by=approver)
        approval_workflow["comparison_refresh"] = comparison_refresh
        raw["approval_workflow"] = approval_workflow
        item.raw_suggestion_json = raw
        session.add(
            AuditEvent(
                case_id=task.case_id,
                actor_type=AuditActorType.USER,
                actor_id=approver,
                event_type="RESEARCH_ITEM_APPROVED_TO_BANK",
                entity_type="ontology_item",
                entity_id=item.provisional_ontology_item_id,
                before_json=before,
                after_json={
                    "research_item_status": ResearchStatus.APPROVED.value,
                    "ontology_item_status": OntologyItemStatus.APPROVED.value,
                    "approval_status": ApprovalStatus.APPROVED.value,
                    "comparison_refresh": comparison_refresh,
                },
                event_payload_json={
                    "research_task_id": task.id,
                    "research_item_id": item.id,
                    "source_urls": list(item.source_urls_json),
                    "date_checked": item.date_checked.isoformat(),
                    "confidence": item.confidence,
                    "two_step_approval": effective_settings.two_step_approval,
                    "first_approved_by": approval_workflow["first_approved_by"],
                    "final_approved_by": approver,
                    "comparison_refresh": comparison_refresh,
                },
                correlation_id=task.id,
            )
        )
        session.flush()
        result = _workflow_result(
            session,
            item,
            status="approved",
            second_review_required=False,
            next_action="none",
            comparison_refresh=comparison_refresh,
        )
        session.commit()
        return result
    except ResearchWorkflowError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        raise ResearchWorkflowError(
            "RESEARCH_APPROVAL_CONFLICT",
            "the researched item could not be promoted because of a persistence conflict",
        ) from exc
    except ValueError as exc:
        session.rollback()
        raise ResearchWorkflowError(
            "RESEARCH_COMPARISON_REFRESH_FAILED",
            f"the researched item could not refresh comparison: {exc}",
        ) from exc
