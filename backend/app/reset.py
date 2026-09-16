"""Wipe every per-case document artefact while keeping the reference library.

The client asked for a clean slate: *"in database we shud remove all old files.
We wont be using any old files."*  Dropping the SQLite file would also drop the
ontology, the external price library and the seed benchmark history -- months of
governed reference data the tool cannot work without.  So this is a *data*
reset, not a schema reset: it deletes the case-scoped tables row by row, in
child-before-parent order, and leaves the schema and the reference banks intact.

Four things a naive ``DELETE FROM cases`` gets wrong, all handled below:

* ``audit_events`` is append-only, guarded by SQLite triggers *and* ORM events.
  ``audit_events.case_id`` is ``ON DELETE SET NULL`` -- an UPDATE -- so even
  deleting a case aborts against the update trigger.  The triggers are dropped
  and recreated around the wipe; the ORM guard is bypassed by using Core
  ``DELETE`` statements, which never emit per-instance mapper events.
* ``vehicles.case_id`` is ``SET NULL``, so deleting a case orphans its vehicle
  rows instead of removing them.  They are deleted explicitly.
* ``cases.current_processing_run_id`` -> ``processing_runs`` is a circular
  ``use_alter`` FK.  It is nulled before the runs are deleted.
* No database cascade touches the filesystem, so the stored PDFs, the rendered
  page images and the generated exports are removed here -- including case
  directories whose row has already gone.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.database import SessionLocal
from app.enums import AuditActorType, CaseStatus, LiabilityGateStatus
from app.init_db import AUDIT_TRIGGER_NAMES, AUDIT_TRIGGER_STATEMENTS, initialize_database
from app.models import (
    AssessmentInvoiceVariance,
    AssessmentOperation,
    AuditEvent,
    Case,
    ChallengeResult,
    ClaimConsistencyFinding,
    ClaimContext,
    ClaimParty,
    ClaimVehicle,
    ComparisonComparable,
    ConfigVersion,
    Document,
    DocumentPage,
    EngineerAssessment,
    ExternalEvidence,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    LiabilityAssessment,
    LiabilityEvidence,
    MappingRun,
    MathFinding,
    OntologyItem,
    OntologyMapping,
    OntologySynonym,
    OntologyVersion,
    PriceComparison,
    PriceObservation,
    ProcessingRun,
    RegulatoryRule,
    ResearchItem,
    ResearchTask,
    ReviewDecision,
    ReviewTask,
    Settlement,
    SourceImport,
    SourceProvider,
    Vehicle,
    VehicleApplicability,
    VehicleCategoryLookup,
    invoice_page_links,
)

CONFIRMATION_PHRASE = "DELETE ALL CASE DATA"

# Deliberately not ``CG-2026-0048``: that is the demo case the client wants gone.
DEFAULT_NEW_CASE_REFERENCE = "CG-CLIENT-001"

DEFAULT_EXPORTS_DIR = BACKEND_DIR / "data" / "exports"

# Child before parent.  Deleting ``cases`` first would work -- the cascades are
# correct -- but every child count would then report zero, and the point of this
# job is to be able to prove what it removed.
WIPE_ORDER: tuple[tuple[str, Any], ...] = (
    ("comparison_comparables", ComparisonComparable),
    ("settlements", Settlement),
    ("review_decisions", ReviewDecision),
    ("review_tasks", ReviewTask),
    ("research_items", ResearchItem),
    ("external_evidence", ExternalEvidence),
    ("research_tasks", ResearchTask),
    ("challenge_results", ChallengeResult),
    ("price_comparisons", PriceComparison),
    ("ontology_mappings", OntologyMapping),
    ("mapping_runs", MappingRun),
    ("assessment_invoice_variances", AssessmentInvoiceVariance),
    ("assessment_operations", AssessmentOperation),
    ("engineer_assessments", EngineerAssessment),
    ("math_findings", MathFinding),
    ("invoice_page_links", invoice_page_links),
    ("invoice_line_items", InvoiceLineItem),
    ("invoices", Invoice),
    ("vehicles", Vehicle),
    ("claim_consistency_findings", ClaimConsistencyFinding),
    ("liability_evidence", LiabilityEvidence),
    ("liability_assessments", LiabilityAssessment),
    ("claim_vehicles", ClaimVehicle),
    ("claim_parties", ClaimParty),
    ("claim_contexts", ClaimContext),
    ("document_pages", DocumentPage),
    ("documents", Document),
    ("audit_events", AuditEvent),
    ("processing_runs", ProcessingRun),
    ("cases", Case),
)

# Reference / benchmark / configuration data.  Counted before and after so the
# report can prove the library survived.
KEPT_TABLES: tuple[tuple[str, Any], ...] = (
    ("ontology_items", OntologyItem),
    ("ontology_synonyms", OntologySynonym),
    ("ontology_versions", OntologyVersion),
    ("vehicle_applicability", VehicleApplicability),
    ("price_observations", PriceObservation),
    ("vehicle_category_lookup", VehicleCategoryLookup),
    ("config_versions", ConfigVersion),
    ("regulatory_rules", RegulatoryRule),
    ("source_providers", SourceProvider),
    ("source_imports", SourceImport),
    ("historical_observations", HistoricalObservation),
)


@dataclass
class RemovedTree:
    path: str
    files: int
    bytes: int


@dataclass
class ResetReport:
    """Everything the job touched, in a shape that prints and serialises."""

    deleted_rows: dict[str, int] = field(default_factory=dict)
    kept_rows: dict[str, int] = field(default_factory=dict)
    removed_paths: list[RemovedTree] = field(default_factory=list)
    new_case: dict[str, Any] | None = None
    derived_history_purged: bool = True

    @property
    def total_rows_deleted(self) -> int:
        return sum(self.deleted_rows.values())

    @property
    def total_bytes_removed(self) -> int:
        return sum(tree.bytes for tree in self.removed_paths)

    def as_dict(self) -> dict[str, Any]:
        return {
            "deleted_rows": dict(self.deleted_rows),
            "total_rows_deleted": self.total_rows_deleted,
            "kept_rows": dict(self.kept_rows),
            "derived_history_purged": self.derived_history_purged,
            "removed_paths": [
                {"path": tree.path, "files": tree.files, "bytes": tree.bytes}
                for tree in self.removed_paths
            ],
            "total_bytes_removed": self.total_bytes_removed,
            "new_case": self.new_case,
        }


def _is_sqlite(session: Session) -> bool:
    bind = session.get_bind()
    return bind.dialect.name == "sqlite"


def _set_audit_triggers(session: Session, *, enabled: bool) -> None:
    """Drop or recreate the append-only triggers on the session's connection.

    They have to move with this transaction rather than through
    ``initialize_database``: a maintenance run may target a database other than
    the process-wide engine, and the wipe must not be visible to other writers
    with the guards already gone.
    """

    if not _is_sqlite(session):
        return
    connection = session.connection()
    if enabled:
        for statement in AUDIT_TRIGGER_STATEMENTS:
            connection.exec_driver_sql(statement)
        return
    for name in AUDIT_TRIGGER_NAMES:
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")


def _delete(session: Session, target: Any) -> int:
    """Core ``DELETE`` for one table; returns the rows it removed itself.

    Core statements are used throughout because ``AuditEvent`` installs
    ``before_update`` / ``before_delete`` mapper guards that raise on any
    per-instance mutation.  A bulk statement never emits those events, which is
    what makes an authorised wipe possible without weakening the guard for
    ordinary application code.
    """

    table: Table = target if isinstance(target, Table) else target.__table__
    result = session.execute(
        delete(table), execution_options={"synchronize_session": False}
    )
    return int(result.rowcount or 0)


def _purge_derived_history(session: Session) -> dict[str, int]:
    """Remove the history rows that were derived from the old demo documents.

    Three populations, none of which is governed reference data:

    * the synthetic in-house bank, regenerated on the next
      ``POST /claims/{ref}/compare`` by ``ensure_synthetic_in_house_data``;
    * rows written back by finalising a case (``source_record_id`` is
      ``finalised:<case>:<line>``);
    * anything still pointing at an invoice or an invoice line.

    Order matters: ``historical_observations.source_invoice_id`` is ``ON DELETE
    SET NULL``, so deleting the invoices first would erase the very marker that
    identifies these rows, leaving them behind as untraceable benchmark noise.
    """

    from app.services.in_house_repair_data import PROVIDER_NAME

    synthetic_import_ids = select(SourceImport.id).where(
        SourceImport.provider_id.in_(
            select(SourceProvider.id).where(SourceProvider.name == PROVIDER_NAME)
        )
    )
    observations = session.execute(
        delete(HistoricalObservation.__table__).where(
            or_(
                HistoricalObservation.source_import_id.in_(synthetic_import_ids),
                HistoricalObservation.source_record_id.like("finalised:%"),
                HistoricalObservation.source_invoice_id.is_not(None),
                HistoricalObservation.source_line_item_id.is_not(None),
            )
        ),
        execution_options={"synchronize_session": False},
    )
    # The snapshot rows have to go with their observations.  ``ensure_synthetic
    # _in_house_data`` short-circuits on a matching ``dataset_version`` and
    # returns without recreating any rows, so a surviving import row could
    # leave the in-house bank permanently empty.
    imports = session.execute(
        delete(SourceImport.__table__).where(
            SourceImport.provider_id.in_(
                select(SourceProvider.id).where(SourceProvider.name == PROVIDER_NAME)
            )
        ),
        execution_options={"synchronize_session": False},
    )
    return {
        "historical_observations": int(observations.rowcount or 0),
        "source_imports": int(imports.rowcount or 0),
    }


def _measure_tree(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() or entry.is_symlink():
            files += 1
            try:
                total += entry.stat().st_size
            except OSError:  # pragma: no cover - racing with another writer
                continue
    return files, total


def _clear_directory(root: Path) -> list[RemovedTree]:
    """Delete every child of ``root``, keeping ``root`` itself.

    Case directories are removed by what is on disk, not by what the database
    lists, so directories whose row disappeared in an earlier partial cleanup
    are collected too.
    """

    removed: list[RemovedTree] = []
    if not root.is_dir():
        return removed
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.is_symlink():
            files, total = _measure_tree(child)
            shutil.rmtree(child)
        else:
            files, total = 1, child.stat().st_size if child.is_file() else 0
            child.unlink()
        removed.append(RemovedTree(path=str(child), files=files, bytes=total))
    return removed


def _create_empty_case(session: Session, case_reference: str, created_by: str) -> dict[str, Any]:
    """Create the one case the client works in next.

    ``CLAIM_REVIEW`` with an unconfirmed liability gate is exactly what
    ``POST /claims`` produces, so the new case behaves like a hand-created one.
    Neither ``POST /claims/{ref}/documents`` nor ``GET /claims/{ref}/extracts``
    consults the liability gate, so uploads and extracts work immediately;
    only comparison and finalisation wait for a human liability decision.
    """

    existing = session.scalar(select(Case).where(Case.case_reference == case_reference))
    if existing is not None:
        raise ValueError(f"A case already exists with reference {case_reference!r}.")
    case = Case(
        case_reference=case_reference,
        status=CaseStatus.CLAIM_REVIEW,
        created_by=created_by,
        notes="Empty case created by the clean-slate reset; ready for client documents.",
    )
    session.add(case)
    session.flush()
    context = ClaimContext(
        case_id=case.id,
        claim_number=case_reference,
        liability_gate_status=LiabilityGateStatus.AWAITING_HUMAN_REVIEW,
        human_confirmed=False,
    )
    session.add(context)
    session.flush()
    return {
        "id": case.id,
        "case_reference": case.case_reference,
        "status": case.status.value,
        "claim_number": context.claim_number,
        "liability_gate_status": context.liability_gate_status.value,
        "human_confirmed": context.human_confirmed,
        "documents": 0,
        "invoices": 0,
        "upload_ready": True,
    }


def reset_case_data(
    session: Session,
    *,
    new_case_reference: str | None = DEFAULT_NEW_CASE_REFERENCE,
    purge_derived_history: bool = True,
    storage_dir: Path | None = None,
    exports_dir: Path | None = None,
    actor: str = "claimguard.reset",
) -> ResetReport:
    """Delete every per-case artefact, keep the reference library, start fresh.

    The caller owns the transaction boundary; nothing here commits, so a
    failure anywhere leaves the database exactly as it was.
    """

    settings = get_settings()
    storage_root = Path(storage_dir) if storage_dir else Path(settings.storage_dir)
    exports_root = Path(exports_dir) if exports_dir else DEFAULT_EXPORTS_DIR

    report = ResetReport(derived_history_purged=purge_derived_history)

    _set_audit_triggers(session, enabled=False)
    try:
        if purge_derived_history:
            derived = _purge_derived_history(session)
            report.deleted_rows["historical_observations (derived)"] = derived[
                "historical_observations"
            ]
            report.deleted_rows["source_imports (synthetic in-house)"] = derived[
                "source_imports"
            ]
        # The circular ``use_alter`` FK: null the pointer before the runs it
        # points at are deleted, so the cascade never has to update a case row
        # that is itself on the way out.
        session.execute(
            update(Case.__table__).values(current_processing_run_id=None),
            execution_options={"synchronize_session": False},
        )
        for label, target in WIPE_ORDER:
            report.deleted_rows[label] = _delete(session, target)
    finally:
        _set_audit_triggers(session, enabled=True)

    if new_case_reference:
        report.new_case = _create_empty_case(session, new_case_reference, actor)
        session.add(
            AuditEvent(
                case_id=report.new_case["id"],
                actor_type=AuditActorType.SYSTEM,
                actor_id=actor,
                event_type="CASE_DATA_RESET",
                entity_type="database",
                entity_id=None,
                before_json=None,
                after_json={"new_case_reference": new_case_reference},
                event_payload_json={
                    "rows_deleted": report.total_rows_deleted,
                    "derived_history_purged": purge_derived_history,
                },
            )
        )
    session.flush()

    for label, model in KEPT_TABLES:
        report.kept_rows[label] = int(session.scalar(select(func.count(model.id))) or 0)

    # Filesystem last: the database work is still rollback-able until the
    # caller commits, and deleting files is not.
    report.removed_paths.extend(_clear_directory(storage_root / "cases"))
    report.removed_paths.extend(_clear_directory(exports_root))
    return report


def render_report(report: ResetReport) -> str:
    """A plain-text table of what was deleted, kept and removed from disk."""

    lines: list[str] = []
    width = max((len(label) for label in report.deleted_rows), default=10)
    lines.append("Rows deleted")
    lines.append(f"  {'table'.ljust(width)}  rows")
    lines.append(f"  {'-' * width}  ----")
    for label, count in report.deleted_rows.items():
        lines.append(f"  {label.ljust(width)}  {count:>4d}")
    lines.append(f"  {'TOTAL'.ljust(width)}  {report.total_rows_deleted:>4d}")

    kept_width = max((len(label) for label in report.kept_rows), default=10)
    lines.append("")
    lines.append("Reference data kept")
    for label, count in report.kept_rows.items():
        lines.append(f"  {label.ljust(kept_width)}  {count:>6d}")

    lines.append("")
    lines.append(
        f"Files removed: {sum(tree.files for tree in report.removed_paths)} "
        f"in {len(report.removed_paths)} directories "
        f"({report.total_bytes_removed} bytes)"
    )
    for tree in report.removed_paths:
        lines.append(f"  {tree.path}  ({tree.files} files, {tree.bytes} bytes)")

    lines.append("")
    if report.new_case:
        lines.append(
            f"New empty case: {report.new_case['case_reference']} "
            f"(status={report.new_case['status']}, "
            f"liability_gate={report.new_case['liability_gate_status']}) "
            "- ready for document upload."
        )
    else:
        lines.append("No new case created.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claimguard-reset",
        description=(
            "Delete every per-case document artefact and start one empty case. "
            "Reference data (ontology, price library, seed benchmark history, "
            "vehicle lookup, configuration) is kept."
        ),
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f'Must be exactly "{CONFIRMATION_PHRASE}". Nothing runs without it.',
    )
    parser.add_argument(
        "--case-reference",
        default=DEFAULT_NEW_CASE_REFERENCE,
        help=f"Reference for the new empty case (default: {DEFAULT_NEW_CASE_REFERENCE}).",
    )
    parser.add_argument(
        "--no-new-case",
        action="store_true",
        help="Wipe without creating a replacement case.",
    )
    parser.add_argument(
        "--keep-derived-history",
        action="store_true",
        help=(
            "Keep the synthetic in-house bank and the finalised-case write-backs. "
            "By default they are deleted because they are derived from the old files."
        ),
    )
    parser.add_argument("--actor", default="claimguard.reset", help="Audit actor id.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    args = parser.parse_args(argv)

    if args.confirm != CONFIRMATION_PHRASE:
        parser.error(
            "Refusing to delete case data. Re-run with "
            f'--confirm "{CONFIRMATION_PHRASE}".'
        )

    initialize_database()
    with SessionLocal() as session:
        try:
            report = reset_case_data(
                session,
                new_case_reference=None if args.no_new_case else args.case_reference,
                purge_derived_history=not args.keep_derived_history,
                actor=args.actor,
            )
        except Exception:
            session.rollback()
            raise
        session.commit()

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
