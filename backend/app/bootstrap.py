"""Idempotently build the supplied ClaimGuard pilot case from bundled sample data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.database import SessionLocal
from app.enums import (
    AuditActorType,
    CaseStatus,
    ClaimPartyRole,
    ClaimVehicleRole,
    DocumentRole,
    LiabilityGateStatus,
    LiabilityStatus,
    ReviewStatus,
)
from app.init_db import initialize_database
from app.models import (
    AuditEvent,
    Case,
    ClaimContext,
    ClaimParty,
    ClaimVehicle,
    Document,
    Invoice,
    LiabilityAssessment,
    PriceComparison,
)
from app.services.case_result import build_claim_workspace
from app.services.comparison_workflow import run_case_comparison
from app.services.document_processing import process_document, store_pdf
from app.services.external_benchmark_import_service import import_external_uk_benchmarks
from app.services.seed_import_service import import_seed_workbooks

SAMPLE_DATA = Path(__file__).resolve().parents[2] / "sample-data"
CASE_REFERENCE = "CG-2026-0048"
INVOICE_PATH = SAMPLE_DATA / "1643919_doc_16439191.pdf.pdf"
ONTOLOGY_PATH = SAMPLE_DATA / "ontology_seed.xlsx"
HISTORY_PATH = SAMPLE_DATA / "historical_claims_seed.xlsx"
EXTERNAL_BENCHMARK_PATH = SAMPLE_DATA / "uk_external_benchmarks.csv"


def _create_case(session) -> Case:
    case = Case(
        case_reference=CASE_REFERENCE,
        status=CaseStatus.LIABILITY_REVIEW,
        created_by="pilot.handler",
        notes="Pilot case built from the supplied invoice 91283 and seed workbooks.",
    )
    session.add(case)
    session.flush()
    confirmed_at = datetime.now(UTC)
    context = ClaimContext(
        case_id=case.id,
        claim_number="CLM-CG-0048",
        paying_insurer_name="Northstar Mutual",
        claiming_insurer_name="Wessex Assurance",
        third_party_name="Amelia Reed",
        paying_policy_number="NSM-8841-2047",
        accident_at=datetime(2025, 11, 19, 10, 30, tzinfo=UTC),
        accident_location="A1081, St Albans, Hertfordshire",
        accident_description=(
            "Insured vehicle entered the roundabout and contacted the third-party "
            "vehicle on its front nearside."
        ),
        damage_description="Front nearside wheel, steering and braking inspection requested.",
        liability_gate_status=LiabilityGateStatus.CONFIRMED,
        human_confirmed=True,
        human_confirmed_by="pilot.handler",
        human_confirmed_at=confirmed_at,
    )
    session.add(context)
    session.flush()
    session.add_all(
        [
            ClaimParty(
                claim_context_id=context.id,
                party_role=ClaimPartyRole.PAYING_INSURER,
                insurer_name="Northstar Mutual",
                policy_number="NSM-8841-2047",
                review_status=ReviewStatus.APPROVED,
            ),
            ClaimParty(
                claim_context_id=context.id,
                party_role=ClaimPartyRole.CLAIMING_INSURER,
                insurer_name="Wessex Assurance",
                review_status=ReviewStatus.APPROVED,
            ),
            ClaimParty(
                claim_context_id=context.id,
                party_role=ClaimPartyRole.INSURED_DRIVER,
                name="Martin Cole",
                review_status=ReviewStatus.APPROVED,
            ),
            ClaimParty(
                claim_context_id=context.id,
                party_role=ClaimPartyRole.CLAIMANT_DRIVER,
                name="Amelia Reed",
                review_status=ReviewStatus.APPROVED,
            ),
        ]
    )
    session.add_all(
        [
            ClaimVehicle(
                claim_context_id=context.id,
                vehicle_role=ClaimVehicleRole.INSURED_VEHICLE,
                registration="EK18 NXR",
                make="Ford",
                model="Fiesta",
                variant="Zetec 1.0",
                manufacture_year=2018,
                review_status=ReviewStatus.APPROVED,
            ),
            ClaimVehicle(
                claim_context_id=context.id,
                vehicle_role=ClaimVehicleRole.THIRD_PARTY_VEHICLE,
                registration="PX64 XCU",
                make="Vauxhall",
                model="Adam",
                variant="Jam 1.2",
                manufacture_year=2014,
                damage_description="Front nearside impact area.",
                review_status=ReviewStatus.APPROVED,
            ),
        ]
    )
    assessment = LiabilityAssessment(
        claim_context_id=context.id,
        human_status=LiabilityStatus.ADMITTED,
        human_rationale="Liability admitted by the pilot claims handler.",
        human_confirmed=True,
        confirmed_by="pilot.handler",
        confirmed_at=confirmed_at,
        effective_status=LiabilityStatus.ADMITTED,
        evidence_snapshot_json=[],
    )
    session.add(assessment)
    session.flush()
    session.add(
        AuditEvent(
            case_id=case.id,
            actor_type=AuditActorType.USER,
            actor_id="pilot.handler",
            event_type="PILOT_CASE_CREATED_AND_LIABILITY_CONFIRMED",
            entity_type="case",
            entity_id=case.id,
            before_json=None,
            after_json={
                "case_reference": CASE_REFERENCE,
                "liability_status": LiabilityStatus.ADMITTED.value,
            },
            event_payload_json={"invoice_may_decide_fault": False},
        )
    )
    session.commit()
    return case


def bootstrap_pilot() -> dict[str, object]:
    for path in (ONTOLOGY_PATH, HISTORY_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    initialize_database()
    with SessionLocal() as session:
        seed_result = import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        external_result = import_external_uk_benchmarks(session, EXTERNAL_BENCHMARK_PATH)
        session.commit()

        case = session.scalar(select(Case).where(Case.case_reference == CASE_REFERENCE))
        if case is None:
            case = _create_case(session)

        invoice_count = session.scalar(
            select(func.count(Invoice.id)).where(Invoice.case_id == case.id)
        )
        if not invoice_count and INVOICE_PATH.is_file():
            document = store_pdf(
                session,
                case=case,
                filename=INVOICE_PATH.name,
                content=INVOICE_PATH.read_bytes(),
                role=DocumentRole.CURRENT,
            )
            session.commit()
            process_document(session, document)
            session.commit()

        if not invoice_count and not INVOICE_PATH.is_file():
            document_count = session.scalar(
                select(func.count(Document.id)).where(Document.case_id == case.id)
            )
            return {
                "case_reference": CASE_REFERENCE,
                "seed_import": {
                    "ontology_items_created": seed_result.ontology_items_created,
                    "price_observations_created": seed_result.price_observations_created,
                    "historical_observations_created": (
                        seed_result.historical_observations_created
                    ),
                    "acceptance_gold_excluded": seed_result.acceptance_gold_excluded,
                },
                "documents": document_count,
                "external_benchmark_import": {
                    "observations_created": external_result.observations_created,
                    "rows_skipped": external_result.rows_skipped,
                    "runtime_rule_enabled": False,
                },
                "comparison": {
                    "status": "waiting_for_invoice_upload",
                    "message": (
                        "Reference banks are ready. Upload an invoice in the application "
                        "to start extraction and comparison."
                    ),
                },
                "workspace_summary": None,
            }

        case = session.scalar(select(Case).where(Case.id == case.id))
        comparison_count = session.scalar(
            select(func.count(PriceComparison.id)).where(
                PriceComparison.processing_run_id == case.current_processing_run_id
            )
        )
        if not comparison_count:
            comparison_result = run_case_comparison(session, case)
            session.commit()
        else:
            comparison_result = {
                "status": "already_compared",
                "line_count": comparison_count,
            }

        workspace = build_claim_workspace(session, CASE_REFERENCE)
        document_count = session.scalar(
            select(func.count(Document.id)).where(Document.case_id == case.id)
        )
        return {
            "case_reference": CASE_REFERENCE,
            "seed_import": {
                "ontology_items_created": seed_result.ontology_items_created,
                "price_observations_created": seed_result.price_observations_created,
                "historical_observations_created": seed_result.historical_observations_created,
                "acceptance_gold_excluded": seed_result.acceptance_gold_excluded,
            },
            "documents": document_count,
            "external_benchmark_import": {
                "observations_created": external_result.observations_created,
                "rows_skipped": external_result.rows_skipped,
                "runtime_rule_enabled": False,
            },
            "comparison": comparison_result,
            "workspace_summary": workspace["summary"],
        }


def main() -> None:
    print(json.dumps(bootstrap_pilot(), indent=2, default=str))


if __name__ == "__main__":
    main()
