"""Upload-to-database document processing.

``EngineerAssessment.extraction_payload_json`` is written by two different
tiers and readers must not have to know which one produced it, so these keys
are present either way (null when that tier has nothing to put in them):

``printed_work_units`` / ``printed_totals``
    ``{line_item_type: {printed label: amount as a string}}`` -- every figure
    the report printed for a section, kept under the label it was printed
    beside, because a PARTS band prints a sub-total, a sundry line and a
    section total and only one of them is the row sum.
``row_work_units`` / ``row_totals``
    ``{line_item_type: amount as a string}`` -- the sum of the rows actually
    read for that section. Never reconciled against the printed figures.
``printed_row_disagreements``
    A list of ``{line_item_type, measure, printed_label, printed, rows,
    difference}``, one per section whose printed figures all differ from its
    row sum. The same disagreements are filed as
    ``ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT`` claim consistency findings.
``deterministic_operations``
    Deterministic tier only: per-operation detail with no column of its own
    (``sequence_no``, ``line_item_type``, ``raw_category``, ``price_derived``,
    ``part_number_raw``). Null on the LLM tiers, whose payload carries its own
    ``operations`` key holding the full extracted model instead.
"""

from __future__ import annotations

import hashlib
import mimetypes
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
from app.domain.line_item_type import UNKNOWN as UNKNOWN_LINE_ITEM_TYPE
from app.domain.line_item_type import ensure_line_item_type
from app.enums import (
    AuditActorType,
    CaseStatus,
    CheckStatus,
    ClaimVehicleRole,
    ConsistencyFindingStatus,
    DocumentKind,
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    OntologyVersionStatus,
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
from app.extraction.docx_ingest import docx_to_pdf_bytes
from app.extraction.engineer_assessment_parser import (
    ParsedEngineerAssessment,
    parse_engineer_assessment,
)
from app.extraction.pdf_pipeline import PDFPipeline, PipelineConfig
from app.llm.document_briefing import (
    DocumentBriefingPage,
    build_document_briefing,
    build_document_briefing_generator,
)
from app.llm.factory import build_invoice_text_extractor, build_invoice_vision_extractor
from app.models import (
    AssessmentOperation,
    AuditEvent,
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

    stored_name = f"{Path(safe_name).stem}.pdf"
    executable = shutil.which("soffice") or shutil.which("libreoffice")

    if suffix == ".doc":
        # Legacy binary .doc cannot be parsed by python-docx; LibreOffice is required.
        if not executable:
            raise ValueError(
                "DOC (legacy) files require LibreOffice to convert. Install LibreOffice "
                "on the backend host, or upload the document as PDF or DOCX -- DOCX "
                "uploads work without LibreOffice."
            )
        pdf_content = _convert_with_libreoffice(executable, suffix, content)
        return NormalisedDocumentUpload(pdf_content, stored_name, "doc")

    # .docx: use the deterministic renderer first. LibreOffice can reflow
    # side-by-side Word tables when it creates a PDF, splitting identity and
    # assessment rows across lines. The renderer preserves the document's
    # block/table order for the extraction parser. LibreOffice remains a
    # fallback for DOCX files containing constructs the renderer cannot read.
    try:
        pdf_content = docx_to_pdf_bytes(content)
    except Exception as python_exc:
        if not executable:
            raise ValueError(f"DOCX document could not be read: {python_exc}") from python_exc
        try:
            pdf_content = _convert_with_libreoffice(executable, suffix, content)
        except ValueError as libreoffice_exc:
            raise ValueError(f"DOCX document could not be read: {python_exc}") from libreoffice_exc
        return NormalisedDocumentUpload(pdf_content, stored_name, "docx-libreoffice")
    if len(pdf_content) > settings.max_upload_bytes:
        raise ValueError(
            f"Converted PDF exceeds the {settings.max_upload_bytes}-byte upload limit."
        )
    return NormalisedDocumentUpload(pdf_content, stored_name, "docx-python")


def _convert_with_libreoffice(executable: str, suffix: str, content: bytes) -> bytes:
    """Convert a .doc/.docx payload to PDF bytes via a headless LibreOffice process."""

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
        return pdf_content


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
        "medium": Severity.WARNING,
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


LIVE_INTAKE_GROUP = "live"
#: How each upload source is named to the user (matches ``source_benchmarks``).
_INTAKE_GROUP_LABELS = {
    "historical_claim": "Third party insured invoices",
    "in_house": "Aviva DLG invoices",
    LIVE_INTAKE_GROUP: "the new invoice being checked",
}


def _reuse_existing_upload(existing: list[Document], intake_group: str | None) -> Document | None:
    """Decide what an upload of bytes already on this claim means.

    Returns the document to reuse, ``None`` when a new copy should be stored,
    or raises when the copy would let an invoice be benchmarked against itself.
    """

    if not intake_group:
        # No source chosen: the file is already here, whichever source holds it.
        return existing[0]
    groups = {document.intake_group for document in existing}
    same_source = [document for document in existing if document.intake_group == intake_group]
    if same_source:
        return same_source[0]

    if intake_group == LIVE_INTAKE_GROUP:
        holders = sorted(
            _INTAKE_GROUP_LABELS.get(group, group) for group in groups if group is not None
        )
        if holders:
            raise ValueError(
                f"This file is already in {' and '.join(holders)}, "
                "so it cannot also be the new invoice being checked: it would be "
                "benchmarked against its own copy, match itself and hide every "
                "discrepancy. Upload the new invoice itself."
            )
        raise ValueError(
            "This file is already on this claim without an upload source, so it "
            "cannot also be the new invoice being checked. Upload the new invoice itself."
        )
    if LIVE_INTAKE_GROUP in groups:
        raise ValueError(
            "This file is already the new invoice being checked, so it cannot also go "
            f"into {_INTAKE_GROUP_LABELS.get(intake_group, intake_group)}: "
            "the new invoice would be benchmarked against its own copy, match itself "
            "and hide every discrepancy."
        )

    ungrouped = next((document for document in existing if document.intake_group is None), None)
    if ungrouped is not None:
        # Re-upload is an explicit selection of an existing client file.
        ungrouped.metadata_json = {**(ungrouped.metadata_json or {}), "intake_group": intake_group}
        ungrouped.intake_group = intake_group
        ungrouped.document_role = DocumentRole.HISTORICAL
        return ungrouped
    # Held only by the other reference source: this source gets its own copy.
    return None


def store_pdf(
    session: Session,
    *,
    case: Case,
    filename: str,
    content: bytes,
    role: DocumentRole = DocumentRole.CURRENT,
    intake_group: str | None = None,
    paired_document_id: str | None = None,
) -> Document:
    """Normalise and immutably store a supported document before creating its record."""

    normalised = normalise_document_upload(filename, content)
    digest = hashlib.sha256(content).hexdigest()
    # The column, not the metadata key: it is what the unique constraint
    # enforces, so the lookup and the database agree on what "already here" is.
    existing = session.scalars(
        select(Document)
        .where(Document.case_id == case.id, Document.sha256 == digest)
        .order_by(Document.created_at, Document.id)
    ).all()
    if existing:
        reused = _reuse_existing_upload(existing, intake_group)
        if reused is not None:
            return reused

    # A byte-identical file may now be stored once per source, so each copy
    # gets its own directory: its stored file and rendered pages are its own,
    # and reprocessing one copy never rewrites the files the other is serving.
    storage_dir = Path(settings.storage_dir) / "cases" / case.id / digest[:12]
    if intake_group:
        storage_dir = storage_dir / intake_group
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / normalised.stored_filename
    stored_path.write_bytes(normalised.content)
    # Keep the byte-for-byte upload alongside the normalized PDF. Extraction
    # needs the PDF contract, while handlers need to inspect exactly what was
    # submitted (especially when the upload was a DOCX later rendered to PDF).
    original_dir = storage_dir / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    original_path = original_dir / _safe_filename(filename)
    original_path.write_bytes(content)
    original_mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
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
            "original_storage_path": str(original_path),
            "original_mime_type": original_mime_type,
            "intake_group": intake_group,
            "paired_document_id": paired_document_id,
        },
        intake_group=intake_group,
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
        select(OntologyVersion)
        .where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
        .order_by(OntologyVersion.sequence_number.desc())
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


def _json_amounts(bucket: dict[str, dict[str, Decimal]]) -> dict[str, dict[str, str]]:
    """Render a two-level ``{type: {label: amount}}`` map JSON-safe."""

    return {
        code: {label: str(amount) for label, amount in labels.items()}
        for code, labels in bucket.items()
    }


#: A printed figure and the rows beneath it are allowed to differ by rounding
#: without that being a disagreement worth a handler's time.
_PRINTED_ROW_TOLERANCE = Decimal("0.05")

#: The claim consistency finding a printed-versus-row disagreement is filed as.
_ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT = "ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT"


def _printed_row_disagreements(
    parsed: ParsedEngineerAssessment,
) -> list[dict[str, str]]:
    """Report where a report's printed section figures and its rows disagree.

    Nothing is corrected. The report's own arithmetic is the evidence the
    client asked to see, so both numbers are kept exactly as found and the
    disagreement is recorded beside them. A section is in agreement when *any*
    figure printed for it matches the row sum -- a PARTS band prints a
    sub-total, a sundry line and a section total, and the rows only ever
    reproduce one of them.
    """

    disagreements: list[dict[str, str]] = []
    for measure, printed, rows in (
        ("work units", parsed.printed_work_units, parsed.row_work_units),
        ("total", parsed.printed_totals, parsed.row_totals),
    ):
        for code, labels in printed.items():
            row_value = rows.get(code)
            if row_value is None or not labels:
                continue
            if any(
                abs(amount - row_value) <= _PRINTED_ROW_TOLERANCE
                for amount in labels.values()
            ):
                continue
            label, amount = min(
                labels.items(), key=lambda item: abs(item[1] - row_value)
            )
            disagreements.append(
                {
                    "line_item_type": code,
                    "measure": measure,
                    "printed_label": label,
                    "printed": str(amount),
                    "rows": str(row_value),
                    "difference": str(amount - row_value),
                }
            )
    return disagreements


def _persist_assessment_arithmetic_findings(
    session: Session,
    *,
    case: Case,
    assessment: EngineerAssessment,
    disagreements: list[dict[str, str]],
) -> None:
    """Record printed-versus-row disagreements as claim consistency findings.

    Medium severity: the report is internally inconsistent, which a handler
    must see, but nothing about it is corrected or blocked. The figures also
    live in the assessment's extraction payload, so they survive a case that
    has no claim context to hang a finding on.

    A forced reprocess deletes the ``engineer_assessments`` row and writes a
    new one, but nothing has a foreign key onto it from here, so the findings
    it left behind would accumulate on every run and point at an id that no
    longer resolves. Everything this assessment owns -- its own findings, and
    the orphans of the assessments it replaced -- is cleared first.
    """

    context = case.claim_context
    if context is None:
        return
    stale = list(
        session.scalars(
            select(ClaimConsistencyFinding).where(
                ClaimConsistencyFinding.claim_context_id == context.id,
                ClaimConsistencyFinding.finding_code
                == _ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT,
                ClaimConsistencyFinding.source_entity_type == "engineer_assessment",
            )
        ).all()
    )
    if stale:
        referenced = {
            finding.source_entity_id for finding in stale if finding.source_entity_id
        }
        live_assessment_ids = set(
            session.scalars(
                select(EngineerAssessment.id).where(EngineerAssessment.id.in_(referenced))
            ).all()
        )
        for finding in stale:
            if (
                finding.source_entity_id == assessment.id
                or finding.source_entity_id not in live_assessment_ids
            ):
                session.delete(finding)
        session.flush()
    for disagreement in disagreements:
        session.add(
            ClaimConsistencyFinding(
                claim_context_id=context.id,
                finding_code=_ASSESSMENT_PRINTED_TOTAL_DISAGREEMENT,
                severity=_severity("medium"),
                status=ConsistencyFindingStatus.OPEN,
                field_name=f"{disagreement['line_item_type']} {disagreement['measure']}",
                expected_value=disagreement["printed"],
                observed_value=disagreement["rows"],
                source_entity_type="engineer_assessment",
                source_entity_id=assessment.id,
                explanation=(
                    f"The engineer assessment prints {disagreement['line_item_type']} "
                    f"{disagreement['measure']} of {disagreement['printed']} "
                    f"({disagreement['printed_label']}) but its own rows total "
                    f"{disagreement['rows']}. Both figures are recorded as printed; "
                    "neither has been corrected."
                ),
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
    # Beside the stored file, not rebuilt from the hash: two copies of one file
    # (one per upload source) share a hash but never a directory.  For every
    # document stored before per-source directories this is the same path.
    output_dir = Path(document.storage_path).parent / "pages"
    cloud_ocr = _build_cloud_ocr(settings)
    vision_extractor = build_invoice_vision_extractor(settings)
    text_extractor = build_invoice_text_extractor(settings)
    briefing_generator = build_document_briefing_generator(settings)
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

        # A report's schedule runs onto pages with no identity marker of their
        # own; `pdf_pipeline._reclassify_priced_assessment_pages` has already
        # recognised those as continuations and typed them ENGINEER_ASSESSMENT,
        # so the page type the document stores and the pages the parser reads
        # are the same set.
        engineer_pages = [
            page for page in analysis.pages
            if page.page_type.value == PageType.ENGINEER_ASSESSMENT.value
        ]
        if document_metadata.get("paired_document_id"):
            engineer_pages = analysis.pages
            for page_row in page_rows.values():
                page_row.page_type = PageType.ENGINEER_ASSESSMENT
        if document_metadata.get("intake_group") and engineer_pages:
            # A separately supplied estimate is supporting evidence, never an
            # additional repair invoice or a reference price observation.
            analysis.invoices = []
        has_benchmarkable_lines = any(
            # `ExtractedLine.benchmarkable` already excludes section totals;
            # the clause is repeated here because this is the governance
            # boundary that decides whether a document can be benchmarked.
            line.benchmarkable and not line.is_section_total
            for extracted in analysis.invoices
            for line in extracted.line_items
        )
        assessment_fields = None
        if engineer_pages:
            # A document can be BOTH an engineer assessment AND carry priced
            # pages: the kind stays ENGINEER_ASSESSMENT while every extracted
            # invoice unit below is persisted exactly as for invoice documents.
            document.document_kind = DocumentKind.ENGINEER_ASSESSMENT
            try:
                parsed = parse_engineer_assessment(engineer_pages)
            except ValueError:
                parsed = None
            if parsed is not None:
                assessment_fields = dict(parsed.fields)
                assessment_operations = parsed.operations
                assessment_confidence = parsed.confidence
                assessment_disagreements = _printed_row_disagreements(parsed)
                assessment_payload = {
                    "fields": {
                        key: value.isoformat() if hasattr(value, "isoformat") else str(value)
                        for key, value in parsed.fields.items()
                    },
                    "operation_count": len(parsed.operations),
                    # Printed figures and row sums are kept side by side and
                    # never reconciled: `assessment_operations` has no column
                    # for either, and the disagreement between them is the
                    # finding, not a value to correct.
                    "printed_work_units": _json_amounts(parsed.printed_work_units),
                    "printed_totals": _json_amounts(parsed.printed_totals),
                    "row_work_units": {
                        code: str(amount) for code, amount in parsed.row_work_units.items()
                    },
                    "row_totals": {
                        code: str(amount) for code, amount in parsed.row_totals.items()
                    },
                    "printed_row_disagreements": assessment_disagreements,
                    # Per-operation detail with no column of its own. Namespaced
                    # because the LLM tier's payload has an "operations" key of
                    # its own with an entirely different shape.
                    "deterministic_operations": [
                        {
                            "sequence_no": operation.sequence_no,
                            "line_item_type": operation.line_item_type,
                            "raw_category": operation.raw_category,
                            "price_derived": operation.price_derived,
                            "part_number_raw": operation.part_number_raw,
                        }
                        for operation in parsed.operations
                    ],
                }
            elif analysis.engineer_assessments:
                extracted_assessment = analysis.engineer_assessments[0]
                assessment_fields = extracted_assessment.fields.model_dump()
                assessment_operations = extracted_assessment.operations
                assessment_confidence = extracted_assessment.extraction_confidence
                # The LLM tiers report no printed section figures, so there is
                # nothing to disagree with. The keys are still written, as
                # nulls, so a reader never has to know which tier produced the
                # payload to know whether printed figures were found.
                assessment_disagreements = []
                assessment_payload = {
                    **extracted_assessment.model_dump(mode="json"),
                    "printed_work_units": None,
                    "printed_totals": None,
                    "row_work_units": None,
                    "row_totals": None,
                    "printed_row_disagreements": [],
                    "deterministic_operations": None,
                }
            else:
                # Deterministic parsing, vision, and the text-only LLM tier all failed to
                # produce usable repair operations. This must never dead-end the document:
                # fall through to manual review instead of failing the whole upload.
                assessment_fields = None
                assessment_operations = []
                assessment_confidence = None
                assessment_payload = None
                assessment_disagreements = []

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
                    # `category` is the canonical section code; the heading as
                    # printed is kept beside it. The LLM tiers report their
                    # section in `category` and leave `line_item_type` unset,
                    # so whichever one carries the heading is normalised.
                    section = getattr(operation, "line_item_type", None)
                    if not section or section == UNKNOWN_LINE_ITEM_TYPE:
                        section = operation.category
                    raw_category = (
                        getattr(operation, "raw_category", None) or operation.category
                    )
                    session.add(
                        AssessmentOperation(
                            assessment_id=assessment.id,
                            sequence_no=operation.sequence_no,
                            category=ensure_line_item_type(section),
                            raw_category=raw_category[:160] if raw_category else None,
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
                _persist_assessment_arithmetic_findings(
                    session,
                    case=case,
                    assessment=assessment,
                    disagreements=assessment_disagreements,
                )
                session.flush()
            elif not has_benchmarkable_lines:
                # Manual review only when NEITHER a usable assessment NOR any
                # benchmarkable invoice line was produced for this document.
                analysis.manual_review_reason = (
                    analysis.manual_review_reason
                    or "Engineer assessment could not be parsed automatically; manual "
                    "review required."
                )
        elif analysis.invoices:
            document.document_kind = DocumentKind.REPAIR_INVOICE
        else:
            document.document_kind = DocumentKind.UNKNOWN

        used_group_ids: set[str] = set()
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
            if group_id in used_group_ids:
                # Retained invoices may share a parsed number (uq_invoices_document_group);
                # disambiguate by page span instead of discarding either unit.
                group_id = (
                    f"{group_id}:pages-{','.join(map(str, extracted.page_numbers))}"
                )
            counter = 2
            while group_id in used_group_ids:
                group_id = f"{group_id}#{counter}"
                counter += 1
            used_group_ids.add(group_id)
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
                claim_reference=header.claim_reference,
                policy_number=header.policy_number,
                currency=header.currency,
                vehicle_id=vehicle.id,
                parts_net=extracted.totals.parts_net,
                labour_net=extracted.totals.labour_net,
                paint_net=extracted.totals.paint_net,
                # "Additional charges" / EXTRAS: the existing, until now
                # unwritten, column rather than a new one.
                other_net=extracted.totals.extras_net,
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
            if header.assessment_reference and not document_metadata.get(
                "assessment_reference"
            ):
                # There is no column for this and there must not be one: the
                # reference an invoice prints matches no assessment on the
                # paired report (Format 2 prints "BOY1537"), so it is display
                # evidence only and must never be keyed on. It also survives in
                # extraction_payload_json["header"]["assessment_reference"].
                document_metadata["assessment_reference"] = header.assessment_reference
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
                    # The printed section the row sat in, its heading verbatim,
                    # and whether the row is the section's rolled-up total
                    # rather than a priced item.
                    line_item_type=line.line_item_type,
                    raw_category=line.raw_category,
                    is_section_total=line.is_section_total,
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
                # A section total is a heading with a number on it, never a
                # repair description, so it is no evidence of what was done.
                invoice_descriptions=tuple(
                    line.raw_description
                    for line in extracted.line_items
                    if not line.is_section_total
                ),
            )

        if not analysis.invoices and analysis.manual_review_reason:
            # A fully unreadable document still needs an invoice container so a
            # handler can enter billable lines from the page images. Without
            # this shell the Manual review UI has a document but no invoice_id,
            # making its manual-entry action impossible.
            placeholder_invoice = Invoice(
                case_id=case.id,
                document_id=document.id,
                document_group_id="manual-review",
                document_role=InvoiceDocumentRole.INVOICE,
                currency="GBP",
                extraction_method=ExtractionMethod.PENDING,
                extraction_confidence=0.0,
                review_status=ReviewStatus.NEEDS_REVIEW,
                page_numbers_json=sorted(page_rows),
                extraction_payload_json={
                    "manual_entry_placeholder": True,
                    "manual_review_reason": analysis.manual_review_reason,
                },
            )
            session.add(placeholder_invoice)
            session.flush()
            if page_rows:
                session.execute(
                    invoice_page_links.insert(),
                    [
                        {
                            "invoice_id": placeholder_invoice.id,
                            "page_id": page_rows[number].id,
                            "page_order": order,
                        }
                        for order, number in enumerate(sorted(page_rows), start=1)
                    ],
                )

        pair_case_assessments(session, case.id)
        # Pairing writes its gap-fill attribution onto the *invoice's*
        # document, which is this one whenever the invoice is uploaded after
        # its assessment. ``document_metadata`` was snapshotted before that,
        # so carry the attribution across or the write below discards it.
        document_metadata["field_sources"] = (document.metadata_json or {}).get(
            "field_sources", {}
        )

        document.upload_status = UploadStatus.READY
        if analysis.manual_review_reason:
            document_metadata["manual_review"] = True
            document_metadata["manual_review_reason"] = analysis.manual_review_reason
            briefing_pages = [
                DocumentBriefingPage(
                    page_number=page_row.page_number,
                    page_type=page_row.page_type.value,
                    text=page_row.raw_text or "",
                    classification_confidence=page_row.classification_confidence,
                )
                for page_row in sorted(page_rows.values(), key=lambda row: row.page_number)
            ]
            document.review_briefing_json = build_document_briefing(
                briefing_generator,
                pages=briefing_pages,
                manual_review_reason=analysis.manual_review_reason,
            )
            session.add(
                AuditEvent(
                    case_id=case.id,
                    processing_run_id=run.id,
                    actor_type=AuditActorType.SYSTEM,
                    actor_id="document_briefing_generator",
                    event_type="DOCUMENT_BRIEFING_RECORDED",
                    entity_type="document",
                    entity_id=document.id,
                    after_json={
                        "fallback": document.review_briefing_json.get("fallback"),
                        "manual_review_reason": analysis.manual_review_reason,
                    },
                    event_payload_json={
                        "model": document.review_briefing_json.get("model"),
                        "prompt_version": document.review_briefing_json.get("prompt_version"),
                    },
                )
            )
        else:
            document_metadata.pop("manual_review", None)
            document_metadata.pop("manual_review_reason", None)
            document.review_briefing_json = None
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
        if engineer_pages and assessment_fields is not None:
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
    original_url = (
        f"/api/v1/documents/{document.id}/original"
        if metadata.get("original_storage_path")
        else None
    )
    return {
        "id": document.id,
        "case_id": document.case_id,
        "filename": document.original_filename,
        "original_url": original_url,
        "sha256": document.sha256,
        "role": document.document_role.value,
        "intake_group": metadata.get("intake_group"),
        "kind": document.document_kind.value,
        "paired": bool(
            document.engineer_assessment
            and document.engineer_assessment.paired_invoice_id
        ),
        "status": document.upload_status.value,
        "page_count": document.page_count,
        "invoice_units": invoice_units,
        "review_briefing": document.review_briefing_json,
        "reprocess_required": bool(metadata.get("reprocess_required")),
        "manual_review": manual_review,
        "manual_review_reason": metadata.get("manual_review_reason")
        or (
            "No benchmarkable invoice line items were detected in this document."
            if inferred_manual_review
            else None
        ),
    }
