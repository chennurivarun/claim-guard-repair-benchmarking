from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import (
    AuditActorType,
    CaseStatus,
    CheckStatus,
    ReviewStatus,
    Severity,
)
from app.extraction.calculation_validator import validate_invoice
from app.extraction.schemas import (
    ExtractedInvoice,
    ExtractedLine,
    FieldSource,
    InvoiceHeader,
    InvoiceTotals,
)
from app.models import AuditEvent, Invoice, InvoiceLineItem, MathFinding

settings = get_settings()


def _check_status(value: str) -> CheckStatus:
    return {
        "pass": CheckStatus.PASS,
        "fail": CheckStatus.FAIL,
        "warning": CheckStatus.WARNING,
        "not_applicable": CheckStatus.NOT_APPLICABLE,
    }.get(value, CheckStatus.WARNING)


def _severity(value: str) -> Severity:
    return {
        "info": Severity.INFO,
        "warning": Severity.WARNING,
        "review": Severity.WARNING,
        "high": Severity.ERROR,
        "error": Severity.ERROR,
        "critical": Severity.CRITICAL,
    }.get(value.lower(), Severity.WARNING)


def _as_extracted_invoice(invoice: Invoice) -> ExtractedInvoice:
    active_lines = [line for line in invoice.line_items if line.status != ReviewStatus.REJECTED]
    return ExtractedInvoice(
        header=InvoiceHeader(
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            supplier_name=invoice.supplier_name,
            supplier_vat_number=invoice.supplier_vat_number,
            customer_name=invoice.customer_name,
            currency=invoice.currency,
        ),
        totals=InvoiceTotals(
            labour_net=invoice.labour_net,
            parts_net=invoice.parts_net,
            subtotal_net=invoice.subtotal_net,
            vat_rate=invoice.vat_rate,
            vat_amount=invoice.vat_total,
            non_vatable=invoice.non_vat_total,
            total_gross=invoice.gross_total,
        ),
        line_items=[
            ExtractedLine(
                sequence_no=line.sequence_no,
                raw_description=line.raw_description,
                normalised_description=line.normalised_description or line.raw_description.lower(),
                item_kind=line.item_kind.value,
                part_number=line.part_number,
                quantity=Decimal(line.quantity) if line.quantity is not None else None,
                unit=line.unit,
                unit_price_net=(
                    Decimal(line.unit_price_net) if line.unit_price_net is not None else None
                ),
                line_total_net=(
                    Decimal(line.line_total_net) if line.line_total_net is not None else None
                ),
                vat_rate=Decimal(line.vat_rate) if line.vat_rate is not None else None,
                vat_amount=Decimal(line.vat_amount) if line.vat_amount is not None else None,
                gross_amount=Decimal(line.line_gross) if line.line_gross is not None else None,
                vat_applicable=line.vat_applicable is not False,
                derived_net=line.derived_net,
                source=FieldSource(
                    page_number=line.source_page.page_number if line.source_page else 1,
                    raw_text=line.source_raw_text,
                    extraction_method=line.extraction_method.value,
                    confidence=line.extraction_confidence or 0,
                    precision="exact" if line.source_regions_json else "approximate",
                ),
            )
            for line in active_lines
        ],
        page_numbers=invoice.page_numbers_json or [1],
        document_role=invoice.document_role.value,
        extraction_method=invoice.extraction_method.value,
        extraction_confidence=invoice.extraction_confidence or 0,
    )


def recalculate_invoice_findings(session: Session, invoice: Invoice) -> None:
    session.execute(delete(MathFinding).where(MathFinding.invoice_id == invoice.id))
    session.flush()
    lines_by_sequence = {line.sequence_no: line for line in invoice.line_items}
    for finding in validate_invoice(_as_extracted_invoice(invoice)):
        line = lines_by_sequence.get(finding.line_sequence_no or -1)
        session.add(
            MathFinding(
                invoice_id=invoice.id,
                line_item_id=line.id if line else None,
                check_code=finding.finding_type,
                status=_check_status(finding.status),
                severity=_severity(finding.severity),
                expected_value=str(finding.expected) if finding.expected is not None else None,
                observed_value=str(finding.found) if finding.found is not None else None,
                difference=str(finding.difference) if finding.difference is not None else None,
                tolerance=str(finding.tolerance) if finding.tolerance is not None else None,
                explanation=finding.explanation,
                is_challengeable=False,
            )
        )


def review_extraction_line(
    session: Session,
    *,
    line: InvoiceLineItem,
    decision: str,
    actor: str,
    reason: str | None,
) -> InvoiceLineItem:
    if line.invoice.case.status == CaseStatus.FINALISED:
        raise ValueError("Create a new revision before reviewing a finalised case.")

    previous_status = line.status
    if decision == "approved":
        line.status = ReviewStatus.APPROVED
        event_type = "INVOICE_LINE_EXTRACTION_APPROVED"
    elif decision == "rejected":
        line.status = ReviewStatus.REJECTED
        event_type = "INVOICE_LINE_EXTRACTION_REJECTED"
    elif decision == "undo":
        line.status = (
            ReviewStatus.APPROVED
            if (line.extraction_confidence or 0)
            > settings.auto_accept_confidence_threshold
            else ReviewStatus.NEEDS_REVIEW
            if (line.extraction_confidence or 0)
            < settings.extraction_review_threshold
            else ReviewStatus.PENDING
        )
        event_type = "INVOICE_LINE_EXTRACTION_RESTORED"
    else:  # Defensive: request validation should reject this first.
        raise ValueError("Unsupported extraction decision.")

    line.invoice.case.status = CaseStatus.EXTRACTION_REVIEW
    recalculate_invoice_findings(session, line.invoice)
    session.add(
        AuditEvent(
            case_id=line.invoice.case_id,
            processing_run_id=line.invoice.case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type=event_type,
            entity_type="invoice_line_item",
            entity_id=line.id,
            before_json={"status": previous_status.value},
            after_json={"status": line.status.value, "reason": reason},
            event_payload_json={
                "original_extraction_retained": True,
                "excluded_from_downstream": line.status == ReviewStatus.REJECTED,
                "calculations_refreshed": True,
            },
        )
    )
    session.commit()
    session.refresh(line)
    return line
