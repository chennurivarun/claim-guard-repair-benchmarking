from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, Settings, get_settings
from app.domain.liability import (
    ExistingInvoiceIdentity,
    InvoiceClaimFacts,
    claim_invoice_consistency,
)
from app.enums import (
    CaseStatus,
    CheckStatus,
    ClaimVehicleRole,
    ConsistencyFindingStatus,
    DocumentKind,
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    PageType,
    PriceScope,
    ReviewStatus,
    RunStatus,
    RunType,
    Severity,
    UploadStatus,
)
from app.extraction.azure_document_intelligence import AzureDocumentIntelligenceOCR
from app.extraction.calculation_validator import validate_invoice
from app.extraction.engineer_assessment_parser import parse_engineer_assessment
from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.llm.factory import build_invoice_text_extractor, build_invoice_vision_extractor
from app.models import (
    AssessmentOperation,
    Case,
    ClaimConsistencyFinding,
    ClaimVehicle,
    Document,
    DocumentPage,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
    MathFinding,
    OntologyVersion,
    ProcessingRun,
    Vehicle,
    invoice_page_links,
)
from app.services.engineer_assessment import normalise_operation, pair_case_assessments
from app.services.vehicle_category_lookup import apply_lookup_to_vehicle
from app.services.vehicle_classification import (
    apply_vehicle_classification,
    classification_from_record,
    normalise_registration,
)

settings = get_settings()
POLICY_PATH = BACKEND_DIR / "config" / "policies" / "claimguard-v1.4.yaml"


def _build_cloud_ocr(config: Settings) -> AzureDocumentIntelligenceOCR | None:
    if config.document_ocr_provider not in {"auto", "azure"}:
        return None

    endpoint = (config.azure_document_endpoint or "").strip()
    api_key = (
        config.azure_document_api_key.get_secret_value().strip()
        if config.azure_document_api_key
        else ""
    )
    if bool(endpoint) != bool(api_key):
        raise ValueError(
            "Azure OCR configuration is incomplete. Set both "
            "CLAIM_GUARD_AZURE_DOCUMENT_ENDPOINT and "
            "CLAIM_GUARD_AZURE_DOCUMENT_API_KEY, then restart FastAPI."
        )
    if endpoint and api_key:
        return AzureDocumentIntelligenceOCR(
            endpoint=endpoint,
            api_key=api_key,
            model=config.azure_document_model.strip(),
            timeout_seconds=config.azure_document_timeout_seconds,
        )
    if config.document_ocr_provider == "azure":
        raise ValueError(
            "Azure OCR is selected but CLAIM_GUARD_AZURE_DOCUMENT_ENDPOINT "
            "and CLAIM_GUARD_AZURE_DOCUMENT_API_KEY are not configured."
        )
    return None


def _safe_filename(value: str) -> str:
    basename = Path(value).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip("-.")
    return stem[:180] or "invoice.pdf"


@dataclass(frozen=True)
class NormalisedDocumentUpload:
    content: bytes
    stored_filename: str
    source_format: str


def normalise_document_upload(filename: str, content: bytes) -> NormalisedDocumentUpload:
    """Convert a supported upload to the PDF contract used by the extraction pipeline."""

    safe_name = _safe_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if not content or len(content) > settings.max_upload_bytes:
        raise ValueError(
            f"Document must be between 1 byte and {settings.max_upload_bytes} bytes."
        )
    if suffix == ".pdf":
        if content[:5] != b"%PDF-":
            raise ValueError("The uploaded PDF does not have a valid PDF signature.")
        return NormalisedDocumentUpload(content, safe_name, "pdf")

    signatures = {
        ".doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        ".docx": b"PK\x03\x04",
    }
    signature = signatures.get(suffix)
    if signature is None:
        raise ValueError("Only PDF, DOC, and DOCX documents are accepted.")
    if not content.startswith(signature):
        raise ValueError(f"The uploaded {suffix[1:].upper()} file signature is invalid.")

    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        raise ValueError(
            "Word document conversion is unavailable. Install LibreOffice on the "
            "backend host, or upload the document as PDF."
        )

    with TemporaryDirectory(prefix="claimguard-upload-") as directory:
        temp = Path(directory)
        source_path = temp / f"source{suffix}"
        source_path.write_bytes(content)
        profile = temp / "lo-profile"
        profile.mkdir()
        environment = os.environ.copy()
        command = [
            executable,
            "--headless",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(temp),
            str(source_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Word document conversion timed out after 60 seconds.") from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Word document conversion failed.") from exc

        generated = temp / "source.pdf"
        if not generated.exists():
            raise ValueError("Word document conversion did not produce a PDF.")
        pdf_content = generated.read_bytes()
        if not pdf_content.startswith(b"%PDF-"):
            raise ValueError("Word document conversion produced an invalid PDF.")
        if len(pdf_content) > settings.max_upload_bytes:
            raise ValueError(
                f"Converted PDF exceeds the {settings.max_upload_bytes}-byte upload limit."
            )
        stored_name = f"{Path(safe_name).stem}.pdf"
        return NormalisedDocumentUpload(pdf_content, stored_name, suffix[1:])


def _enum_or(enum_type, value: str, fallback):
    try:
        return enum_type(value)
    except ValueError:
        return fallback


def _extraction_method(value: str, *, invoice: bool = False) -> ExtractionMethod:
    mapping = {
        "native": ExtractionMethod.NATIVE_TEXT,
        "native_table": ExtractionMethod.NATIVE_TABLE,
        "ocr": ExtractionMethod.OCR,
        "azure_layout": ExtractionMethod.OCR,
        "vision_required": ExtractionMethod.VISION,
        "vision": ExtractionMethod.VISION,
    }
    if invoice and value == "native_table":
        return ExtractionMethod.NATIVE_TABLE
    return mapping.get(value, ExtractionMethod.PENDING)


def _severity(value: str) -> Severity:
    return {
        "info": Severity.INFO,
        "warning": Severity.WARNING,
        "review": Severity.WARNING,
        "high": Severity.ERROR,
        "error": Severity.ERROR,
        "critical": Severity.CRITICAL,
    }.get(value.lower(), Severity.WARNING)


def _check_status(value: str) -> CheckStatus:
    return {
        "pass": CheckStatus.PASS,
        "fail": CheckStatus.FAIL,
        "warning": CheckStatus.WARNING,
        "not_applicable": CheckStatus.NOT_APPLICABLE,
    }.get(value, CheckStatus.WARNING)


def store_pdf(
    session: Session,
    *,
    case: Case,
    filename: str,
    content: bytes,
    role: DocumentRole = DocumentRole.CURRENT,
) -> Document:
    """Normalise and immutably store a supported document before creating its record."""

    normalised = normalise_document_upload(filename, content)
    digest = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(Document).where(Document.case_id == case.id, Document.sha256 == digest)
    )
    if existing is not None:
        return existing

    storage_dir = Path(settings.storage_dir) / "cases" / case.id / digest[:12]
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / normalised.stored_filename
    stored_path.write_bytes(normalised.content)
    document = Document(
        case_id=case.id,
        document_role=role,
        original_filename=filename[:500],
        storage_path=str(stored_path),
        sha256=digest,
        mime_type="application/pdf",
        file_size=len(normalised.content),
        upload_status=UploadStatus.STORED,
        metadata_json={
            "safe_filename": normalised.stored_filename,
            "source_format": normalised.source_format,
        },
    )
    session.add(document)
    case.status = CaseStatus.UPLOADED
    session.flush()
    return document


def _new_run(
    session: Session,
    case: Case,
    *,
    make_current: bool = True,
) -> ProcessingRun:
    ontology_version = session.scalar(
        select(OntologyVersion).order_by(OntologyVersion.sequence_number.desc())
    )
    policy_bytes = POLICY_PATH.read_bytes() if POLICY_PATH.exists() else b"claimguard-v1.4"
    run = ProcessingRun(
        case_id=case.id,
        run_type=RunType.FULL,
        application_version=settings.app_version,
        configuration_hash=hashlib.sha256(policy_bytes).hexdigest(),
        ontology_version_id=ontology_version.id if ontology_version else None,
        benchmark_policy_version="claimguard-v1.4",
        model_provider=None,
        model_id=None,
        prompt_version=None,
        extraction_version="native-pdf-v1",
        status=RunStatus.RUNNING,
    )
    session.add(run)
    session.flush()
    if make_current:
        case.current_processing_run_id = run.id
        case.status = CaseStatus.PROCESSING
    return run


def _persist_claim_findings(
    session: Session,
    *,
    case: Case,
    document: Document,
    invoice: Invoice,
    invoice_descriptions: tuple[str, ...],
) -> None:
    context = case.claim_context
    if context is None:
        return
    claimant_vehicle = next(
        (
            vehicle
            for vehicle in context.vehicles
            if vehicle.vehicle_role == ClaimVehicleRole.CLAIMANT_VEHICLE
        ),
        None,
    )
    other_identities: list[ExistingInvoiceIdentity] = []
    rows = session.execute(
        select(Invoice, Document)
        .join(Document, Invoice.document_id == Document.id)
        .where(Invoice.case_id == case.id, Document.id != document.id)
    ).all()
    for other_invoice, other_document in rows:
        other_identities.append(
            ExistingInvoiceIdentity(
                invoice_number=other_invoice.invoice_number,
                document_sha256=other_document.sha256,
                supplier_name=other_invoice.supplier_name,
            )
        )
    facts = InvoiceClaimFacts(
        invoice_number=invoice.invoice_number,
        document_sha256=document.sha256,
        invoice_date=invoice.invoice_date,
        registration=invoice.vehicle.registration if invoice.vehicle else None,
        vehicle_make=invoice.vehicle.make if invoice.vehicle else None,
        vehicle_model=invoice.vehicle.model if invoice.vehicle else None,
        supplier_name=invoice.supplier_name,
        repair_descriptions=invoice_descriptions,
    )
    accident_date = context.accident_at.date() if context.accident_at else None
    findings = claim_invoice_consistency(
        accident_date=accident_date,
        claimant_registration=claimant_vehicle.registration if claimant_vehicle else None,
        claimant_vehicle_make=claimant_vehicle.make if claimant_vehicle else None,
        claimant_vehicle_model=claimant_vehicle.model if claimant_vehicle else None,
        damage_description=context.damage_description,
        invoice=facts,
        existing_invoices=other_identities,
    )
    for finding in findings:
        session.add(
            ClaimConsistencyFinding(
                claim_context_id=context.id,
                finding_code=finding.code,
                severity=_severity(finding.severity),
                status=ConsistencyFindingStatus.OPEN,
                source_entity_type="invoice",
                source_entity_id=invoice.id,
                explanation=finding.message,
            )
        )


def process_document(session: Session, document: Document) -> ProcessingRun:
    """Run native-first PDF analysis and persist pages, invoices, lines and checks."""

    case = session.get(Case, document.case_id)
    if case is None:
        raise ValueError("Document case does not exist.")
    previous_run_id = case.current_processing_run_id
    previous_case_status = case.status
    run = _new_run(session, case)
    document.upload_status = UploadStatus.PROCESSING
    session.flush()
    document_metadata = dict(document.metadata_json or {})
    manual_page_corrections = dict(document_metadata.get("page_corrections") or {})
    output_dir = Path(settings.storage_dir) / "cases" / case.id / document.sha256[:12] / "pages"
    cloud_ocr = _build_cloud_ocr(settings)
    vision_extractor = build_invoice_vision_extractor(settings)
    text_extractor = build_invoice_text_extractor(settings)
    pipeline = PDFPipeline(
        PipelineConfig(
            max_pages=settings.max_pdf_pages,
            ocr_enabled=settings.document_ocr_provider in {"auto", "tesseract"},
            vision_max_batches=settings.llm_vision_max_batches,
            text_max_batches=settings.llm_text_max_batches,
        ),
        cloud_ocr=cloud_ocr,
        vision_extractor=vision_extractor,
        text_extractor=text_extractor,
    )
    try:
        analysis = pipeline.analyse(document.storage_path, output_dir)
        document.page_count = analysis.page_count
        page_rows: dict[int, DocumentPage] = {}
        for page in analysis.pages:
            correction = manual_page_corrections.get(str(page.page_number)) or {}
            corrected_page_type = _enum_or(
                PageType,
                correction.get("page_type", page.page_type.value),
                PageType.OTHER,
            )
            page_row = DocumentPage(
                document_id=document.id,
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                rotation=correction.get("rotation", page.rotation),
                native_char_count=page.native_character_count,
                image_coverage=Decimal("1") if page.image_count else Decimal("0"),
                extraction_method=_extraction_method(page.extraction_method),
                page_type=corrected_page_type,
                classification_confidence=page.classification_confidence,
                group_id=correction.get("group_id", page.group_key),
                raw_text=page.text,
                rendered_image_path=(
                    str(page.rendered_image_path) if page.rendered_image_path else None
                ),
                page_hash=hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                review_status=(
                    ReviewStatus.CORRECTED
                    if correction
                    else ReviewStatus.NEEDS_REVIEW
                    if page.classification_confidence < 0.7
                    else ReviewStatus.PENDING
                ),
            )
            session.add(page_row)
            page_rows[page.page_number] = page_row
        session.flush()

        engineer_pages = [
            page for page in analysis.pages
            if page.page_type.value == PageType.ENGINEER_ASSESSMENT.value
        ]
        if engineer_pages and not analysis.invoices:
            document.document_kind = DocumentKind.ENGINEER_ASSESSMENT
            try:
                parsed = parse_engineer_assessment(engineer_pages)
            except ValueError:
                parsed = None
            if parsed is not None:
                assessment_fields = dict(parsed.fields)
                assessment_operations = parsed.operations
                assessment_confidence = parsed.confidence
                assessment_payload = {
                    "fields": {
                        key: value.isoformat() if hasattr(value, "isoformat") else str(value)
                        for key, value in parsed.fields.items()
                    },
                    "operation_count": len(parsed.operations),
                }
            elif analysis.engineer_assessments:
                extracted_assessment = analysis.engineer_assessments[0]
                assessment_fields = extracted_assessment.fields.model_dump()
                assessment_operations = extracted_assessment.operations
                assessment_confidence = extracted_assessment.extraction_confidence
                assessment_payload = extracted_assessment.model_dump(mode="json")
            else:
                # Deterministic parsing, vision, and the text-only LLM tier all failed to
                # produce usable repair operations. This must never dead-end the document:
                # fall through to manual review instead of failing the whole upload.
                assessment_fields = None
                assessment_operations = []
                assessment_confidence = None
                assessment_payload = None

            if assessment_fields is not None:
                assessment_fields["damage_areas_json"] = assessment_fields.pop(
                    "damage_areas", None
                )
                assessment = EngineerAssessment(
                    case_id=case.id,
                    document_id=document.id,
                    extraction_confidence=assessment_confidence,
                    review_status=(
                        ReviewStatus.APPROVED
                        if assessment_confidence > settings.auto_accept_confidence_threshold
                        else ReviewStatus.PENDING
                    ),
                    extraction_payload_json=assessment_payload,
                    **assessment_fields,
                )
                session.add(assessment)
                session.flush()
                for operation in assessment_operations:
                    page_row = page_rows.get(operation.page_number)
                    session.add(
                        AssessmentOperation(
                            assessment_id=assessment.id,
                            sequence_no=operation.sequence_no,
                            category=operation.category,
                            operation_code=operation.code,
                            part_number=getattr(operation, "part_number", None),
                            raw_description=operation.description,
                            normalised_description=normalise_operation(operation.description),
                            work_units=operation.work_units,
                            hours=operation.hours,
                            quantity=operation.quantity,
                            unit_price_net=operation.unit_price,
                            total_net=operation.total,
                            source_page_id=page_row.id if page_row else None,
                            extraction_confidence=assessment_confidence,
                        )
                    )
                session.flush()
            else:
                analysis.manual_review_reason = (
                    analysis.manual_review_reason
                    or "Engineer assessment could not be parsed automatically; manual "
                    "review required."
                )
        elif analysis.invoices:
            document.document_kind = DocumentKind.REPAIR_INVOICE
        else:
            document.document_kind = DocumentKind.UNKNOWN

        for extracted in analysis.invoices:
            header = extracted.header
            vehicle = Vehicle(
                case_id=case.id,
                registration=header.registration,
                vin=header.vin,
                make=header.vehicle_make,
                model=header.vehicle_model,
                variant=header.vehicle_variant,
                engine_cc=header.engine_cc,
                mileage=header.mileage,
                source="invoice_extraction",
                verification_status=ReviewStatus.PENDING,
            )
            registration = normalise_registration(header.registration)
            if registration and case.claim_context is not None:
                claim_vehicle = next(
                    (
                        candidate
                        for candidate in session.scalars(
                            select(ClaimVehicle).where(
                                ClaimVehicle.claim_context_id == case.claim_context.id
                            )
                        ).all()
                        if normalise_registration(candidate.registration) == registration
                    ),
                    None,
                )
                if claim_vehicle is not None:
                    apply_vehicle_classification(
                        vehicle,
                        classification_from_record(claim_vehicle),
                    )
            session.add(vehicle)
            session.flush()
            apply_lookup_to_vehicle(session, vehicle)
            group_id = (
                f"{extracted.document_role}:{header.invoice_number}"
                if header.invoice_number
                else f"{extracted.document_role}:pages-{','.join(map(str, extracted.page_numbers))}"
            )
            invoice = Invoice(
                case_id=case.id,
                document_id=document.id,
                document_group_id=group_id,
                document_role=(
                    InvoiceDocumentRole.ESTIMATE
                    if extracted.document_role == "estimate"
                    else InvoiceDocumentRole.INVOICE
                ),
                invoice_number=header.invoice_number,
                invoice_date=header.invoice_date,
                supplier_name=header.supplier_name,
                supplier_vat_number=header.supplier_vat_number,
                customer_name=header.customer_name,
                currency=header.currency,
                vehicle_id=vehicle.id,
                parts_net=extracted.totals.parts_net,
                labour_net=extracted.totals.labour_net,
                subtotal_net=extracted.totals.subtotal_net,
                vat_rate=extracted.totals.vat_rate,
                vat_total=extracted.totals.vat_amount,
                non_vat_total=extracted.totals.non_vatable,
                gross_total=extracted.totals.total_gross,
                extraction_method=_extraction_method(extracted.extraction_method, invoice=True),
                extraction_confidence=extracted.extraction_confidence,
                review_status=(
                    ReviewStatus.APPROVED
                    if extracted.extraction_confidence
                    > settings.auto_accept_confidence_threshold
                    else ReviewStatus.PENDING
                ),
                page_numbers_json=extracted.page_numbers,
                extraction_payload_json=extracted.model_dump(mode="json"),
            )
            session.add(invoice)
            session.flush()
            session.execute(
                invoice_page_links.insert(),
                [
                    {
                        "invoice_id": invoice.id,
                        "page_id": page_rows[number].id,
                        "page_order": order,
                    }
                    for order, number in enumerate(extracted.page_numbers, start=1)
                    if number in page_rows
                ],
            )

            line_rows: dict[int, InvoiceLineItem] = {}
            for line in extracted.line_items:
                source_page = page_rows.get(line.source.page_number)
                bbox = line.source.bbox
                line_row = InvoiceLineItem(
                    invoice_id=invoice.id,
                    sequence_no=line.sequence_no,
                    raw_description=line.raw_description,
                    normalised_description=line.normalised_description,
                    item_kind=_enum_or(LineItemKind, line.item_kind, LineItemKind.UNKNOWN),
                    part_number=line.part_number,
                    quantity=line.quantity,
                    unit=line.unit,
                    price_scope=PriceScope.LINE_TOTAL,
                    unit_price_net=line.unit_price_net,
                    line_total_net=line.line_total_net,
                    vat_rate=line.vat_rate,
                    vat_amount=line.vat_amount,
                    line_gross=line.gross_amount,
                    vat_applicable=line.vat_applicable,
                    derived_net=line.derived_net,
                    source_page_id=source_page.id if source_page else None,
                    source_bbox_json=([bbox.x0, bbox.y0, bbox.x1, bbox.y1] if bbox else None),
                    source_regions_json={
                        name: [region.x0, region.y0, region.x1, region.y1]
                        for name, region in line.source.regions.items()
                    }
                    or None,
                    source_raw_text=line.source.raw_text,
                    extraction_method=_extraction_method(line.source.extraction_method),
                    extraction_confidence=line.source.confidence,
                    status=(
                        ReviewStatus.APPROVED
                        if line.source.confidence
                        > settings.auto_accept_confidence_threshold
                        else ReviewStatus.NEEDS_REVIEW
                        if line.source.confidence
                        < settings.extraction_review_threshold
                        else ReviewStatus.PENDING
                    ),
                )
                session.add(line_row)
                line_rows[line.sequence_no] = line_row
            session.flush()

            for finding in validate_invoice(extracted):
                line_row = line_rows.get(finding.line_sequence_no or -1)
                session.add(
                    MathFinding(
                        invoice_id=invoice.id,
                        line_item_id=line_row.id if line_row else None,
                        check_code=finding.finding_type,
                        status=_check_status(finding.status),
                        severity=_severity(finding.severity),
                        expected_value=str(finding.expected)
                        if finding.expected is not None
                        else None,
                        observed_value=str(finding.found) if finding.found is not None else None,
                        difference=str(finding.difference)
                        if finding.difference is not None
                        else None,
                        tolerance=str(finding.tolerance) if finding.tolerance is not None else None,
                        explanation=finding.explanation,
                        is_challengeable=False,
                    )
                )
            _persist_claim_findings(
                session,
                case=case,
                document=document,
                invoice=invoice,
                invoice_descriptions=tuple(line.raw_description for line in extracted.line_items),
            )

        pair_case_assessments(session, case.id)

        document.upload_status = UploadStatus.READY
        if analysis.manual_review_reason:
            document_metadata["manual_review"] = True
            document_metadata["manual_review_reason"] = analysis.manual_review_reason
        else:
            document_metadata.pop("manual_review", None)
            document_metadata.pop("manual_review_reason", None)
        if manual_page_corrections:
            document_metadata["reprocess_required"] = False
            document_metadata.pop("reprocess_reason", None)
            document_metadata["last_reprocessed_with_page_corrections_at"] = datetime.now(
                UTC
            ).isoformat()
        document.metadata_json = document_metadata
        case.status = CaseStatus.EXTRACTION_REVIEW
        run.status = RunStatus.SUCCEEDED
        run.completed_at = datetime.now(UTC)
        run.metrics_json = {
            "page_count": analysis.page_count,
            "invoice_units": len(analysis.invoices),
            "extracted_lines": sum(len(invoice.line_items) for invoice in analysis.invoices),
        }
        if analysis.manual_review_reason:
            run.metrics_json["manual_review"] = True
            run.metrics_json["manual_review_reason"] = analysis.manual_review_reason
        if analysis.llm_failures:
            run.metrics_json["llm_failures"] = analysis.llm_failures
        if engineer_pages and not analysis.invoices and assessment_fields is not None:
            run.metrics_json["engineer_assessments"] = 1
    except Exception as exc:
        document_id = document.id
        case_id = case.id
        session.rollback()
        failed_document = session.get(Document, document_id)
        failed_case = session.get(Case, case_id)
        if failed_document is not None:
            failed_document.upload_status = UploadStatus.FAILED
        if failed_case is not None:
            failed_run = _new_run(session, failed_case, make_current=False)
            failed_run.status = RunStatus.FAILED
            failed_run.completed_at = datetime.now(UTC)
            failed_run.error_summary = str(exc)[:1000]
            previous_run = (
                session.get(ProcessingRun, previous_run_id) if previous_run_id else None
            )
            if previous_run is not None and previous_run.status == RunStatus.SUCCEEDED:
                failed_case.current_processing_run_id = previous_run.id
                failed_case.status = previous_case_status
            else:
                failed_case.current_processing_run_id = None
                failed_case.status = CaseStatus.FAILED
        session.commit()
        raise
    session.flush()
    return run


def serialise_document(document: Document) -> dict[str, Any]:
    metadata = document.metadata_json or {}
    invoice_units = len(document.invoices)
    inferred_manual_review = bool(
        document.upload_status == UploadStatus.READY
        and document.page_count
        and invoice_units == 0
        and document.engineer_assessment is None
    )
    manual_review = bool(metadata.get("manual_review")) or inferred_manual_review
    return {
        "id": document.id,
        "case_id": document.case_id,
        "filename": document.original_filename,
        "sha256": document.sha256,
        "role": document.document_role.value,
        "kind": document.document_kind.value,
        "paired": bool(
            document.engineer_assessment
            and document.engineer_assessment.paired_invoice_id
        ),
        "status": document.upload_status.value,
        "page_count": document.page_count,
        "invoice_units": invoice_units,
        "reprocess_required": bool(metadata.get("reprocess_required")),
        "manual_review": manual_review,
        "manual_review_reason": metadata.get("manual_review_reason")
        or (
            "No benchmarkable invoice line items were detected in this document."
            if inferred_manual_review
            else None
        ),
    }
