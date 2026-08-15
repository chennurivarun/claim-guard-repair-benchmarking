"""Pair Engineer Assessments with invoices and persist explainable variances."""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AssessmentInvoiceVariance,
    AssessmentOperation,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
    Vehicle,
)


ALIASES = {
    "front bumper remove refit": "front bumper remove refit",
    "r r front bumper": "front bumper remove refit",
    "front bumper": "front bumper remove refit",
    "radiator grille remove refit": "radiator grille remove refit",
    "r r radiator grille": "radiator grille remove refit",
    "radar sensor calibrate": "radar sensor calibrate",
    "front bumper repair paint plastic": "front bumper paint",
    "paint front bumper": "front bumper paint",
    "vehicle recovery": "vehicle recovery",
    "standard vehicle recovery": "vehicle recovery",
}


def normalise_operation(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    text = re.sub(r"\b(r and r|remove and refit|remove refit)\b", "remove refit", text)
    for alias, canonical in ALIASES.items():
        if alias in text:
            return canonical
    return text


def _match_score(left: str, right: str) -> float:
    left_norm = normalise_operation(left)
    right_norm = normalise_operation(right)
    if left_norm == right_norm:
        return 1.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def pair_case_assessments(session: Session, case_id: str) -> None:
    assessments = session.scalars(
        select(EngineerAssessment)
        .where(EngineerAssessment.case_id == case_id)
        .options(selectinload(EngineerAssessment.operations))
    ).all()
    invoices = session.scalars(
        select(Invoice)
        .where(Invoice.case_id == case_id)
        .options(selectinload(Invoice.vehicle), selectinload(Invoice.line_items))
    ).all()
    for assessment in assessments:
        candidates: list[tuple[float, Invoice, list[str]]] = []
        for invoice in invoices:
            reasons: list[str] = []
            score = 0.0
            invoice_registration = invoice.vehicle.registration if invoice.vehicle else None
            if assessment.registration and invoice_registration:
                if re.sub(r"\W", "", assessment.registration).upper() == re.sub(
                    r"\W", "", invoice_registration
                ).upper():
                    score += 0.70
                    reasons.append("registration exact match")
            if assessment.claim_reference and invoice.invoice_number:
                if assessment.claim_reference.upper() in invoice.invoice_number.upper():
                    score += 0.25
                    reasons.append("claim reference found in invoice number")
            if score:
                candidates.append((score, invoice, reasons))
        candidates.sort(key=lambda row: row[0], reverse=True)
        if not candidates or candidates[0][0] < 0.70:
            assessment.paired_invoice_id = None
            assessment.pair_status = "unpaired"
            assessment.pair_confidence = candidates[0][0] if candidates else 0.0
            assessment.pair_reasons_json = candidates[0][2] if candidates else ["no safe identifier match"]
            continue
        score, invoice, reasons = candidates[0]
        assessment.paired_invoice_id = invoice.id
        assessment.pair_status = "paired"
        assessment.pair_confidence = min(score, 1.0)
        assessment.pair_reasons_json = reasons
        operation_ids = [operation.id for operation in assessment.operations]
        if operation_ids:
            session.execute(
                delete(AssessmentInvoiceVariance).where(
                    AssessmentInvoiceVariance.assessment_operation_id.in_(operation_ids)
                )
            )
        used_lines: set[str] = set()
        for operation in assessment.operations:
            ranked = sorted(
                (
                    (_match_score(operation.raw_description, line.raw_description), line)
                    for line in invoice.line_items
                    if line.id not in used_lines
                ),
                key=lambda row: row[0],
                reverse=True,
            )
            if not ranked or ranked[0][0] < 0.34:
                continue
            match_confidence, line = ranked[0]
            used_lines.add(line.id)
            engineer = Decimal(operation.total_net) if operation.total_net is not None else None
            billed = Decimal(line.line_total_net) if line.line_total_net is not None else None
            difference = billed - engineer if engineer is not None and billed is not None else None
            percentage = (
                difference / engineer * Decimal("100")
                if difference is not None and engineer not in {None, Decimal("0")}
                else None
            )
            threshold = (
                "above_10_percent"
                if difference is not None and percentage is not None
                and difference >= Decimal("5") and percentage > Decimal("10")
                else "above_5_percent"
                if difference is not None and percentage is not None
                and difference >= Decimal("5") and percentage > Decimal("5")
                else "within_threshold"
            )
            session.add(
                AssessmentInvoiceVariance(
                    assessment_operation_id=operation.id,
                    invoice_id=invoice.id,
                    invoice_line_item_id=line.id,
                    matching_method="canonical_description",
                    match_confidence=match_confidence,
                    engineer_amount=engineer,
                    invoice_amount=billed,
                    difference_amount=difference,
                    difference_percentage=percentage,
                    threshold_status=threshold,
                    explanation=(
                        f"Invoice £{billed:.2f} versus engineer assessment £{engineer:.2f}; "
                        f"variance £{difference:.2f} ({percentage:.1f}%)."
                        if None not in {engineer, billed, difference, percentage}
                        else "Comparable descriptions matched; monetary comparison unavailable."
                    ),
                )
            )


def engineer_assessment_payload(assessment: EngineerAssessment) -> dict:
    return {
        "id": assessment.id,
        "document_id": assessment.document_id,
        "assessment_number": assessment.assessment_number,
        "claim_reference": assessment.claim_reference,
        "registration": assessment.registration,
        "pair_status": assessment.pair_status,
        "pair_confidence": assessment.pair_confidence,
        "pair_reasons": assessment.pair_reasons_json or [],
        "paired_invoice_id": assessment.paired_invoice_id,
        "totals": {
            "labour_net": assessment.labour_net,
            "paint_net": assessment.paint_net,
            "parts_net": assessment.parts_net,
            "extras_net": assessment.extras_net,
            "subtotal_net": assessment.subtotal_net,
            "vat_total": assessment.vat_total,
            "gross_total": assessment.gross_total,
        },
        "operations": [
            {
                "id": operation.id,
                "category": operation.category,
                "code": operation.operation_code,
                "description": operation.raw_description,
                "total_net": operation.total_net,
                "source_page_id": operation.source_page_id,
                "variances": [
                    {
                        "invoice_id": variance.invoice_id,
                        "invoice_line_item_id": variance.invoice_line_item_id,
                        "engineer_amount": variance.engineer_amount,
                        "invoice_amount": variance.invoice_amount,
                        "difference_amount": variance.difference_amount,
                        "difference_percentage": variance.difference_percentage,
                        "threshold_status": variance.threshold_status,
                        "explanation": variance.explanation,
                    }
                    for variance in operation.variances
                ],
            }
            for operation in assessment.operations
        ],
    }
