from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import (
    AssessmentMappingOverrideRequest,
    CaseDataResetRequest,
    ClaimCreateRequest,
    ExtractionDecisionRequest,
    FinaliseCaseRequest,
    InvoiceLineCorrectionRequest,
    InvoiceLineManualCreateRequest,
    LiabilityDecisionRequest,
    ManualResearchRequest,
    MappingApprovalRequest,
    MappingDecisionRequest,
    PageCorrectionRequest,
    ReprocessCaseRequest,
    ResearchItemApprovalRequest,
    ReviewDecisionRequest,
    SeedImportRequest,
    SettlementCreateRequest,
    VehicleClassificationRequest,
)
from app.config import BACKEND_DIR, get_settings
from app.database import get_db
from app.domain.liability import LiabilityState, liability_gate
from app.domain.normalisation import normalise_description, normalise_unit
from app.domain.price_decision import DEFAULT_POLICY as DEFAULT_P90_POLICY
from app.enums import (
    ApprovalStatus,
    AuditActorType,
    CaseStatus,
    ChallengeStatus,
    ClaimPartyRole,
    ClaimVehicleRole,
    DocumentRole,
    ExtractionMethod,
    LiabilityGateStatus,
    LiabilityStatus,
    LineItemKind,
    PriceScope,
    PriceVatBasis,
    ReviewStatus,
    SettlementStatus,
    UploadStatus,
)
from app.exports import (
    ExportValidationError,
    backup_sqlite,
    build_case_workbook,
    build_json_bytes,
    build_negotiation_docx,
    build_negotiation_pdf,
)
from app.llm.factory import build_mapping_adjudicator
from app.models import (
    AssessmentOperation,
    AuditEvent,
    Case,
    ChallengeResult,
    ClaimContext,
    ClaimParty,
    ClaimVehicle,
    Document,
    DocumentPage,
    EngineerAssessment,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    LiabilityAssessment,
    OntologyItem,
    OntologyMapping,
    PriceComparison,
    Settlement,
    Vehicle,
)
from app.reset import CONFIRMATION_PHRASE, clear_reset_paths, reset_case_data
from app.services.benchmarking import (
    benchmark_observations,
    build_benchmark_dashboard,
    sync_finalised_case_to_benchmarks,
)
from app.services.case_result import (
    build_case_result,
    build_claim_workspace,
    build_line_price_evidence,
    build_uploaded_batch_benchmark_dashboard,
)
from app.services.comparison_workflow import run_case_comparison
from app.services.document_mapping import (
    DocumentMappingError,
    approve_case_mapping,
    case_mapping_payload,
    override_assessment_pairing,
)
from app.services.document_processing import process_document, serialise_document, store_pdf
from app.services.engineer_assessment import (
    engineer_assessment_payload,
    manual_override_payload,
    run_case_gap_fill,
    section_breakdown_for_invoice,
)
from app.services.extraction_review import (
    recalculate_invoice_findings,
    review_extraction_line,
)
from app.services.knowledge_graph import build_challenge_knowledge_graph, sync_to_neo4j
from app.services.mapping_review import (
    BundleComponentDecision,
    MappingReviewCommand,
    MappingReviewError,
    refresh_invoice_rollup,
    review_line_mapping,
)
from app.services.page_correction import (
    PageCorrectionCommand,
    PageCorrectionError,
    correct_document_page,
)
from app.services.reprocessing import reprocess_case
from app.services.research_workflow import (
    ManualEvidenceInput,
    ResearchSuggestionInput,
    ResearchWorkflowError,
    approve_research_item,
    trigger_manual_research,
)
from app.services.seed_import_service import import_seed_workbooks
from app.services.vehicle_category_lookup import lookup_vehicle_category
from app.services.vehicle_classification import (
    apply_vehicle_classification,
    normalise_registration,
    validate_vehicle_classification,
)

logger = logging.getLogger(__name__)

router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db)]
_RESEARCH_CONFLICT_CODES = frozenset(
    {
        "RESEARCH_ALREADY_OPEN",
        "RESEARCH_ALREADY_APPROVED_FOR_LINE",
        "ONTOLOGY_ITEM_ALREADY_APPROVED",
        "RESEARCH_IDENTITY_ALREADY_OPEN",
        "EVIDENCE_CONTENT_ALREADY_RESEARCHED",
        "DUPLICATE_EVIDENCE_IN_REQUEST",
    }
)


@router.get("/readiness", tags=["system"])
def data_readiness(db: DatabaseSession) -> dict[str, Any]:
    ontology_items = db.scalar(select(func.count(OntologyItem.id))) or 0
    historical_claims = db.scalar(select(func.count(HistoricalObservation.id))) or 0
    return {
        "ready": ontology_items > 0 and historical_claims > 0,
        "ontology_items": ontology_items,
        "historical_claims": historical_claims,
        "issues": [
            message
            for count, message in (
                (
                    ontology_items,
                    "Ontology bank is empty. Run the seed import before comparison.",
                ),
                (
                    historical_claims,
                    "Historical claims bank is empty. Run the seed import before comparison.",
                ),
            )
            if count == 0
        ],
    }


@router.get("/vehicle-categories/lookup", tags=["benchmarks"])
def vehicle_category_lookup(
    db: DatabaseSession,
    make: Annotated[str, Query(min_length=1)],
    model: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    match = lookup_vehicle_category(db, make=make, model=model)
    if match is None:
        return {
            "matched": False,
            "make": make,
            "model": model,
            "status": "manual_review",
        }
    return {
        "matched": True,
        "make": make,
        "model": model,
        "group_range": match.group_range,
        "group_category": match.group_category,
        "body_type": match.body_type,
        "fuel_type": match.fuel_type,
        "source": match.source,
        "matched_make": match.matched_make,
        "matched_model": match.matched_model,
        "status": match.match_status,
    }


def _not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": entity})


def _liability_value(value: str) -> LiabilityStatus:
    normalised = value.strip().upper().replace(" ", "_")
    try:
        return LiabilityStatus(normalised)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_LIABILITY_STATUS", "message": value},
        ) from exc


def _liability_display(value: LiabilityStatus | None) -> str:
    return (value.value if value else "HUMAN_REVIEW_REQUIRED").replace("_", " ")


def _page_payload(page: DocumentPage) -> dict[str, Any]:
    document_metadata = page.document.metadata_json or {}
    correction = (document_metadata.get("page_corrections") or {}).get(str(page.page_number))
    return {
        "id": page.id,
        "document_id": page.document_id,
        "document_filename": page.document.original_filename,
        "page_number": page.page_number,
        "width": page.width,
        "height": page.height,
        "page_type": page.page_type.value,
        "classification_confidence": page.classification_confidence,
        "classification_source": "handler" if correction else "pipeline",
        "extraction_method": page.extraction_method.value,
        "rotation": page.rotation,
        "group_id": page.group_id,
        "review_status": page.review_status.value,
        "reprocess_required": bool(document_metadata.get("reprocess_required")),
        "correction": correction,
        "image_url": f"/api/v1/pages/{page.id}/image",
    }


def _case_query():
    return select(Case).options(
        selectinload(Case.claim_context).selectinload(ClaimContext.parties),
        selectinload(Case.claim_context).selectinload(ClaimContext.vehicles),
        selectinload(Case.claim_context).selectinload(ClaimContext.liability_assessments),
        selectinload(Case.claim_context).selectinload(ClaimContext.consistency_findings),
        selectinload(Case.documents).selectinload(Document.pages),
        selectinload(Case.invoices).selectinload(Invoice.vehicle),
        selectinload(Case.invoices).selectinload(Invoice.line_items),
        selectinload(Case.invoices).selectinload(Invoice.math_findings),
    )


def _case_payload(case: Case) -> dict[str, Any]:
    context = case.claim_context
    assessments = context.liability_assessments if context else []
    latest = max(assessments, key=lambda item: item.created_at) if assessments else None
    return {
        "id": case.id,
        "case_reference": case.case_reference,
        "status": case.status.value,
        "created_by": case.created_by,
        "created_at": case.created_at.isoformat(),
        "claim": (
            {
                "claim_number": context.claim_number,
                "paying_insurer_name": context.paying_insurer_name,
                "claiming_insurer_name": context.claiming_insurer_name,
                "third_party_name": context.third_party_name,
                "paying_policy_number": context.paying_policy_number,
                "claiming_policy_number": context.claiming_policy_number,
                "accident_at": context.accident_at.isoformat() if context.accident_at else None,
                "accident_location": context.accident_location,
                "accident_description": context.accident_description,
                "damage_description": context.damage_description,
                "human_confirmed": context.human_confirmed,
                "liability_gate_status": context.liability_gate_status.value,
                "liability_status": _liability_display(latest.effective_status if latest else None),
                "parties": [
                    {
                        "id": party.id,
                        "role": party.party_role.value,
                        "name": party.name,
                        "insurer_name": party.insurer_name,
                        "policy_number": party.policy_number,
                    }
                    for party in context.parties
                ],
                "vehicles": [
                    {
                        "id": vehicle.id,
                        "role": vehicle.vehicle_role.value,
                        "registration": vehicle.registration,
                        "vin": vehicle.vin,
                        "make": vehicle.make,
                        "model": vehicle.model,
                        "variant": vehicle.variant,
                        "damage_description": vehicle.damage_description,
                    }
                    for vehicle in context.vehicles
                ],
                "consistency_findings": [
                    {
                        "id": finding.id,
                        "code": finding.finding_code,
                        "severity": finding.severity.value,
                        "status": finding.status.value,
                        "explanation": finding.explanation,
                    }
                    for finding in context.consistency_findings
                ],
            }
            if context
            else None
        ),
        "documents": [serialise_document(document) for document in case.documents],
        "invoice_count": len(case.invoices),
    }


@router.post("/claims", status_code=status.HTTP_201_CREATED, tags=["claims"])
@router.post("/cases", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_claim(request: ClaimCreateRequest, db: DatabaseSession) -> dict[str, Any]:
    if db.scalar(select(Case).where(Case.case_reference == request.case_reference)):
        raise HTTPException(status_code=409, detail={"code": "CASE_EXISTS"})
    case = Case(
        case_reference=request.case_reference,
        status=CaseStatus.CLAIM_REVIEW,
        created_by=request.created_by,
        notes=request.notes,
    )
    db.add(case)
    db.flush()
    context = ClaimContext(
        case_id=case.id,
        claim_number=request.claim_number,
        paying_insurer_name=request.paying_insurer_name,
        claiming_insurer_name=request.claiming_insurer_name,
        third_party_name=request.third_party_name,
        paying_policy_number=request.paying_policy_number,
        claiming_policy_number=request.claiming_policy_number,
        accident_at=request.accident_at,
        accident_location=request.accident_location,
        accident_description=request.accident_description,
        damage_description=request.damage_description,
        liability_gate_status=LiabilityGateStatus.AWAITING_HUMAN_REVIEW,
        human_confirmed=False,
    )
    db.add(context)
    db.flush()
    for party in request.parties:
        try:
            role = ClaimPartyRole(party.role)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid party role: {party.role}"
            ) from exc
        db.add(
            ClaimParty(
                claim_context_id=context.id,
                party_role=role,
                name=party.name,
                insurer_name=party.insurer_name,
                policy_number=party.policy_number,
                address=party.address,
                review_status=ReviewStatus.PENDING,
            )
        )
    for vehicle in request.vehicles:
        try:
            role = ClaimVehicleRole(vehicle.role)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid vehicle role: {vehicle.role}"
            ) from exc
        try:
            classification = validate_vehicle_classification(
                official_vehicle_class=vehicle.official_vehicle_class,
                bodywork_code=vehicle.bodywork_code,
                market_segment=vehicle.market_segment,
                classification_source=vehicle.classification_source,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_VEHICLE_CLASSIFICATION", "message": str(exc)},
            ) from exc
        db.add(
            ClaimVehicle(
                claim_context_id=context.id,
                vehicle_role=role,
                registration=vehicle.registration,
                vin=vehicle.vin,
                make=vehicle.make,
                model=vehicle.model,
                variant=vehicle.variant,
                manufacture_year=vehicle.manufacture_year,
                official_vehicle_class=classification.official_vehicle_class,
                bodywork_code=classification.bodywork_code,
                market_segment=classification.market_segment,
                classification_source=classification.classification_source,
                policy_number=vehicle.policy_number,
                insurer_name=vehicle.insurer_name,
                damage_description=vehicle.damage_description,
                review_status=ReviewStatus.PENDING,
            )
        )
    db.add(
        AuditEvent(
            case_id=case.id,
            actor_type=AuditActorType.USER,
            actor_id=request.created_by,
            event_type="CLAIM_CREATED",
            entity_type="case",
            entity_id=case.id,
            after_json=request.model_dump(mode="json"),
            event_payload_json={"liability_gate_required": True},
        )
    )
    db.commit()
    loaded = db.scalar(_case_query().where(Case.id == case.id))
    return _case_payload(loaded)


@router.get("/claims", tags=["claims"])
def list_claims(db: DatabaseSession) -> list[dict[str, Any]]:
    cases = db.scalars(_case_query().order_by(Case.created_at.desc())).unique().all()
    return [_case_payload(case) for case in cases]


@router.get("/claims/{case_reference}", tags=["claims"])
def get_claim(case_reference: str, db: DatabaseSession) -> dict[str, Any]:
    case = db.scalar(_case_query().where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    return _case_payload(case)


@router.patch("/claims/{case_reference}/vehicle-classification", tags=["claims"])
def update_vehicle_classification(
    case_reference: str,
    request: VehicleClassificationRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Apply a sourced classification to matching claim and extracted vehicles."""

    case = db.scalar(_case_query().where(Case.case_reference == case_reference))
    if case is None or case.claim_context is None:
        raise _not_found("Claim context not found")
    try:
        classification = validate_vehicle_classification(
            official_vehicle_class=request.official_vehicle_class,
            bodywork_code=request.bodywork_code,
            market_segment=request.market_segment,
            classification_source=request.classification_source,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_VEHICLE_CLASSIFICATION", "message": str(exc)},
        ) from exc

    registration = normalise_registration(request.registration)
    claim_vehicles = [
        vehicle
        for vehicle in case.claim_context.vehicles
        if normalise_registration(vehicle.registration) == registration
    ]
    invoice_vehicles = [
        vehicle
        for vehicle in db.scalars(select(Vehicle).where(Vehicle.case_id == case.id)).all()
        if normalise_registration(vehicle.registration) == registration
    ]
    matches = [*claim_vehicles, *invoice_vehicles]
    if not matches:
        raise _not_found("Vehicle registration not found on this claim")
    for vehicle in matches:
        apply_vehicle_classification(vehicle, classification)

    db.add(
        AuditEvent(
            case_id=case.id,
            actor_type=AuditActorType.USER,
            actor_id=request.verified_by,
            event_type="VEHICLE_CLASSIFICATION_VERIFIED",
            entity_type="vehicle",
            entity_id=request.registration,
            before_json=None,
            after_json={
                "registration": request.registration,
                "official_vehicle_class": classification.official_vehicle_class,
                "bodywork_code": classification.bodywork_code,
                "market_segment": classification.market_segment,
                "classification_source": classification.classification_source,
                "classification_label": classification.label,
            },
            event_payload_json={"records_updated": len(matches), "source_required": True},
        )
    )
    db.commit()
    return {
        "registration": request.registration,
        "classification_label": classification.label,
        "records_updated": len(matches),
    }


@router.post("/claims/{case_reference}/liability/confirm", tags=["liability"])
def confirm_liability(
    case_reference: str,
    request: LiabilityDecisionRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    case = db.scalar(_case_query().where(Case.case_reference == case_reference))
    if case is None or case.claim_context is None:
        raise _not_found("Claim context not found")
    context = case.claim_context
    status_value = _liability_value(request.status)
    previous = (
        max(context.liability_assessments, key=lambda item: item.created_at)
        if context.liability_assessments
        else None
    )
    assessment = LiabilityAssessment(
        claim_context_id=context.id,
        processing_run_id=case.current_processing_run_id,
        supersedes_id=previous.id if previous else None,
        ai_suggested_status=previous.ai_suggested_status if previous else None,
        ai_confidence=previous.ai_confidence if previous else None,
        ai_rationale=previous.ai_rationale if previous else None,
        ai_suggestion_json=previous.ai_suggestion_json if previous else None,
        model_id=previous.model_id if previous else None,
        prompt_version=previous.prompt_version if previous else None,
        human_status=status_value,
        human_correction_json={
            "previous_effective_status": previous.effective_status.value if previous else None,
            "new_status": status_value.value,
        },
        human_rationale=request.rationale,
        human_confirmed=True,
        confirmed_by=request.confirmed_by,
        confirmed_at=datetime.now(UTC),
        effective_status=status_value,
        split_liability_percentage=request.split_liability_percentage,
    )
    db.add(assessment)
    context.human_confirmed = True
    context.human_confirmed_by = request.confirmed_by
    context.human_confirmed_at = assessment.confirmed_at
    domain_state = LiabilityState(status_value.value.replace("_", " "))
    gate = liability_gate(domain_state, human_confirmed=True)
    context.liability_gate_status = (
        LiabilityGateStatus.CONFIRMED
        if gate.challenge_issue_allowed
        else LiabilityGateStatus.BLOCKED
    )
    case.status = CaseStatus.LIABILITY_REVIEW
    db.add(
        AuditEvent(
            case_id=case.id,
            actor_type=AuditActorType.USER,
            actor_id=request.confirmed_by,
            event_type="LIABILITY_CONFIRMED",
            entity_type="liability_assessment",
            entity_id=assessment.id,
            before_json={"status": previous.effective_status.value if previous else None},
            after_json=request.model_dump(mode="json"),
            event_payload_json={
                "challenge_issue_allowed": gate.challenge_issue_allowed,
                "invoice_decided_fault": False,
            },
        )
    )
    db.commit()
    return {
        "status": _liability_display(status_value),
        "human_confirmed": True,
        "challenge_issue_allowed": gate.challenge_issue_allowed,
        "reason": gate.reason,
    }


_INTAKE_GROUPS = frozenset({None, "historical_claim", "in_house", "live"})


def _resolve_document_role(role: str, intake_group: str | None) -> DocumentRole:
    """One rule for both the single-file and the batch upload paths."""

    if intake_group not in _INTAKE_GROUPS:
        raise ValueError("Unknown intake group")
    if intake_group:
        return DocumentRole.CURRENT if intake_group == "live" else DocumentRole.HISTORICAL
    return DocumentRole(role)


def _uploadable_case(db: Session, case_reference: str) -> Case:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    if case.status == CaseStatus.FINALISED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CASE_ALREADY_FINALISED",
                "message": "Create a new case revision before uploading another invoice.",
            },
        )
    return case


@router.post("/claims/{case_reference}/documents", tags=["documents"])
def upload_document(
    case_reference: str,
    db: DatabaseSession,
    file: Annotated[UploadFile, File()],
    role: Annotated[str, Form()] = "current",
    intake_group: Annotated[str | None, Form()] = None,
    paired_document_id: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    case = _uploadable_case(db, case_reference)
    try:
        document_role = _resolve_document_role(role, intake_group)
        if paired_document_id:
            target = db.get(Document, paired_document_id)
            if target is None or target.case_id != case.id or not target.invoices:
                raise ValueError("The engineer estimate must reference an extracted invoice in this claim.")
            if len(target.invoices) != 1:
                raise ValueError("Choose a single-invoice document for explicit estimate linkage.")
            if (target.metadata_json or {}).get("intake_group") != intake_group:
                raise ValueError("The engineer estimate and invoice must have the same intake group.")
        content = file.file.read()
        document = store_pdf(
            db,
            case=case,
            filename=file.filename or "invoice.pdf",
            content=content,
            role=document_role,
            intake_group=intake_group,
            paired_document_id=paired_document_id,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_DOCUMENT", "message": str(exc)},
        ) from exc
    return serialise_document(document)


def _batch_entry(slot: str, filename: str | None) -> dict[str, Any]:
    return {
        "slot": slot,
        "filename": filename,
        "status": "failed",
        "document_id": None,
        "invoice_units": 0,
        "assessment_id": None,
        "error": None,
        "detail": None,
    }


# One request holds one SQLite write lock for as long as it runs, and OCR is
# 3-10 s per file.  Uncapped, 200 invoices is a 10-30 minute request during
# which every concurrent write fails against the busy timeout and the client
# has long since timed out and lost the per-file report it came for.  Fifty
# files is roughly ten times Neha's first population pass and still finishes
# inside a normal proxy timeout.
MAX_BATCH_FILES = 50
MAX_BATCH_BYTES = 500 * 1024 * 1024


def _upload_size(upload: UploadFile) -> int:
    """Bytes in an upload without reading it into memory."""

    if upload.size is not None:
        return upload.size
    position = upload.file.tell()
    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(position)
    return size


def _batch_failure(entry: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """Record a per-file failure without swallowing what actually went wrong.

    ``detail`` carries the real cause - "corrupt PDF", "OCR timeout" - because
    the whole point of a per-file report is telling the operator which file to
    look at and why.  ``error`` stays the sentence a handler can act on.
    """

    entry["status"] = "failed"
    entry["error"] = (
        str(exc)
        if isinstance(exc, ValueError)
        else "The file could not be processed. It has not been added to the claim."
    )
    entry["detail"] = f"{type(exc).__name__}: {exc}"[:500]
    return entry


@router.post("/claims/{case_reference}/documents/batch", tags=["documents"])
def upload_document_batch(
    case_reference: str,
    db: DatabaseSession,
    invoice_files: Annotated[list[UploadFile] | None, File()] = None,
    estimate_files: Annotated[list[UploadFile] | None, File()] = None,
    role: Annotated[str, Form()] = "current",
    intake_group: Annotated[str | None, Form()] = None,
    process: Annotated[bool, Form()] = True,
    run_sweep: Annotated[bool, Form()] = True,
) -> dict[str, Any]:
    """Accept a folder of repair invoices and a folder of engineer estimates.

    Two decisions worth stating.

    *Why an endpoint rather than a documented client loop.* A loop would have
    to get two things right on every call, and the cost of getting either wrong
    is silent: both folders must carry the **same** ``intake_group``, because
    ``_select_invoice`` refuses to pair an assessment with an invoice in a
    different bucket, and the invoices must be processed before the estimates,
    or each estimate pairs against a case that has no invoice in it yet. Both
    are properties of the batch as a whole, so they belong where the batch is.
    The endpoint also turns N round trips into one.

    *Why per-file results rather than all-or-nothing.* Handing over five pairs
    and being told only "422" is unusable. Each file is committed on its own, so
    one unreadable PDF fails alone and the report names it with a real reason;
    the caller keeps every file that worked.

    *Why a commit per file rather than one SAVEPOINT per file.* Two reasons,
    and they are the same reason. ``process_document``'s failure handler calls
    ``Session.rollback()`` and then ``Session.commit()`` to write the FAILED
    document and the FAILED run; inside a ``with db.begin_nested():`` that
    rollback closes the context-managed transaction and the handler's very next
    statement raises ``InvalidRequestError`` - so the document was never marked
    FAILED, no FAILED run was written, the case status was never restored, and
    the real cause was replaced by a SQLAlchemy-internals message. And a single
    transaction spanning the batch holds the SQLite write lock for the whole
    run, so every concurrent write fails against the busy timeout and one
    failure in the final sweep rolls back all N files. Committing the stored
    row before processing it, and the processed result after, fixes both: the
    handler has a durable row to mark, and no file's work depends on the next
    file's.

    The single-file endpoint is untouched and still the right call for the
    setup screen's one-invoice-one-estimate flow.
    """

    case = _uploadable_case(db, case_reference)
    try:
        document_role = _resolve_document_role(role, intake_group)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_DOCUMENT", "message": str(exc)},
        ) from exc

    queue: list[tuple[str, UploadFile]] = [
        # Invoices first: an assessment processed before any invoice exists can
        # only report "no invoice to pair with".
        *(("invoice", upload) for upload in invoice_files or []),
        *(("estimate", upload) for upload in estimate_files or []),
    ]
    if not queue:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMPTY_BATCH",
                "message": "Attach at least one file to invoice_files or estimate_files.",
            },
        )
    total_bytes = sum(_upload_size(upload) for _, upload in queue)
    if len(queue) > MAX_BATCH_FILES or total_bytes > MAX_BATCH_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "BATCH_TOO_LARGE",
                "message": (
                    f"This batch has {len(queue)} files ({total_bytes} bytes). "
                    f"Send at most {MAX_BATCH_FILES} files and "
                    f"{MAX_BATCH_BYTES} bytes per request, in several batches if "
                    "needed, then call the link-sweep endpoint once at the end."
                ),
                "files": len(queue),
                "bytes": total_bytes,
                "max_files": MAX_BATCH_FILES,
                "max_bytes": MAX_BATCH_BYTES,
            },
        )

    results: list[dict[str, Any]] = []
    for slot, upload in queue:
        entry = _batch_entry(slot, upload.filename)
        try:
            content = upload.file.read()
            document = store_pdf(
                db,
                case=case,
                filename=upload.filename or f"{slot}.pdf",
                content=content,
                role=document_role,
                intake_group=intake_group,
            )
            entry["document_id"] = document.id
            already_processed = document.page_count is not None and bool(document.pages)
            entry["status"] = "already_processed" if already_processed else "stored"
            # Durable before processing, so ``process_document``'s failure
            # handler has a row to mark FAILED after its own rollback.
            db.commit()
        except Exception as exc:  # noqa: BLE001 - one bad file must not sink the batch
            logger.exception("Batch upload failed for %s", upload.filename)
            db.rollback()
            results.append(_batch_failure(entry, exc))
            continue

        if process and entry["status"] == "stored":
            try:
                run = process_document(db, document)
                entry["status"] = "processed"
                entry["metrics"] = run.metrics_json
                db.commit()
            except Exception as exc:  # noqa: BLE001 - one bad file must not sink the batch
                logger.exception("Batch processing failed for %s", upload.filename)
                # ``process_document`` has already committed the FAILED document
                # and the FAILED run; this only clears the session.
                db.rollback()
                results.append(_batch_failure(entry, exc))
                continue

        entry["invoice_units"] = len(document.invoices)
        if document.engineer_assessment is not None:
            entry["assessment_id"] = document.engineer_assessment.id
        results.append(entry)

    swept = None
    if run_sweep and process and any(row["status"] == "processed" for row in results):
        # Every file above is already committed. A sweep failure must therefore
        # be reported, never raised: letting it propagate would close the
        # session on a rolled-back transaction and hand the client a bare 500
        # with none of the per-file rows this endpoint exists to provide.
        try:
            run_case_gap_fill(db, case.id)
            db.commit()
            swept = _pairing_summary(db, case)
        except Exception as exc:  # noqa: BLE001 - the files are already safe
            logger.exception("Batch link sweep failed for case %s", case.id)
            db.rollback()
            swept = {
                "error": (
                    "The files were accepted but the pairing sweep failed. "
                    "Call the link-sweep endpoint to retry it."
                ),
                "detail": f"{type(exc).__name__}: {exc}"[:500],
            }

    return {
        "case_reference": case.case_reference,
        "intake_group": intake_group,
        "document_role": document_role.value,
        "accepted": sum(1 for row in results if row["status"] != "failed"),
        "failed": sum(1 for row in results if row["status"] == "failed"),
        "results": results,
        "pairing": swept,
    }


def _pairing_summary(db: Session, case: Case) -> dict[str, Any]:
    assessments = db.scalars(
        select(EngineerAssessment)
        .where(EngineerAssessment.case_id == case.id)
        .options(selectinload(EngineerAssessment.paired_invoice))
        .order_by(EngineerAssessment.created_at, EngineerAssessment.id)
    ).all()
    rows = [
        {
            "assessment_id": assessment.id,
            "document_id": assessment.document_id,
            "assessment_number": assessment.assessment_number,
            "pair_status": assessment.pair_status,
            # Which of the two decided this link: the printed-identity rule,
            # or a handler who linked it by hand on the mapping screen.
            "pair_source": assessment.pair_source,
            "manual_override": manual_override_payload(assessment),
            "pair_confidence": assessment.pair_confidence,
            "pair_reasons": assessment.pair_reasons_json or [],
            "paired_invoice_id": assessment.paired_invoice_id,
            "paired_invoice_number": (
                assessment.paired_invoice.invoice_number if assessment.paired_invoice else None
            ),
        }
        for assessment in assessments
    ]
    return {
        "assessments": len(rows),
        "paired": sum(1 for row in rows if row["pair_status"] == "paired"),
        "unpaired": sum(1 for row in rows if row["pair_status"] != "paired"),
        "details": rows,
    }


@router.post("/claims/{case_reference}/documents/link-sweep", tags=["documents"])
def run_document_link_sweep(case_reference: str, db: DatabaseSession) -> dict[str, Any]:
    """Re-pair and gap-fill every assessment in the case, once, after a batch.

    Neha's step 3: "at the end, run a check" over all documents. Until now this
    sweep only ran per-document inside ``process_document`` and again inside
    ``POST /compare``, so a batch whose estimates arrived before their invoices
    stayed unpaired until someone ran a comparison. It delegates to
    ``run_case_gap_fill`` and is idempotent - the fill reverses its own earlier
    writes before re-evaluating.
    """

    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    run_case_gap_fill(db, case.id)
    summary = _pairing_summary(db, case)
    db.commit()
    return {"case_reference": case.case_reference, **summary}


def _mapping_error_status(code: str) -> int:
    if code in {"ASSESSMENT_NOT_FOUND", "INVOICE_NOT_FOUND"}:
        return 404
    if code in {"CASE_ALREADY_FINALISED", "INVOICE_ALREADY_LINKED"}:
        return 409
    return 422


@router.get("/claims/{case_reference}/document-mapping", tags=["documents"])
def get_document_mapping(case_reference: str, db: DatabaseSession) -> dict[str, Any]:
    """The mapping review step: which invoice each engineer assessment belongs to.

    Deliberately separate from ``/invoice-lines/{id}/mapping-decision``, which
    reviews the *ontology* mapping of one invoice line to a priced repair
    item. This one is about which two documents describe the same repair.
    """

    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    return case_mapping_payload(db, case)


@router.post(
    "/claims/{case_reference}/document-mapping/assessments/{assessment_id}",
    tags=["documents"],
)
def override_document_mapping(
    case_reference: str,
    assessment_id: str,
    request: AssessmentMappingOverrideRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Set, change or clear the invoice one engineer assessment is paired to.

    The pairing engine refuses to guess between two equally good candidates
    and refuses a pair whose printed identities conflict, both of which end
    in "manual linkage required". This is where that linkage is performed.
    """

    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    try:
        payload = override_assessment_pairing(
            db,
            case=case,
            assessment_id=assessment_id,
            decision=request.decision,
            invoice_id=request.invoice_id,
            actor=request.actor,
            reason=request.reason.strip() if request.reason else None,
        )
        db.commit()
        return payload
    except DocumentMappingError as exc:
        db.rollback()
        raise HTTPException(
            status_code=_mapping_error_status(exc.code),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/claims/{case_reference}/document-mapping/approve", tags=["documents"])
def approve_document_mapping(
    case_reference: str,
    request: MappingApprovalRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Approve the mapping, which runs the case-wide gap-fill sweep over it.

    This is what replaced the standing "Re-run pairing sweep" button: the
    sweep still happens, but only once a handler has said the pairs are
    right, and against the pairs they confirmed.
    """

    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    try:
        payload = approve_case_mapping(db, case=case, actor=request.actor)
        db.commit()
        return payload
    except DocumentMappingError as exc:
        db.rollback()
        raise HTTPException(
            status_code=_mapping_error_status(exc.code),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/claims/{case_reference}/documents", tags=["documents"])
def list_case_documents(
    case_reference: str,
    db: DatabaseSession,
) -> list[dict[str, Any]]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    documents = db.scalars(
        select(Document)
        .where(Document.case_id == case.id)
        .options(
            selectinload(Document.invoices),
            selectinload(Document.engineer_assessment),
        )
        .order_by(Document.created_at.desc())
    ).all()
    return [serialise_document(document) for document in documents]


@router.post("/documents/{document_id}/process", tags=["documents"])
def run_document_pipeline(
    document_id: str,
    db: DatabaseSession,
    force: bool = False,
) -> dict[str, Any]:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found")
    case = db.get(Case, document.case_id)
    if case is not None and case.status == CaseStatus.FINALISED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CASE_ALREADY_FINALISED",
                "message": "Create a new case revision before reprocessing documents.",
            },
        )
    if document.page_count is not None and document.pages:
        reprocess_required = bool((document.metadata_json or {}).get("reprocess_required"))
        if force and reprocess_required:
            for invoice in list(document.invoices):
                db.delete(invoice)
            if document.engineer_assessment is not None:
                db.delete(document.engineer_assessment)
            for page in list(document.pages):
                db.delete(page)
            db.flush()
            document.page_count = None
            document.upload_status = UploadStatus.PENDING
        else:
            return {
                "document": serialise_document(document),
                "status": "reprocess_required" if reprocess_required else "already_processed",
                "invoice_units": len(document.invoices),
                "reprocess_required": reprocess_required,
            }
    try:
        run = process_document(db, document)
        db.commit()
    except ValueError as exc:
        # Validation errors carry messages written for the handler; pass them through.
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "PDF_PROCESSING_FAILED", "message": str(exc)},
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Document processing failed for document %s", document_id)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PDF_PROCESSING_FAILED",
                "message": (
                    "The document could not be processed because of an internal "
                    "error. The uploaded file has been kept safely - try "
                    "processing it again, and contact support if this repeats."
                ),
            },
        ) from exc
    return {
        "run_id": run.id,
        "status": run.status.value,
        "metrics": run.metrics_json,
        "document": serialise_document(document),
    }


@router.get("/claims/{case_reference}/pages", tags=["documents"])
def get_pages(case_reference: str, db: DatabaseSession) -> list[dict[str, Any]]:
    pages = db.scalars(
        select(DocumentPage)
        .join(Document, DocumentPage.document_id == Document.id)
        .join(Case, Document.case_id == Case.id)
        .where(Case.case_reference == case_reference)
        .options(selectinload(DocumentPage.document))
        .order_by(Document.created_at, DocumentPage.page_number)
    ).all()
    return [_page_payload(page) for page in pages]


@router.get("/claims/{case_reference}/engineer-assessments", tags=["documents"])
def get_engineer_assessments(case_reference: str, db: DatabaseSession) -> list[dict[str, Any]]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    assessments = db.scalars(
        select(EngineerAssessment)
        .where(EngineerAssessment.case_id == case.id)
        .options(
            selectinload(EngineerAssessment.operations).selectinload(AssessmentOperation.variances)
        )
        .order_by(EngineerAssessment.created_at)
    ).all()
    return [engineer_assessment_payload(assessment) for assessment in assessments]


def _invoice_extract_line_payload(line: InvoiceLineItem) -> dict[str, Any]:
    return {
        "id": line.id,
        "sequence_no": line.sequence_no,
        "line_item_type": line.line_item_type,
        "raw_category": line.raw_category,
        "description": line.raw_description,
        "quantity": line.quantity,
        "unit_price": line.unit_price_net,
        "line_total": line.line_total_net,
        "is_section_total": line.is_section_total,
        "item_kind": line.item_kind.value,
    }


def _invoice_extract_payload(invoice: Invoice) -> dict[str, Any]:
    field_sources = (
        (invoice.document.metadata_json or {}).get("field_sources", {})
        if invoice.document
        else {}
    )
    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "vehicle_make": invoice.vehicle.make if invoice.vehicle else None,
        "vehicle_model": invoice.vehicle.model if invoice.vehicle else None,
        "vehicle_registration": invoice.vehicle.registration if invoice.vehicle else None,
        "claim_number": invoice.claim_reference,
        "policy_number": invoice.policy_number,
        "field_sources": field_sources,
        "lines": [
            _invoice_extract_line_payload(line)
            for line in sorted(invoice.line_items, key=lambda item: item.sequence_no)
        ],
    }


def _assessment_price_derived_map(assessment: EngineerAssessment) -> dict[int, bool]:
    """``price_derived`` has no column; it lives on the raw extraction payload,
    keyed by the operation's sequence number, and is only present when the
    native parser (not an LLM tier) produced the operations.
    """

    payload = assessment.extraction_payload_json or {}
    return {
        operation["sequence_no"]: operation.get("price_derived")
        for operation in payload.get("operations", [])
        if isinstance(operation, dict) and operation.get("sequence_no") is not None
    }


def _assessment_extract_line_payload(
    operation: AssessmentOperation, price_derived_map: dict[int, bool]
) -> dict[str, Any]:
    return {
        "sequence_no": operation.sequence_no,
        "line_item_type": operation.category,
        "raw_category": operation.raw_category,
        "description": operation.raw_description,
        "work_units": operation.work_units,
        "hours": operation.hours,
        "unit_price": operation.unit_price_net,
        "line_total": operation.total_net,
        "price_derived": price_derived_map.get(operation.sequence_no),
    }


def _assessment_extract_payload(assessment: EngineerAssessment) -> dict[str, Any]:
    price_derived_map = _assessment_price_derived_map(assessment)
    return {
        "assessment_id": assessment.id,
        "assessment_number": assessment.assessment_number,
        "vehicle_make": assessment.vehicle_make,
        "vehicle_model": assessment.vehicle_model,
        "vehicle_registration": assessment.registration,
        "claim_number": assessment.claim_reference,
        "policy_number": assessment.policy_number,
        "paired_invoice_number": (
            assessment.paired_invoice.invoice_number if assessment.paired_invoice else None
        ),
        "pair_status": assessment.pair_status,
        "pair_source": assessment.pair_source,
        "manual_override": manual_override_payload(assessment),
        "pair_confidence": assessment.pair_confidence,
        "pair_reasons": assessment.pair_reasons_json or [],
        "lines": [
            _assessment_extract_line_payload(operation, price_derived_map)
            for operation in sorted(assessment.operations, key=lambda item: item.sequence_no)
        ],
    }


@router.get("/claims/{case_reference}/extracts", tags=["documents"])
def get_claim_extracts(case_reference: str, db: DatabaseSession) -> dict[str, Any]:
    """The two standardised, read-only tables the client asked for: one row
    per invoice/assessment identity, one line row per invoice/assessment line,
    and the section breakdowns that link a rolled-up invoice total to the
    assessment rows behind it. The two arrays are never merged.
    """

    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    invoices = (
        db.scalars(
            select(Invoice)
            .where(Invoice.case_id == case.id)
            .options(
                selectinload(Invoice.vehicle),
                selectinload(Invoice.line_items),
                selectinload(Invoice.document),
            )
            .order_by(Invoice.invoice_date, Invoice.id)
        )
        .unique()
        .all()
    )
    assessments = db.scalars(
        select(EngineerAssessment)
        .where(EngineerAssessment.case_id == case.id)
        .options(
            selectinload(EngineerAssessment.operations),
            selectinload(EngineerAssessment.paired_invoice),
        )
        .order_by(EngineerAssessment.created_at, EngineerAssessment.id)
    ).all()
    section_breakdowns: list[dict[str, Any]] = []
    for invoice in invoices:
        for breakdown in section_breakdown_for_invoice(db, invoice):
            section_breakdowns.append(
                {"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, **breakdown}
            )
    return {
        "invoice_extracts": [_invoice_extract_payload(invoice) for invoice in invoices],
        "assessment_extracts": [
            _assessment_extract_payload(assessment) for assessment in assessments
        ],
        "section_breakdowns": section_breakdowns,
    }


@router.patch("/pages/{page_id}", tags=["documents"])
def correct_page(
    page_id: str,
    request: PageCorrectionRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    page = db.scalar(
        select(DocumentPage)
        .where(DocumentPage.id == page_id)
        .options(selectinload(DocumentPage.document).selectinload(Document.case))
    )
    if page is None:
        raise _not_found("Document page not found")
    try:
        result = correct_document_page(
            db,
            page=page,
            command=PageCorrectionCommand(
                actor=request.actor,
                reason=request.reason,
                page_type=request.page_type,
                group_id=request.group_id,
                group_id_set="group_id" in request.model_fields_set,
                rotation=request.rotation,
            ),
        )
        db.commit()
    except PageCorrectionError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return {
        **_page_payload(result.page),
        "changed_fields": list(result.changed_fields),
    }


@router.get("/pages/{page_id}/image", response_class=FileResponse, tags=["documents"])
def get_page_image(page_id: str, db: DatabaseSession):
    page = db.get(DocumentPage, page_id)
    if page is None or not page.rendered_image_path:
        raise _not_found("Page image not found")
    path = Path(page.rendered_image_path)
    if not path.exists():
        raise _not_found("Page image file not found")
    filename = f"page-{page.page_number}.png"
    return FileResponse(
        path,
        media_type="image/png",
        filename=filename,
        content_disposition_type="inline",
    )


def _line_payload(line: InvoiceLineItem, db: Session) -> dict[str, Any]:
    mapping = db.scalar(
        select(OntologyMapping)
        .where(OntologyMapping.invoice_line_item_id == line.id)
        .order_by(OntologyMapping.updated_at.desc())
    )
    comparison = db.scalar(
        select(PriceComparison)
        .where(PriceComparison.invoice_line_item_id == line.id)
        .order_by(PriceComparison.updated_at.desc())
    )
    challenge = (
        db.scalar(
            select(ChallengeResult).where(ChallengeResult.price_comparison_id == comparison.id)
        )
        if comparison
        else None
    )
    return {
        "id": line.id,
        "sequence_no": line.sequence_no,
        "description": line.raw_description,
        "normalised_description": line.normalised_description,
        "part_number": line.part_number,
        "kind": line.item_kind.value,
        "quantity": line.quantity,
        "unit": line.unit,
        "unit_price_net": line.unit_price_net,
        "line_total_net": line.line_total_net,
        "vat_rate": line.vat_rate,
        "vat_amount": line.vat_amount,
        "line_gross": line.line_gross,
        "status": line.status.value,
        "source_page_id": line.source_page_id,
        "source_page_number": line.source_page.page_number if line.source_page else None,
        "source_bbox": line.source_bbox_json,
        "source_regions": line.source_regions_json,
        "source_raw_text": line.source_raw_text,
        "extraction_method": line.extraction_method.value,
        "extraction_confidence": line.extraction_confidence,
        "user_corrected": line.user_corrected,
        "mapping": (
            {
                "id": mapping.id,
                "ontology_item_id": mapping.selected_ontology_item_id,
                "confidence": mapping.combined_confidence,
                "status": mapping.final_status.value,
                "rationale": mapping.rationale,
                "decision": mapping.decision.value,
                "reviewed_by": mapping.reviewed_by,
                "reviewed_at": (mapping.reviewed_at.isoformat() if mapping.reviewed_at else None),
                "is_bundled": mapping.is_bundled,
                "bundle_components": mapping.bundle_components_json,
                "flags": mapping.flags_json,
            }
            if mapping
            else None
        ),
        "comparison": (
            {
                "invoice_price": comparison.invoice_line_net,
                "ontology_price": comparison.ontology_line_net,
                "historical_price": comparison.historical_line_net,
                "challenge_price": comparison.benchmark_line_net,
                "benchmark_source": comparison.selected_benchmark_source,
                "status": comparison.status.value,
            }
            if comparison
            else None
        ),
        "challenge": (
            {
                "amount_net": challenge.challenge_net,
                "vat_impact": challenge.challenge_vat,
                "gross_effect": challenge.challenge_gross,
                "percentage": challenge.challenge_percentage,
                "strength": challenge.evidence_strength_score,
                "label": challenge.evidence_label,
            }
            if challenge
            else None
        ),
    }


@router.get("/claims/{case_reference}/invoices", tags=["invoices"])
def get_invoices(
    case_reference: str,
    db: DatabaseSession,
    p90_threshold_pct: int = Query(DEFAULT_P90_POLICY.default_threshold_pct),
) -> list[dict[str, Any]]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    threshold = _validated_p90_threshold_pct(p90_threshold_pct)
    invoices = (
        db.scalars(
            select(Invoice)
            .join(Case, Invoice.case_id == Case.id)
            .where(Case.case_reference == case_reference)
            .options(
                selectinload(Invoice.document),
                selectinload(Invoice.vehicle),
                selectinload(Invoice.line_items),
                selectinload(Invoice.math_findings),
            )
            .order_by(Invoice.invoice_date)
        )
        .unique()
        .all()
    )
    challenge_review_by_invoice: dict[str, dict[str, int]] = {
        invoice.id: {"positive": 0, "approved": 0, "rejected": 0, "unresolved": 0}
        for invoice in invoices
    }
    challenge_lines_by_invoice: dict[str, list[dict[str, Any]]] = {
        invoice.id: [] for invoice in invoices
    }
    # Benchmarks, Review findings and exports all use the unified read-time P90
    # decision. Persisted legacy ChallengeResult amounts can disagree with it,
    # so the invoice selector must use this same result graph as its source of
    # truth instead of reading the legacy amounts directly.
    result = build_case_result(db, case_reference, p90_threshold_pct=threshold)
    for challenge in result["challenges"]:
        invoice_id = challenge.get("invoice_id")
        if not invoice_id or _decimal_value(challenge.get("challenge_amount_net")) <= 0:
            continue
        review = challenge_review_by_invoice.setdefault(
            invoice_id,
            {"positive": 0, "approved": 0, "rejected": 0, "unresolved": 0},
        )
        review["positive"] += 1
        challenge_status = challenge.get("status")
        if challenge_status == ChallengeStatus.APPROVED.value:
            review["approved"] += 1
        elif challenge_status == ChallengeStatus.REJECTED.value:
            review["rejected"] += 1
        else:
            review["unresolved"] += 1
        challenge_lines_by_invoice.setdefault(invoice_id, []).append(
            {
                "id": challenge.get("id"),
                "line_id": challenge.get("line_id"),
                "description": challenge.get("description"),
                "billed_net": float(_decimal_value(challenge.get("invoice_net"))),
                "supported_net": float(_decimal_value(challenge.get("challenge_price_net"))),
                "in_house_p90_net": (
                    float(_decimal_value(challenge.get("in_house_p90_net")))
                    if challenge.get("in_house_p90_net") is not None
                    else None
                ),
                "historical_claims_p90_net": (
                    float(_decimal_value(challenge.get("historical_claims_p90_net")))
                    if challenge.get("historical_claims_p90_net") is not None
                    else None
                ),
                "external_price_net": (
                    float(_decimal_value(challenge.get("external_price_net")))
                    if challenge.get("external_price_net") is not None
                    else None
                ),
                "external_price_sources": challenge.get("external_price_sources") or [],
                "external_price_method": challenge.get("external_price_method"),
                "challenge_net": float(_decimal_value(challenge.get("challenge_amount_net"))),
                "status": challenge_status or ChallengeStatus.DRAFT.value,
                "benchmark_source": challenge.get("benchmark_source"),
            }
        )
    return [
        {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "uploaded_at": invoice.created_at.isoformat(),
            "document_id": invoice.document_id,
            "document_filename": invoice.document.original_filename,
            "intake_group": (invoice.document.metadata_json or {}).get("intake_group"),
            "document_role": invoice.document_role.value,
            "supplier_name": invoice.supplier_name,
            "vehicle": (
                {
                    "registration": invoice.vehicle.registration,
                    "vin": invoice.vehicle.vin,
                    "make": invoice.vehicle.make,
                    "model": invoice.vehicle.model,
                    "mileage": invoice.vehicle.mileage,
                }
                if invoice.vehicle
                else None
            ),
            "totals": {
                "labour_net": invoice.labour_net,
                "parts_net": invoice.parts_net,
                "subtotal_net": invoice.subtotal_net,
                "vat": invoice.vat_total,
                "non_vat": invoice.non_vat_total,
                "gross": invoice.gross_total,
            },
            "challenge_review": challenge_review_by_invoice[invoice.id],
            "challenge_lines": challenge_lines_by_invoice[invoice.id],
            "lines": [_line_payload(line, db) for line in invoice.line_items],
            "checks": [
                {
                    "code": finding.check_code,
                    "status": finding.status.value,
                    "severity": finding.severity.value,
                    "expected": finding.expected_value,
                    "observed": finding.observed_value,
                    "explanation": finding.explanation,
                }
                for finding in invoice.math_findings
            ],
        }
        for invoice in invoices
    ]


@router.patch("/invoice-lines/{line_id}", tags=["invoices"])
def correct_invoice_line(
    line_id: str,
    request: InvoiceLineCorrectionRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    line = db.get(InvoiceLineItem, line_id)
    if line is None:
        raise _not_found("Invoice line not found")
    if line.invoice.case.status == CaseStatus.FINALISED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CASE_ALREADY_FINALISED",
                "message": "Create a new revision before correcting a finalised case.",
            },
        )
    before = jsonable_encoder(_line_payload(line, db))
    previous_case_status = line.invoice.case.status
    audit_updates = request.model_dump(mode="json", exclude={"actor", "reason"}, exclude_none=True)
    updates = request.model_dump(exclude={"actor", "reason"}, exclude_none=True)
    if "item_kind" in updates:
        updates["item_kind"] = LineItemKind(updates["item_kind"])
    for field, value in updates.items():
        setattr(line, field, value)
    line.user_corrected = True
    line.status = ReviewStatus.CORRECTED
    line.invoice.case.status = CaseStatus.EXTRACTION_REVIEW
    recalculate_invoice_findings(db, line.invoice)
    db.add(
        AuditEvent(
            case_id=line.invoice.case_id,
            processing_run_id=line.invoice.case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=request.actor,
            event_type="INVOICE_LINE_CORRECTED",
            entity_type="invoice_line_item",
            entity_id=line.id,
            before_json=before,
            after_json={**audit_updates, "reason": request.reason},
            event_payload_json={
                "raw_extraction_preserved": True,
                "recomparison_required": True,
                "previous_case_status": previous_case_status.value,
            },
        )
    )
    db.commit()
    return _line_payload(line, db)


@router.post(
    "/claims/{case_reference}/invoices/{invoice_id}/lines",
    tags=["invoices"],
    status_code=201,
)
def add_manual_invoice_line(
    case_reference: str,
    invoice_id: str,
    request: InvoiceLineManualCreateRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Let a handler add a billable line by hand for a document the pipeline
    could not benchmark, so it flows into mapping and comparison like any
    other handler-approved extraction.
    """

    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    invoice = db.get(Invoice, invoice_id)
    if invoice is None or invoice.case_id != case.id:
        raise _not_found("Invoice not found")
    if case.status == CaseStatus.FINALISED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CASE_ALREADY_FINALISED",
                "message": "Create a new case revision before adding invoice lines.",
            },
        )
    try:
        item_kind = LineItemKind(request.item_kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_LINE_KIND",
                "message": f"Unknown item_kind: {request.item_kind}",
            },
        ) from exc
    description = request.description.strip()
    next_sequence = (
        db.scalar(
            select(func.max(InvoiceLineItem.sequence_no)).where(
                InvoiceLineItem.invoice_id == invoice.id
            )
        )
        or 0
    ) + 1
    source_page = None
    if request.page_number is not None:
        source_page = db.scalar(
            select(DocumentPage).where(
                DocumentPage.document_id == invoice.document_id,
                DocumentPage.page_number == request.page_number,
            )
        )
    line = InvoiceLineItem(
        invoice_id=invoice.id,
        sequence_no=next_sequence,
        raw_description=description,
        normalised_description=normalise_description(description),
        item_kind=item_kind,
        part_number=(request.part_number or "").strip() or None,
        quantity=request.quantity,
        unit=normalise_unit(request.unit, item_kind=item_kind.value),
        unit_price_net=request.unit_price_net,
        line_total_net=request.line_total_net,
        vat_rate=request.vat_rate,
        source_page_id=source_page.id if source_page else None,
        source_raw_text=description,
        extraction_method=ExtractionMethod.MANUAL,
        extraction_confidence=1.0,
        status=ReviewStatus.APPROVED,
        user_corrected=True,
    )
    db.add(line)
    db.flush()
    case.status = CaseStatus.EXTRACTION_REVIEW
    recalculate_invoice_findings(db, invoice)
    db.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=request.recorded_by,
            event_type="INVOICE_LINE_MANUALLY_ADDED",
            entity_type="invoice_line_item",
            entity_id=line.id,
            before_json=None,
            after_json=jsonable_encoder(_line_payload(line, db)),
            event_payload_json={
                "invoice_id": invoice.id,
                "manual_entry": True,
                "recorded_by": request.recorded_by,
            },
        )
    )
    db.commit()
    return _line_payload(line, db)


@router.post("/invoice-lines/{line_id}/extraction-decision")
def decide_extraction_line(
    line_id: str,
    request: ExtractionDecisionRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    line = db.get(InvoiceLineItem, line_id)
    if line is None:
        raise _not_found("Invoice line not found")
    try:
        reviewed = review_extraction_line(
            db,
            line=line,
            decision=request.decision,
            actor=request.actor,
            reason=request.reason.strip() if request.reason else None,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "EXTRACTION_REVIEW_BLOCKED", "message": str(error)},
        ) from error
    return _line_payload(reviewed, db)


@router.post(
    "/claims/{case_reference}/invoice-lines/{line_id}/mapping-decision",
    tags=["comparison"],
)
def decide_line_mapping(
    case_reference: str,
    line_id: str,
    request: MappingDecisionRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    try:
        result = review_line_mapping(
            db,
            case=case,
            line_id=line_id,
            command=MappingReviewCommand(
                actor=request.actor,
                decision=request.decision,
                rationale=request.rationale,
                ontology_item_id=request.ontology_item_id,
                bundle_components=tuple(
                    BundleComponentDecision(
                        ontology_item_id=component.ontology_item_id,
                        allocated_net=component.allocated_net,
                        quantity=component.quantity,
                        unit=component.unit,
                    )
                    for component in request.bundle_components
                ),
            ),
        )
        db.commit()
        return result
    except MappingReviewError as exc:
        db.rollback()
        status_code = (
            404
            if exc.code in {"INVOICE_LINE_NOT_FOUND", "ONTOLOGY_ITEM_NOT_FOUND"}
            else 409
            if exc.code
            in {
                "CASE_ALREADY_FINALISED",
                "COMPARISON_NOT_READY",
                "CHALLENGE_RESULT_NOT_FOUND",
                "INVOICE_SUMMARY_NOT_FOUND",
                "COMPARABLES_CHANGED",
            }
            else 422
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/invoices/{invoice_id}/settlements", tags=["settlements"])
def record_settlement(
    invoice_id: str,
    request: SettlementCreateRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id).options(selectinload(Invoice.line_items))
    )
    if invoice is None:
        raise _not_found("Invoice not found")
    vat = request.agreed_vat or Decimal("0")
    invoice_settlement = Settlement(
        invoice_id=invoice.id,
        line_item_id=None,
        status=SettlementStatus.SETTLED,
        agreed_amount_net=request.agreed_amount_net,
        agreed_vat=vat,
        agreed_amount_gross=request.agreed_amount_net + vat,
        agreed_at=request.agreed_at,
        recorded_by=request.recorded_by,
        note=request.note,
        negotiation_reference=request.negotiation_reference,
    )
    db.add(invoice_settlement)
    line_ids = {line.id for line in invoice.line_items}
    for allocation in request.lines:
        if allocation.line_item_id not in line_ids:
            raise HTTPException(status_code=422, detail="Settlement line is not on this invoice")
        line_vat = allocation.agreed_vat or Decimal("0")
        db.add(
            Settlement(
                invoice_id=invoice.id,
                line_item_id=allocation.line_item_id,
                status=SettlementStatus.SETTLED,
                agreed_amount_net=allocation.agreed_amount_net,
                agreed_vat=line_vat,
                agreed_amount_gross=allocation.agreed_amount_net + line_vat,
                agreed_at=request.agreed_at,
                recorded_by=request.recorded_by,
                note=request.note,
                negotiation_reference=request.negotiation_reference,
            )
        )
    db.add(
        AuditEvent(
            case_id=invoice.case_id,
            actor_type=AuditActorType.USER,
            actor_id=request.recorded_by,
            event_type="SETTLEMENT_RECORDED",
            entity_type="invoice",
            entity_id=invoice.id,
            before_json=None,
            after_json=request.model_dump(mode="json"),
            event_payload_json={
                "invoice_level_required": True,
                "line_allocations_optional": True,
            },
        )
    )
    db.commit()
    return {
        "id": invoice_settlement.id,
        "invoice_id": invoice.id,
        "agreed_amount_net": invoice_settlement.agreed_amount_net,
        "agreed_vat": invoice_settlement.agreed_vat,
        "agreed_amount_gross": invoice_settlement.agreed_amount_gross,
        "line_allocations": len(request.lines),
        "status": invoice_settlement.status.value,
    }


@router.post("/admin/seeds/import", tags=["admin"])
def import_pilot_seeds(request: SeedImportRequest, db: DatabaseSession) -> dict[str, Any]:
    """Import the governed ontology/history workbooks; identical replays are idempotent."""

    try:
        result = import_seed_workbooks(
            db,
            request.ontology_path,
            request.historical_path,
            adapter_key=request.adapter_key,
        )
        db.commit()
    except (FileNotFoundError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "SEED_IMPORT_FAILED", "message": str(exc)},
        ) from exc
    return asdict(result)


@router.get("/admin/in-house-repair-data.csv", tags=["admin"])
def download_synthetic_in_house_data(db: DatabaseSession) -> Response:
    """Download the governed synthetic in-house observations used by the demo."""

    from app.services.in_house_repair_data import synthetic_in_house_csv

    return Response(
        content=synthetic_in_house_csv(db),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="claim-guard-in-house-repair-data.csv"'
        },
    )


@router.post("/admin/case-data/reset", tags=["admin"])
def reset_case_data_endpoint(
    request: CaseDataResetRequest, db: DatabaseSession
) -> dict[str, Any]:
    """Delete every per-case document artefact and open one empty case.

    Destructive and irreversible, so it is gated twice: the caller has to send
    the exact confirmation phrase, and nothing is deleted until that matches.
    Reference data - ontology, price library, seed benchmark history, vehicle
    lookup, regulatory rules, configuration - is kept, and so is the schema.

    Files go *after* the commit, never before. ``reset_case_data`` resolves the
    roots and returns them; only once ``db.commit()`` has returned does
    ``clear_reset_paths`` sweep them. The other order means a commit that fails
    on a locked or full database leaves every case row in place and every PDF
    behind it permanently gone - strictly worse than doing nothing.

    The sweep itself never aborts the request: by the time it runs the database
    half is durable, so a ``PermissionError`` halfway through is reported in
    ``sweep_failures`` rather than raised as a 500 that tells the operator
    nothing about which directories survived.

    Not authenticated, matching the other ``/admin`` routes - see the reset
    endpoint's note in the commit message. That is a real gap for a route that
    erases the audit chain, and the audit export is the mitigation, not a fix.
    """

    if request.confirm != CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "RESET_CONFIRMATION_REQUIRED",
                "message": (
                    "This permanently deletes every case, document and extract. "
                    f'Send confirm="{CONFIRMATION_PHRASE}" to proceed.'
                ),
            },
        )
    try:
        report = reset_case_data(
            db,
            new_case_reference=request.new_case_reference or None,
            purge_derived_history=request.purge_derived_history,
            actor=request.actor,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "RESET_FAILED", "message": str(exc)},
        ) from exc
    clear_reset_paths(report)
    return report.as_dict()


@router.get("/benchmarks/dashboard", tags=["benchmarks"])
def benchmark_dashboard(
    db: DatabaseSession,
    case_reference: str | None = None,
    vehicle_class: str | None = None,
    ontology_item_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    minimum_count: Annotated[int, Query(ge=1, le=1000)] = 1,
    challenge_threshold_pct: Annotated[float, Query(ge=0, le=100)] = 10,
    source_group: Annotated[str | None, Query(pattern="^(in_house|historical_claim)$")] = None,
) -> dict[str, Any]:
    """Read the governed, invoice-only repair benchmarking database."""

    if case_reference:
        try:
            uploaded_dashboard = build_uploaded_batch_benchmark_dashboard(
                db,
                case_reference,
                vehicle_class=vehicle_class,
                ontology_item_id=ontology_item_id,
                date_from=date_from,
                date_to=date_to,
                minimum_count=minimum_count,
                challenge_threshold_pct=challenge_threshold_pct,
                source_group=source_group,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if uploaded_dashboard is not None:
            return uploaded_dashboard

    return build_benchmark_dashboard(
        db,
        vehicle_class=vehicle_class,
        ontology_item_id=ontology_item_id,
        date_from=date_from,
        date_to=date_to,
        minimum_count=minimum_count,
        challenge_threshold_pct=challenge_threshold_pct,
        source_group=source_group,
    )


@router.get("/benchmarks/{ontology_item_id}/observations", tags=["benchmarks"])
def benchmark_source_observations(
    ontology_item_id: str,
    db: DatabaseSession,
    vehicle_class: str | None = None,
    source_group: Annotated[str | None, Query(pattern="^(in_house|historical_claim)$")] = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> dict[str, Any]:
    """Return the bounded source invoices behind a benchmark row."""

    return {
        "ontologyItemId": ontology_item_id,
        "vehicleClass": vehicle_class,
        "observations": benchmark_observations(
            db,
            ontology_item_id,
            vehicle_class=vehicle_class,
            source_group=source_group,
            limit=limit,
        ),
    }


@router.get("/historical-observations/{observation_id}", tags=["benchmarks"])
def historical_observation_source(
    observation_id: str,
    db: DatabaseSession,
) -> dict[str, Any]:
    observation = db.get(HistoricalObservation, observation_id)
    if observation is None:
        raise _not_found("Historical observation not found")
    return {
        "id": observation.id,
        "claim_reference": observation.claim_reference,
        "source_record_id": observation.source_record_id,
        "invoice_date": (
            observation.invoice_date.isoformat() if observation.invoice_date else None
        ),
        "description": observation.raw_description,
        "line_total_net": observation.line_total_net,
        "approved_amount_net": observation.approved_amount_net,
        "settled_amount_net": observation.settled_amount_net,
        "vehicle": {
            "make": observation.vehicle_make,
            "model": observation.vehicle_model,
            "variant": observation.vehicle_variant,
            "year": observation.vehicle_year,
            "class": observation.official_vehicle_class,
        },
        "source": observation.comparability_metadata_json or {},
    }


@router.post("/claims/{case_reference}/compare", tags=["comparison"])
def compare_claim(case_reference: str, db: DatabaseSession) -> dict[str, Any]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    try:
        # Comparison is the "after all documents are loaded" moment, so the
        # assessment gap-fill sweep runs here before anything reads the
        # invoice's vehicle or claim identity.
        run_case_gap_fill(db, case.id)
        ontology_count = db.scalar(select(func.count(OntologyItem.id))) or 0
        history_count = db.scalar(select(func.count(HistoricalObservation.id))) or 0
        if ontology_count == 0:
            raise ValueError(
                "The ontology bank is empty. Import the ontology seed before comparison."
            )
        if history_count == 0:
            raise ValueError(
                "The historical claims bank is empty. Import historical invoice "
                "evidence before comparison."
            )
        existing_comparison = (
            db.scalar(
                select(PriceComparison.id).where(
                    PriceComparison.processing_run_id == case.current_processing_run_id
                )
            )
            if case.current_processing_run_id
            else None
        )
        # A handler-triggered comparison is an explicit refresh request.  Older
        # handover databases may contain comparisons created before the
        # ontology/history seeds were imported (or before the current mapping
        # rules).  Returning ``already_compared`` would preserve those stale
        # NO_MATCH rows forever.  Reprocessing is immutable: it creates a new
        # run and retains the previous audit evidence.
        if existing_comparison:
            result = reprocess_case(
                db,
                case,
                actor="pilot.handler",
                llm_adjudicator=build_mapping_adjudicator(get_settings()),
            )
        else:
            result = run_case_comparison(
                db,
                case,
                llm_adjudicator=build_mapping_adjudicator(get_settings()),
            )
        db.add(
            AuditEvent(
                case_id=case.id,
                processing_run_id=case.current_processing_run_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id="claimguard.comparison",
                event_type="CASE_COMPARISON_COMPLETED",
                entity_type="case",
                entity_id=case.id,
                before_json=None,
                after_json=result,
                event_payload_json={"policy_version": "claimguard-v1.4"},
            )
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "COMPARISON_NOT_READY", "message": str(exc)},
        ) from exc
    return result


@router.post(
    "/claims/{case_reference}/invoice-lines/{line_id}/research",
    tags=["research"],
)
def trigger_line_research(
    case_reference: str,
    line_id: str,
    request: ManualResearchRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    try:
        suggestion = ResearchSuggestionInput(
            canonical_name=request.suggestion.canonical_name,
            item_type=LineItemKind(request.suggestion.item_type.lower()),
            category=request.suggestion.category,
            unit=request.suggestion.unit,
            price_net=request.suggestion.price_net,
            date_checked=request.suggestion.date_checked,
            rationale=request.suggestion.rationale,
            vat_basis=PriceVatBasis(request.suggestion.vat_basis.lower()),
            price_scope=PriceScope(request.suggestion.price_scope.lower()),
            part_number=request.suggestion.part_number,
            vehicle_compatibility=request.suggestion.vehicle_compatibility,
            confidence=request.suggestion.confidence,
            currency=request.suggestion.currency,
            region=request.suggestion.region,
            quality_tier=request.suggestion.quality_tier,
        )
        evidence = [
            ManualEvidenceInput(
                source_uri=row.source_uri,
                title=row.title,
                captured_at=row.captured_at,
                minimal_excerpt=row.minimal_excerpt,
                source_record_id=row.source_record_id,
                price_net=row.price_net,
                original_price=row.original_price,
                currency=row.currency,
                vat_basis=PriceVatBasis(row.vat_basis.lower()),
                unit=row.unit,
                part_number=row.part_number,
                fitment=row.fitment,
                quality_tier=row.quality_tier,
                condition=row.condition,
                shipping=row.shipping,
                stock_status=row.stock_status,
            )
            for row in request.evidence
        ]
        return trigger_manual_research(
            db,
            case_id=case.id,
            invoice_line_item_id=line_id,
            requested_by=request.requested_by,
            query_text=request.query_text,
            suggestion=suggestion,
            evidence=evidence,
            source_allow_list_version=request.source_allow_list_version,
        )
    except ResearchWorkflowError as exc:
        status_code = (
            404
            if exc.code == "INVOICE_LINE_NOT_FOUND"
            else 409
            if exc.code in _RESEARCH_CONFLICT_CODES
            else 422
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_RESEARCH_INPUT", "message": str(exc)},
        ) from exc


@router.post("/research-items/{research_item_id}/approve", tags=["research"])
def approve_researched_item(
    research_item_id: str,
    request: ResearchItemApprovalRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    try:
        return approve_research_item(
            db,
            research_item_id=research_item_id,
            approved_by=request.approved_by,
            reviewer_note=request.reviewer_note,
        )
    except ResearchWorkflowError as exc:
        status_code = 404 if exc.code == "RESEARCH_ITEM_NOT_FOUND" else 409
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/challenge-results/{challenge_id}/decision", tags=["comparison"])
def decide_challenge(
    challenge_id: str,
    request: ReviewDecisionRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    challenge = db.get(ChallengeResult, challenge_id)
    if challenge is None:
        raise _not_found("Challenge result not found")
    case_id = _challenge_case_id(db, challenge)
    case = db.get(Case, case_id) if case_id else None
    if case is not None and case.status == CaseStatus.FINALISED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CASE_ALREADY_FINALISED",
                "message": "Challenge decisions cannot change after case finalisation.",
            },
        )
    comparison = (
        db.get(PriceComparison, challenge.price_comparison_id)
        if challenge.price_comparison_id
        else None
    )
    mapping = (
        db.get(OntologyMapping, comparison.ontology_mapping_id)
        if comparison and comparison.ontology_mapping_id
        else None
    )
    ontology_item = (
        db.get(OntologyItem, mapping.selected_ontology_item_id)
        if mapping and mapping.selected_ontology_item_id
        else None
    )
    line = db.get(InvoiceLineItem, comparison.invoice_line_item_id) if comparison else None
    before = {
        "status": challenge.status.value,
        "reviewer_approved": challenge.reviewer_approved,
        "challenge_net": challenge.challenge_net,
        "challenge_vat": challenge.challenge_vat,
        "recommended_payable_net": challenge.recommended_payable_net,
    }
    live_challenge: dict[str, Any] | None = None
    if request.challenge_price_net is not None and not request.approved:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CHALLENGE_EDIT",
                "message": "A rejected line cannot also set a Challenge Price.",
            },
        )
    if request.challenge_price_net is not None:
        invoice_line_net = _decimal_value(comparison.invoice_line_net if comparison else None)
        edited_price = request.challenge_price_net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if (
            comparison is None
            or line is None
            or edited_price <= Decimal("0.00")
            or edited_price >= invoice_line_net
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_CHALLENGE_PRICE",
                    "message": (
                        "Challenge Price must be more than £0.00 and less than "
                        "the current net line total. Reject the challenge when "
                        "no reduction is needed."
                    ),
                },
            )
        edited_challenge = (invoice_line_net - edited_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        vat_rate = _decimal_value(line.vat_rate)
        edited_vat = (
            (edited_challenge * vat_rate / Decimal("100")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if line.vat_applicable
            else Decimal("0.00")
        )
        edited_percentage = (
            edited_challenge / invoice_line_net * Decimal("100")
            if invoice_line_net > 0
            else Decimal("0")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        challenge.challenge_net = f"{edited_challenge:.2f}"
        challenge.challenge_vat = f"{edited_vat:.2f}"
        challenge.challenge_gross = f"{edited_challenge + edited_vat:.2f}"
        challenge.challenge_percentage = f"{edited_percentage:.2f}"
        challenge.recommended_payable_net = f"{edited_price:.2f}"
        challenge.narrative = (
            f"Handler edited the line Challenge Price to £{edited_price:.2f}. {request.rationale}"
        )
    elif request.approved and case is not None:
        # Persist the exact operational recommendation the reviewer saw. The
        # legacy comparison row can contain an older policy amount; approving
        # without a manual edit must not silently switch back to that value.
        live_result = build_case_result(db, case.case_reference)
        live_challenge = next(
            (row for row in live_result["challenges"] if row.get("id") == challenge.id),
            None,
        )
        if live_challenge and _decimal_value(live_challenge.get("challenge_amount_net")) > 0:
            live_price = _decimal_value(live_challenge.get("challenge_price_net")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            live_amount = _decimal_value(live_challenge.get("challenge_amount_net")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            live_vat = _decimal_value(live_challenge.get("challenge_vat")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            invoice_line_net = _decimal_value(
                live_challenge.get("invoice_net")
                or (comparison.invoice_line_net if comparison else None)
            )
            live_percentage = (
                live_amount / invoice_line_net * Decimal("100")
                if invoice_line_net > 0
                else Decimal("0")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            challenge.recommended_payable_net = f"{live_price:.2f}"
            challenge.challenge_net = f"{live_amount:.2f}"
            challenge.challenge_vat = f"{live_vat:.2f}"
            challenge.challenge_gross = f"{live_amount + live_vat:.2f}"
            challenge.challenge_percentage = f"{live_percentage:.2f}"
            challenge.narrative = request.rationale
    live_decision_has_verified_price_source = bool(
        request.approved
        and live_challenge
        and (
            live_challenge.get("in_house_p90_net") is not None
            or live_challenge.get("historical_claims_p90_net") is not None
            or live_challenge.get("external_price_net") is not None
        )
    )
    evidence_is_approved = bool(
        live_decision_has_verified_price_source
        or (
            comparison
            and (
                comparison.n_comparables >= 3
                or (ontology_item and ontology_item.approval_status == ApprovalStatus.APPROVED)
            )
        )
    )
    if (
        request.approved
        and _decimal_value(challenge.challenge_net) > 0
        and not evidence_is_approved
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROVISIONAL_EVIDENCE",
                "message": (
                    "A challenge requires at least one verified in-house benchmark P90, "
                    "historical claims P90 or external reference price."
                ),
            },
        )
    challenge.reviewer_approved = request.approved
    challenge.status = ChallengeStatus.APPROVED if request.approved else ChallengeStatus.REJECTED
    challenge.approved_by = request.actor
    challenge.approved_at = datetime.now(UTC)
    if comparison is not None and line is not None:
        refresh_invoice_rollup(
            db,
            line=line,
            processing_run_id=comparison.processing_run_id,
        )
    db.add(
        AuditEvent(
            case_id=case_id,
            processing_run_id=challenge.processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=request.actor,
            event_type="CHALLENGE_APPROVED" if request.approved else "CHALLENGE_REJECTED",
            entity_type="challenge_result",
            entity_id=challenge.id,
            before_json=before,
            after_json={
                "status": challenge.status.value,
                "reviewer_approved": request.approved,
                "rationale": request.rationale,
                "challenge_net": challenge.challenge_net,
                "challenge_vat": challenge.challenge_vat,
                "challenge_gross": challenge.challenge_gross,
                "recommended_payable_net": challenge.recommended_payable_net,
                "handler_edited": request.challenge_price_net is not None,
            },
            event_payload_json={"provisional_evidence_excluded": True},
        )
    )
    db.commit()
    return {
        "id": challenge.id,
        "status": challenge.status.value,
        "reviewer_approved": challenge.reviewer_approved,
        "approved_by": challenge.approved_by,
        "approved_at": challenge.approved_at,
        "challenge_net": challenge.challenge_net,
        "challenge_vat": challenge.challenge_vat,
        "challenge_gross": challenge.challenge_gross,
        "recommended_payable_net": challenge.recommended_payable_net,
    }


def _decimal_value(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _challenge_case_id(db: Session, challenge: ChallengeResult) -> str | None:
    if challenge.invoice_id:
        invoice = db.get(Invoice, challenge.invoice_id)
        return invoice.case_id if invoice else None
    if challenge.price_comparison_id:
        return db.scalar(
            select(Invoice.case_id)
            .join(InvoiceLineItem, InvoiceLineItem.invoice_id == Invoice.id)
            .join(PriceComparison, PriceComparison.invoice_line_item_id == InvoiceLineItem.id)
            .where(PriceComparison.id == challenge.price_comparison_id)
        )
    return None


@router.post("/claims/{case_reference}/finalise", tags=["comparison"])
def finalise_claim(
    case_reference: str,
    request: FinaliseCaseRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    case = db.scalar(_case_query().where(Case.case_reference == case_reference))
    if case is None or case.claim_context is None:
        raise _not_found("Claim context not found")
    if case.status == CaseStatus.FINALISED:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CASE_ALREADY_FINALISED",
                "message": "The claim is already finalised.",
            },
        )
    if case.status != CaseStatus.COMPARISON_REVIEW or case.current_processing_run_id is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPARISON_NOT_READY",
                "message": "A completed current comparison is required before finalisation.",
            },
        )
    context = case.claim_context
    latest = (
        max(context.liability_assessments, key=lambda item: item.created_at)
        if context.liability_assessments
        else None
    )
    state = LiabilityState(
        (latest.effective_status.value if latest else "HUMAN_REVIEW_REQUIRED").replace("_", " ")
    )
    gate = liability_gate(state, human_confirmed=bool(latest and latest.human_confirmed))
    if not gate.challenge_issue_allowed:
        raise HTTPException(
            status_code=409,
            detail={"code": "LIABILITY_GATE_BLOCKED", "message": gate.reason},
        )
    invoice_summaries = list(
        db.scalars(
            select(ChallengeResult).where(
                ChallengeResult.processing_run_id == case.current_processing_run_id,
                ChallengeResult.invoice_id.is_not(None),
            )
        ).all()
    )
    if not invoice_summaries:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPARISON_NOT_READY",
                "message": "The current comparison has no invoice summary to finalise.",
            },
        )
    line_decision_rows = list(
        db.execute(
            select(ChallengeResult, InvoiceLineItem.invoice_id, PriceComparison.invoice_line_net)
            .join(
                PriceComparison,
                PriceComparison.id == ChallengeResult.price_comparison_id,
            )
            .join(
                InvoiceLineItem,
                InvoiceLineItem.id == PriceComparison.invoice_line_item_id,
            )
            .where(
                ChallengeResult.processing_run_id == case.current_processing_run_id,
                ChallengeResult.price_comparison_id.is_not(None),
            )
        ).all()
    )
    line_challenges = [row[0] for row in line_decision_rows]
    if not line_challenges:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPARISON_NOT_READY",
                "message": "The current comparison has no line decisions to finalise.",
            },
        )
    resolved_statuses = {ChallengeStatus.APPROVED, ChallengeStatus.REJECTED}
    # The review UI and invoice selectors use the unified read-time decision.
    # Apply that same source of truth here so a stale persisted amount cannot
    # block finalisation after the current three-source calculation reaches 0.
    live_result = build_case_result(db, case_reference)
    live_positive_ids = {
        row.get("id")
        for row in live_result.get("challenges", [])
        if row.get("id") and _decimal_value(row.get("challenge_amount_net")) > 0
    }
    pending = [
        row.id
        for row in line_challenges
        if row.id in live_positive_ids and row.status not in resolved_statuses
    ]
    if pending:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CHALLENGE_REVIEW_REQUIRED",
                "message": "Every positive challenge line must be reviewed before finalisation.",
                "challenge_ids": pending,
            },
        )
    decisions_by_invoice: dict[str, list[tuple[ChallengeResult, Decimal]]] = {}
    for challenge, invoice_id, invoice_line_net in line_decision_rows:
        decisions_by_invoice.setdefault(invoice_id, []).append(
            (challenge, _decimal_value(invoice_line_net))
        )
    approved_at = datetime.now(UTC)
    for summary in invoice_summaries:
        invoice_decisions = decisions_by_invoice.get(summary.invoice_id or "", [])
        invoice_price_net = sum(
            (invoice_line_net for _, invoice_line_net in invoice_decisions),
            Decimal("0"),
        )
        approved_lines = [
            challenge
            for challenge, _ in invoice_decisions
            if challenge.status == ChallengeStatus.APPROVED and challenge.id in live_positive_ids
        ]
        challenge_net = sum(
            (_decimal_value(challenge.challenge_net) for challenge in approved_lines),
            Decimal("0"),
        )
        challenge_vat = sum(
            (_decimal_value(challenge.challenge_vat) for challenge in approved_lines),
            Decimal("0"),
        )
        challenge_gross = challenge_net + challenge_vat
        approved_score = (
            Decimal(sum(challenge.evidence_strength_score for challenge in approved_lines))
            / Decimal(len(approved_lines))
            if approved_lines
            else Decimal("0")
        )
        summary.challenge_net = challenge_net
        summary.challenge_vat = challenge_vat
        summary.challenge_gross = challenge_gross
        summary.challenge_percentage = (
            challenge_net / invoice_price_net * Decimal("100")
            if invoice_price_net > 0
            else Decimal("0")
        )
        summary.evidence_strength_score = int(
            approved_score.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        summary.evidence_label = (
            "Strong"
            if approved_score >= Decimal("80")
            else "Moderate"
            if approved_score >= Decimal("60")
            else "Weak"
        )
        summary.recommended_payable_net = invoice_price_net - challenge_net
        summary.narrative = (
            f"Invoice Challenge Price £{invoice_price_net - challenge_net:.2f} "
            "after handler review."
        )
        summary.score_breakdown_json = {
            **(summary.score_breakdown_json or {}),
            "challenged_line_count": len(approved_lines),
            "reviewed_positive_line_count": sum(
                1
                for challenge, _ in invoice_decisions
                if _decimal_value(challenge.challenge_net) > 0
                and challenge.status in resolved_statuses
            ),
            "rejected_positive_line_count": sum(
                1
                for challenge, _ in invoice_decisions
                if _decimal_value(challenge.challenge_net) > 0
                and challenge.status == ChallengeStatus.REJECTED
            ),
        }
        summary.findings_json = {
            **(summary.findings_json or {}),
            "human_decisions_applied": True,
        }
        summary.reviewer_approved = True
        summary.status = ChallengeStatus.APPROVED
        summary.approved_by = request.finalised_by
        summary.approved_at = approved_at
    case.status = CaseStatus.FINALISED
    case.finalised_at = approved_at
    benchmark_observations_created = sync_finalised_case_to_benchmarks(db, case)
    db.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=request.finalised_by,
            event_type="CASE_FINALISED",
            entity_type="case",
            entity_id=case.id,
            before_json={"status": CaseStatus.COMPARISON_REVIEW.value},
            after_json={"status": CaseStatus.FINALISED.value, "note": request.note},
            event_payload_json={
                "liability_status": _liability_display(latest.effective_status),
                "positive_lines_reviewed": sum(
                    1 for row in line_challenges if _decimal_value(row.challenge_net) > 0
                ),
                "positive_lines_approved": sum(
                    1
                    for row in line_challenges
                    if _decimal_value(row.challenge_net) > 0
                    and row.status == ChallengeStatus.APPROVED
                ),
                "positive_lines_rejected": sum(
                    1
                    for row in line_challenges
                    if _decimal_value(row.challenge_net) > 0
                    and row.status == ChallengeStatus.REJECTED
                ),
                "benchmark_observations_created": benchmark_observations_created,
            },
        )
    )
    db.commit()
    return {
        "case_reference": case.case_reference,
        "status": case.status.value,
        "finalised_at": case.finalised_at,
        "finalised_by": request.finalised_by,
        "benchmark_observations_created": benchmark_observations_created,
    }


@router.post("/claims/{case_reference}/reprocess", tags=["comparison"])
def reprocess_claim(
    case_reference: str,
    request: ReprocessCaseRequest,
    db: DatabaseSession,
) -> dict[str, Any]:
    case = db.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise _not_found("Claim not found")
    try:
        result = reprocess_case(
            db,
            case,
            actor=request.actor,
            ontology_version_id=request.ontology_version_id,
            llm_adjudicator=build_mapping_adjudicator(get_settings()),
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "REPROCESS_BLOCKED", "message": str(exc)},
        ) from exc


def _validated_p90_threshold_pct(p90_threshold_pct: int) -> int:
    if p90_threshold_pct not in DEFAULT_P90_POLICY.allowed_thresholds:
        allowed = sorted(DEFAULT_P90_POLICY.allowed_thresholds)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_P90_THRESHOLD",
                "message": f"p90_threshold_pct must be one of: {allowed}",
                "allowed": allowed,
            },
        )
    return p90_threshold_pct


@router.get("/claims/{case_reference}/workspace", tags=["reports"])
def get_claim_workspace(
    case_reference: str,
    db: DatabaseSession,
    invoice_id: str | None = None,
    p90_threshold_pct: int = Query(DEFAULT_P90_POLICY.default_threshold_pct),
) -> dict[str, Any]:
    threshold = _validated_p90_threshold_pct(p90_threshold_pct)
    try:
        return build_claim_workspace(
            db, case_reference, invoice_id=invoice_id, p90_threshold_pct=threshold
        )
    except LookupError as exc:
        raise _not_found("Claim not found") from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "WORKSPACE_NOT_READY", "message": str(exc)}
        ) from exc


@router.get("/claims/{case_reference}/result", tags=["reports"])
def get_case_result(
    case_reference: str,
    db: DatabaseSession,
    p90_threshold_pct: int = Query(DEFAULT_P90_POLICY.default_threshold_pct),
) -> dict[str, Any]:
    threshold = _validated_p90_threshold_pct(p90_threshold_pct)
    try:
        return build_case_result(db, case_reference, p90_threshold_pct=threshold)
    except LookupError as exc:
        raise _not_found("Claim not found") from exc


@router.get(
    "/claims/{case_reference}/lines/{line_id}/price-evidence",
    tags=["reports"],
)
def get_line_price_evidence(
    case_reference: str,
    line_id: str,
    db: DatabaseSession,
    p90_threshold_pct: int = Query(DEFAULT_P90_POLICY.default_threshold_pct),
) -> dict[str, Any]:
    """Return the exact evidence rows used for one line's supported price."""

    threshold = _validated_p90_threshold_pct(p90_threshold_pct)
    try:
        return build_line_price_evidence(
            db,
            case_reference,
            line_id,
            p90_threshold_pct=threshold,
        )
    except LookupError as exc:
        raise _not_found("Invoice line evidence not found") from exc


@router.get("/claims/{case_reference}/knowledge-graph", tags=["reports"])
def get_challenge_knowledge_graph(
    case_reference: str,
    db: DatabaseSession,
    p90_threshold_pct: int = Query(DEFAULT_P90_POLICY.default_threshold_pct),
) -> dict[str, Any]:
    threshold = _validated_p90_threshold_pct(p90_threshold_pct)
    try:
        result = build_case_result(db, case_reference, p90_threshold_pct=threshold)
    except LookupError as exc:
        raise _not_found("Claim not found") from exc
    payload = build_challenge_knowledge_graph(result)
    sync_to_neo4j(payload, get_settings())
    return payload


@router.get("/claims/{case_reference}/reports/{report_format}", tags=["reports"])
def download_report(
    case_reference: str,
    report_format: str,
    db: DatabaseSession,
    p90_threshold_pct: int = Query(DEFAULT_P90_POLICY.default_threshold_pct),
):
    threshold = _validated_p90_threshold_pct(p90_threshold_pct)
    report_format = report_format.lower()
    allowed = {"json", "xlsx", "sqlite", "docx", "pdf"}
    if report_format not in allowed:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNSUPPORTED_REPORT", "allowed": sorted(allowed)},
        )
    try:
        result = build_case_result(db, case_reference, p90_threshold_pct=threshold)
    except LookupError as exc:
        raise _not_found("Claim not found") from exc

    if report_format in {"docx", "pdf"} and result["case"]["status"] != CaseStatus.FINALISED.value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REPORT_BLOCKED",
                "message": "Negotiation letters require a finalised claim.",
            },
        )

    filename = (
        f"{case_reference}-claimguard.{report_format if report_format != 'sqlite' else 'sqlite3'}"
    )
    if report_format == "json":
        return Response(
            content=build_json_bytes(result),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    output_dir = BACKEND_DIR / "data" / "exports" / case_reference
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    try:
        if report_format == "xlsx":
            build_case_workbook(result, output_path)
        elif report_format == "docx":
            build_negotiation_docx(result, output_path)
        elif report_format == "pdf":
            build_negotiation_pdf(result, output_path)
        else:
            database_path = db.get_bind().url.database
            if not database_path or database_path == ":memory:":
                raise ValueError("SQLite backup is unavailable for an in-memory database.")
            backup_sqlite(database_path, output_path)
    except (ExportValidationError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "REPORT_BLOCKED", "message": str(exc)},
        ) from exc
    return FileResponse(output_path, filename=filename)
