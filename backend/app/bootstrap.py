"""Idempotently build the supplied ClaimGuard pilot case from bundled sample data.

The idempotence check is "does a case with this reference exist", which is the
right question until a clean-slate reset makes the answer *deliberately* no.
Running ``claimguard-bootstrap`` after ``claimguard-reset`` would then rebuild
the demo case, re-ingest the demo invoice and re-mint the auto-staged ontology
rows derived from it -- precisely what the client asked to be rid of.

So the guard is on the reset, not on the reference: renaming the demo case
would resurrect exactly the same data under a different label. If the audit log
records a ``CASE_DATA_RESET``, this refuses to recreate the pilot case and says
why; ``--force`` is the deliberate override, and ``--case-reference`` exists for
building the demo somewhere it will not collide.

That leaves a gap this module also fills. The demo case and the reference
library arrived through the same command, so a new user following the setup
instructions had no way to get the ontology, historical and external price
banks -- which every comparison needs -- without also getting the demo claim,
its fabricated claim context, its two demo vehicles and a processed demo
invoice. ``setup_reference_library`` is that missing path, and it is a *second
console script* rather than a ``--seeds-only`` flag on this one: the command
printed in the setup instructions should not be one forgotten flag away from
rebuilding the demo corpus. ``claimguard-bootstrap`` is unchanged and still
builds the demo for the acceptance walkthrough that needs it.
"""

from __future__ import annotations

import argparse
import json
import sys
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
    HistoricalObservation,
    Invoice,
    LiabilityAssessment,
    OntologyItem,
    PriceComparison,
    PriceObservation,
)
from app.reset import DEFAULT_NEW_CASE_REFERENCE, create_empty_case
from app.services.case_result import build_claim_workspace
from app.services.comparison_workflow import run_case_comparison
from app.services.document_processing import process_document, store_pdf
from app.services.external_benchmark_import_service import import_external_uk_benchmarks
from app.services.seed_import_service import import_seed_workbooks

SAMPLE_DATA = Path(__file__).resolve().parents[2] / "sample-data"
DEFAULT_CASE_REFERENCE = "CG-2026-0048"
# Back-compat alias for anything still importing the constant.
CASE_REFERENCE = DEFAULT_CASE_REFERENCE

# Written by ``app.reset``. Its presence means an operator deliberately
# deleted every case, so rebuilding the demo case is almost never wanted.
RESET_EVENT_TYPE = "CASE_DATA_RESET"

# The clean-install case. Deliberately the same reference ``claimguard-reset``
# leaves behind, so a fresh install and a reset database open on the same claim.
DEFAULT_EMPTY_CASE_REFERENCE = DEFAULT_NEW_CASE_REFERENCE
SETUP_ACTOR = "claimguard.setup"
INVOICE_PATH = SAMPLE_DATA / "1643919_doc_16439191.pdf.pdf"
ONTOLOGY_PATH = SAMPLE_DATA / "ontology_seed.xlsx"
HISTORY_PATH = SAMPLE_DATA / "historical_claims_seed.xlsx"
EXTERNAL_BENCHMARK_PATH = SAMPLE_DATA / "uk_external_benchmarks.csv"


def _create_case(session, case_reference: str = DEFAULT_CASE_REFERENCE) -> Case:
    case = Case(
        case_reference=case_reference,
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
                "case_reference": case_reference,
                "liability_status": LiabilityStatus.ADMITTED.value,
            },
            event_payload_json={"invoice_may_decide_fault": False},
        )
    )
    session.commit()
    return case


def bootstrap_pilot(
    case_reference: str = DEFAULT_CASE_REFERENCE, *, force: bool = False
) -> dict[str, object]:
    for path in (ONTOLOGY_PATH, HISTORY_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    initialize_database()
    with SessionLocal() as session:
        seed_result = import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        external_result = import_external_uk_benchmarks(session, EXTERNAL_BENCHMARK_PATH)
        session.commit()

        case = session.scalar(select(Case).where(Case.case_reference == case_reference))
        if case is None:
            _refuse_after_reset(session, case_reference, force=force)
            case = _create_case(session, case_reference)

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
                "case_reference": case_reference,
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

        workspace = build_claim_workspace(session, case_reference)
        document_count = session.scalar(
            select(func.count(Document.id)).where(Document.case_id == case.id)
        )
        return {
            "case_reference": case_reference,
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


def _refuse_after_reset(session, case_reference: str, *, force: bool) -> None:
    """Do not undo a clean-slate reset by accident.

    The reset's whole purpose is that the demo corpus is gone. Recreating the
    pilot case would re-ingest the demo invoice and, through
    ``stage_unmatched_line_proposal``, re-mint the ontology items and price
    observations derived from it.
    """

    if force:
        return
    resets = session.scalar(
        select(func.count(AuditEvent.id)).where(AuditEvent.event_type == RESET_EVENT_TYPE)
    )
    if resets:
        raise RuntimeError(
            f"Refusing to recreate {case_reference}: the audit log records "
            f"{resets} clean-slate reset(s), so this case was deliberately "
            "deleted. Re-run with --force if you really want the demo corpus "
            "back, or use --case-reference to build it elsewhere."
        )


def _reference_bank_totals(session) -> dict[str, int]:
    """What ``POST /claims/{ref}/compare`` and ``GET /readiness`` actually count."""

    return {
        "ontology_items": session.scalar(select(func.count(OntologyItem.id))) or 0,
        "historical_observations": (
            session.scalar(select(func.count(HistoricalObservation.id))) or 0
        ),
        "price_observations": session.scalar(select(func.count(PriceObservation.id))) or 0,
    }


def setup_reference_library(
    case_reference: str | None = DEFAULT_EMPTY_CASE_REFERENCE,
) -> dict[str, object]:
    """Import the reference library and, optionally, open one empty case.

    This is the documented install path. It imports exactly what
    ``bootstrap_pilot`` imports -- the ontology and historical seed workbooks
    and the external UK benchmark file -- and stops there. No demo case, no
    ``ClaimContext`` full of invented parties, no demo vehicles, no liability
    assessment, and no demo invoice ingested.

    ``case_reference`` is the one case the user will work in. It is built by
    ``app.reset.create_empty_case``, so a fresh install lands in the same state
    a clean-slate reset leaves behind: ``CLAIM_REVIEW`` with the liability gate
    awaiting a human. Uploads and extracts work immediately; only comparison
    and finalisation wait on the liability decision. The one row it does write
    beyond ``cases`` is that case's ``claim_contexts`` row -- the gate lives
    there, so an empty case cannot exist without it. Pass ``None`` for a pure
    seeds-only import with no case at all.

    Re-running is safe: the seed import is content-addressed and an existing
    case is left exactly as it is, documents and all.
    """

    for path in (ONTOLOGY_PATH, HISTORY_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    initialize_database()
    with SessionLocal() as session:
        seed_result = import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        external_result = import_external_uk_benchmarks(session, EXTERNAL_BENCHMARK_PATH)
        session.commit()

        case_payload: dict[str, object] | None = None
        if case_reference:
            existing = session.scalar(
                select(Case).where(Case.case_reference == case_reference)
            )
            if existing is None:
                case_payload = dict(
                    create_empty_case(session, case_reference, SETUP_ACTOR)
                )
                session.commit()
                case_payload["created"] = True
            else:
                case_payload = {
                    "id": existing.id,
                    "case_reference": existing.case_reference,
                    "status": existing.status.value,
                    "created": False,
                }

        return {
            "mode": "seeds_only" if case_reference is None else "seeds_and_empty_case",
            "case": case_payload,
            "seed_import": {
                "ontology_items_created": seed_result.ontology_items_created,
                "price_observations_created": seed_result.price_observations_created,
                "historical_observations_created": (
                    seed_result.historical_observations_created
                ),
                "acceptance_gold_excluded": seed_result.acceptance_gold_excluded,
            },
            "external_benchmark_import": {
                "observations_created": external_result.observations_created,
                "rows_skipped": external_result.rows_skipped,
            },
            "reference_banks": _reference_bank_totals(session),
        }


def render_setup_report(result: dict[str, object]) -> str:
    banks = result["reference_banks"]
    lines = [
        "Reference library ready:",
        f"  ontology items           {banks['ontology_items']:>6}",
        f"  historical observations  {banks['historical_observations']:>6}",
        f"  price observations       {banks['price_observations']:>6}",
    ]
    case = result["case"]
    if case is None:
        lines.append("")
        lines.append("No case created. Create one in the app before uploading documents.")
    else:
        verb = "Created empty case" if case["created"] else "Existing case kept"
        lines.append("")
        lines.append(f"{verb} {case['case_reference']} -- no documents, upload form ready.")
    lines.append("No demo case and no demo invoice were created.")
    return "\n".join(lines)


def setup_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claimguard-setup",
        description=(
            "Prepare a clean ClaimGuard install: import the reference library and "
            "open one empty case. Creates no demo case and ingests no demo invoice."
        ),
    )
    parser.add_argument(
        "--case-reference",
        default=DEFAULT_EMPTY_CASE_REFERENCE,
        help=f"Reference for the empty case (default: {DEFAULT_EMPTY_CASE_REFERENCE}).",
    )
    parser.add_argument(
        "--no-case",
        action="store_true",
        help="Import the reference library only; create no case at all.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the machine-readable report."
    )
    args = parser.parse_args(argv)
    result = setup_reference_library(None if args.no_case else args.case_reference)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_setup_report(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claimguard-bootstrap",
        description="Build the bundled ClaimGuard demo case from sample data.",
    )
    parser.add_argument(
        "--case-reference",
        default=DEFAULT_CASE_REFERENCE,
        help=f"Reference for the demo case (default: {DEFAULT_CASE_REFERENCE}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate the demo case even though a clean-slate reset has run.",
    )
    args = parser.parse_args(argv)
    try:
        result = bootstrap_pilot(args.case_reference, force=args.force)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
