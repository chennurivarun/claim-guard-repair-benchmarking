from datetime import date

from app.domain.liability import (
    ExistingInvoiceIdentity,
    InvoiceClaimFacts,
    LiabilityState,
    claim_invoice_consistency,
    liability_gate,
)


def test_only_human_confirmed_admitted_or_split_can_issue_challenge() -> None:
    assert liability_gate(LiabilityState.ADMITTED, human_confirmed=True).challenge_issue_allowed
    assert liability_gate(
        LiabilityState.SPLIT_LIABILITY, human_confirmed=True
    ).challenge_issue_allowed
    assert not liability_gate(LiabilityState.PENDING, human_confirmed=True).challenge_issue_allowed
    assert not liability_gate(
        LiabilityState.ADMITTED, human_confirmed=False
    ).challenge_issue_allowed
    assert liability_gate(LiabilityState.DENIED, human_confirmed=True).analysis_allowed


def test_invoice_checks_consistency_but_does_not_decide_fault() -> None:
    invoice = InvoiceClaimFacts(
        invoice_number="91283",
        document_sha256="abc",
        invoice_date=date(2025, 11, 26),
        registration="PX64 XCU",
        vehicle_make="Vauxhall",
        vehicle_model="Adam Jam",
        supplier_name="St Albans Car Clinic",
        repair_descriptions=("Front discs", "Front brake pads"),
    )
    findings = claim_invoice_consistency(
        accident_date=date(2025, 11, 1),
        claimant_registration="PX64 XCU",
        claimant_vehicle_make="Vauxhall",
        claimant_vehicle_model="Adam Jam",
        damage_description="Front impact",
        invoice=invoice,
    )
    assert {finding.code for finding in findings} >= {
        "CLAIM_INVOICE_VRM_MATCH",
        "INVOICE_AFTER_ACCIDENT",
        "CLAIM_INVOICE_VEHICLE_MATCH",
        "DAMAGE_REPAIR_CAUSATION_REVIEW",
    }
    assert all("liability" not in finding.code.lower() for finding in findings)


def test_duplicate_hash_is_blocking_finding() -> None:
    invoice = InvoiceClaimFacts(
        invoice_number="90538",
        document_sha256="same-hash",
        invoice_date=date(2025, 9, 26),
        registration="KU65 EOK",
    )
    findings = claim_invoice_consistency(
        accident_date=date(2025, 9, 1),
        claimant_registration="KU65 EOK",
        claimant_vehicle_make=None,
        claimant_vehicle_model=None,
        damage_description=None,
        invoice=invoice,
        existing_invoices=(ExistingInvoiceIdentity("different", "same-hash", "Other Garage"),),
    )
    duplicate = next(finding for finding in findings if finding.code == "DUPLICATE_INVOICE")
    assert duplicate.status == "FAIL"
