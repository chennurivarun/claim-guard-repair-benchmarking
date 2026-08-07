from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class LiabilityState(StrEnum):
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    SPLIT_LIABILITY = "SPLIT LIABILITY"
    PENDING = "PENDING"
    HUMAN_REVIEW_REQUIRED = "HUMAN REVIEW REQUIRED"


@dataclass(frozen=True)
class InvoiceClaimFacts:
    invoice_number: str | None
    document_sha256: str
    invoice_date: date | None
    registration: str | None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    supplier_name: str | None = None
    repair_descriptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExistingInvoiceIdentity:
    invoice_number: str | None
    document_sha256: str
    supplier_name: str | None = None


@dataclass(frozen=True)
class ConsistencyFinding:
    code: str
    status: str
    severity: str
    message: str


@dataclass(frozen=True)
class LiabilityGate:
    state: LiabilityState
    human_confirmed: bool
    analysis_allowed: bool
    challenge_issue_allowed: bool
    reason: str


def _normalise_registration(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _normalise_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def liability_gate(state: LiabilityState | str, *, human_confirmed: bool) -> LiabilityGate:
    state = LiabilityState(state)
    if not human_confirmed:
        return LiabilityGate(
            state=state,
            human_confirmed=False,
            analysis_allowed=True,
            challenge_issue_allowed=False,
            reason="A claims handler must confirm liability before any challenge is issued.",
        )
    allowed = state in {LiabilityState.ADMITTED, LiabilityState.SPLIT_LIABILITY}
    if allowed:
        reason = "Human-confirmed liability allows the quantum challenge to be issued."
    elif state == LiabilityState.DENIED:
        reason = (
            "Liability is denied; retain the quantum analysis but do not issue a payable challenge."
        )
    else:
        reason = "Liability remains unresolved; the analysis may continue as a draft only."
    return LiabilityGate(
        state=state,
        human_confirmed=True,
        analysis_allowed=True,
        challenge_issue_allowed=allowed,
        reason=reason,
    )


def claim_invoice_consistency(
    *,
    accident_date: date | None,
    claimant_registration: str | None,
    claimant_vehicle_make: str | None,
    claimant_vehicle_model: str | None,
    damage_description: str | None,
    invoice: InvoiceClaimFacts,
    existing_invoices: Iterable[ExistingInvoiceIdentity] = (),
) -> tuple[ConsistencyFinding, ...]:
    """Deterministic contradictions only; damage causation remains human review."""

    findings: list[ConsistencyFinding] = []
    expected_vrm = _normalise_registration(claimant_registration)
    found_vrm = _normalise_registration(invoice.registration)
    if expected_vrm and found_vrm:
        matches = expected_vrm == found_vrm
        findings.append(
            ConsistencyFinding(
                code="CLAIM_INVOICE_VRM_MATCH" if matches else "CLAIM_INVOICE_VRM_MISMATCH",
                status="PASS" if matches else "FAIL",
                severity="INFO" if matches else "HIGH",
                message=(
                    "Invoice vehicle registration matches the claimant vehicle."
                    if matches
                    else "Invoice registration does not match the claimant vehicle."
                ),
            )
        )
    else:
        findings.append(
            ConsistencyFinding(
                code="CLAIM_INVOICE_VRM_MISSING",
                status="REVIEW",
                severity="AMBER",
                message="A registration is missing from the claim or invoice.",
            )
        )

    if accident_date and invoice.invoice_date:
        valid_date = invoice.invoice_date >= accident_date
        findings.append(
            ConsistencyFinding(
                code="INVOICE_AFTER_ACCIDENT" if valid_date else "INVOICE_BEFORE_ACCIDENT",
                status="PASS" if valid_date else "FAIL",
                severity="INFO" if valid_date else "HIGH",
                message=(
                    "Invoice date is on or after the accident date."
                    if valid_date
                    else "Invoice predates the recorded accident."
                ),
            )
        )

    expected_vehicle = _normalise_name(
        f"{claimant_vehicle_make or ''}{claimant_vehicle_model or ''}"
    )
    found_vehicle = _normalise_name(f"{invoice.vehicle_make or ''}{invoice.vehicle_model or ''}")
    if expected_vehicle and found_vehicle:
        vehicle_match = expected_vehicle in found_vehicle or found_vehicle in expected_vehicle
        findings.append(
            ConsistencyFinding(
                code="CLAIM_INVOICE_VEHICLE_MATCH"
                if vehicle_match
                else "CLAIM_INVOICE_VEHICLE_MISMATCH",
                status="PASS" if vehicle_match else "REVIEW",
                severity="INFO" if vehicle_match else "AMBER",
                message=(
                    "Invoice vehicle description is consistent with the claim."
                    if vehicle_match
                    else "Vehicle make/model needs handler review."
                ),
            )
        )

    duplicate_hash = False
    duplicate_identity = False
    for existing in existing_invoices:
        duplicate_hash = duplicate_hash or existing.document_sha256 == invoice.document_sha256
        duplicate_identity = duplicate_identity or bool(
            invoice.invoice_number
            and existing.invoice_number == invoice.invoice_number
            and _normalise_name(existing.supplier_name) == _normalise_name(invoice.supplier_name)
        )
    duplicate = duplicate_hash or duplicate_identity
    findings.append(
        ConsistencyFinding(
            code="DUPLICATE_INVOICE" if duplicate else "NO_DUPLICATE_INVOICE_FOUND",
            status="FAIL" if duplicate else "PASS",
            severity="HIGH" if duplicate else "INFO",
            message=(
                "The same document hash or supplier/invoice identity already exists."
                if duplicate
                else "No exact duplicate invoice was found."
            ),
        )
    )

    if damage_description and invoice.repair_descriptions:
        findings.append(
            ConsistencyFinding(
                code="DAMAGE_REPAIR_CAUSATION_REVIEW",
                status="REVIEW",
                severity="AMBER",
                message=(
                    "Repair descriptions and stated damage are available. A handler must confirm "
                    "causation; the invoice alone cannot establish accident-related damage."
                ),
            )
        )
    return tuple(findings)
