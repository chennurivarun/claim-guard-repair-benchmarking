"""Wipe every per-case document artefact while keeping the reference library.

The client asked for a clean slate: *"in database we shud remove all old files.
We wont be using any old files."*  Dropping the SQLite file would also drop the
ontology, the external price library and the seed benchmark history -- months of
governed reference data the tool cannot work without.  So this is a *data*
reset, not a schema reset: it deletes the case-scoped tables row by row, in
child-before-parent order, and leaves the schema and the reference banks intact.

Seven things a naive ``DELETE FROM cases`` gets wrong, all handled below:

* ``audit_events`` is append-only, guarded by SQLite triggers *and* ORM events.
  ``audit_events.case_id`` is ``ON DELETE SET NULL`` -- an UPDATE -- so even
  deleting a case aborts against the update trigger.  The triggers are dropped
  and recreated around the wipe; the ORM guard is bypassed by using Core
  ``DELETE`` statements, which never emit per-instance mapper events.
* Deleting the chain is also the one supported way to destroy the tamper
  evidence it exists to provide, so the whole table is written to a JSON Lines
  export -- with a SHA-256 over the file -- *before* the first row goes, and
  the report carries the path.
* ``vehicles.case_id`` is ``SET NULL``, so deleting a case orphans its vehicle
  rows instead of removing them.  They are deleted explicitly.
* ``cases.current_processing_run_id`` -> ``processing_runs`` is a circular
  ``use_alter`` FK.  It is nulled before the runs are deleted.
* Half of the "reference library" is not reference data at all.
  ``stage_unmatched_line_proposal`` mints an ``OntologyItem`` +
  ``OntologyVersion`` + ``ExternalEvidence`` + ``PriceObservation`` out of every
  unmatched priced invoice line, and ``trigger_manual_research`` does the same
  for reviewer research.  Keeping those while deleting ``external_evidence``
  leaves benchmarks that are derived from the very documents the client asked
  to be erased *and* can no longer be audited.  They are purged with the rest of
  the derived history, and whatever survives is counted separately in the
  report so "kept" can never quietly mean "kept case data".
* No database cascade touches the filesystem, so the stored PDFs, the rendered
  page images and the generated exports have to be removed too -- including
  case directories whose row has already gone.  That deletion is *irreversible*,
  so this module does not do it: :func:`reset_case_data` only resolves and
  reports the roots, and the caller sweeps them via
  :func:`clear_reset_paths` **after** its ``commit()`` has succeeded.  Doing it
  the other way round means a failed commit leaves every row in place and every
  PDF behind them gone.
* The delete root is env-controlled (``CLAIM_GUARD_STORAGE_DIR``) and
  unvalidated, so ``''`` makes it relative to the process cwd and ``/`` aims it
  at ``/cases``.  :func:`_resolve_delete_root` refuses anything that is not an
  absolute path at least two segments below the filesystem root, and the
  storage root additionally has to be the exact tree ``store_pdf`` writes to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Table, delete, func, not_, or_, select, update
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
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

# The audit export must land somewhere the sweep does not then delete, so it is
# a *sibling* of the exports tree rather than a directory inside it.
AUDIT_EXPORT_DIRNAME = "audit-exports"

# A delete root has to be absolute and at least this many segments below the
# filesystem root.  ``CLAIM_GUARD_STORAGE_DIR=/`` would otherwise resolve to
# ``/cases`` and ``CLAIM_GUARD_STORAGE_DIR=''`` to ``./cases``, relative to
# whichever cwd the process happens to have.
MINIMUM_ROOT_DEPTH = 2

# Every marker that says "this reference row was minted from a case document".
#
# ``auto_unmatched_invoice_line``  -- research_workflow.stage_unmatched_line_proposal
# ``reviewer_initiated_manual_research`` -- research_workflow.trigger_manual_research
#
# Both write an OntologyVersion labelled ``research-<task id>``, an OntologyItem
# whose ``price_source`` is the marker, an ExternalEvidence row and a
# PriceObservation whose ``source_type`` is the marker and whose ``evidence_id``
# points at that evidence.  ``research_tasks`` is case-scoped and is wiped, so
# every one of these rows is case-derived by construction.
CASE_DERIVED_SOURCE_TYPES: tuple[str, ...] = (
    "auto_unmatched_invoice_line",
    "reviewer_initiated_manual_research",
)

# ``mapping_review._learn_approved_synonym`` writes this when a handler approves
# an invoice-line mapping, with ``source_reference='invoice_line:<id>'``.  Zero
# rows today, real the first time a handler approves a mapping.
CASE_DERIVED_SYNONYM_SOURCE_TYPES: tuple[str, ...] = ("handler_approved_invoice_mapping",)

# ``research_workflow._new_ontology_version`` labels every version it mints
# ``research-<research task id>``.
RESEARCH_VERSION_LABEL_PREFIX = "research-"

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

# Reference / benchmark / configuration data.  Counted after the wipe so the
# report can prove the library survived -- and, for the four tables that can
# hold case-derived rows, counted *twice*, so "kept" can never quietly mean
# "kept case data".  See ``_count_case_derived``.
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
class SweepFailure:
    path: str
    error: str


@dataclass
class ResetReport:
    """Everything the job touched, in a shape that prints and serialises."""

    deleted_rows: dict[str, int] = field(default_factory=dict)
    kept_rows: dict[str, int] = field(default_factory=dict)
    # The subset of ``kept_rows`` that was minted from case documents rather
    # than imported as reference data.  Zero after a full reset; non-zero only
    # when the operator asked to keep the derived data.
    kept_case_derived: dict[str, int] = field(default_factory=dict)
    # Resolved, absolute, reported *before* anything is deleted, and kept in
    # the response afterwards so the operator can always see which tree this
    # run addressed -- the silent-no-op failure mode is a wrong root, not a
    # missing one.
    resolved_roots: list[str] = field(default_factory=list)
    # The same list, consumed by ``clear_reset_paths`` as it sweeps.
    pending_roots: list[str] = field(default_factory=list)
    removed_paths: list[RemovedTree] = field(default_factory=list)
    sweep_failures: list[SweepFailure] = field(default_factory=list)
    audit_export: dict[str, Any] | None = None
    new_case: dict[str, Any] | None = None
    derived_history_purged: bool = True

    @property
    def total_rows_deleted(self) -> int:
        return sum(self.deleted_rows.values())

    @property
    def total_bytes_removed(self) -> int:
        return sum(tree.bytes for tree in self.removed_paths)

    @property
    def kept_reference_rows(self) -> dict[str, int]:
        return {
            label: count - self.kept_case_derived.get(label, 0)
            for label, count in self.kept_rows.items()
        }

    @property
    def total_case_derived_kept(self) -> int:
        return sum(self.kept_case_derived.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "deleted_rows": dict(self.deleted_rows),
            "total_rows_deleted": self.total_rows_deleted,
            "kept_rows": dict(self.kept_rows),
            "kept_rows_reference": self.kept_reference_rows,
            "kept_rows_case_derived": dict(self.kept_case_derived),
            "total_case_derived_kept": self.total_case_derived_kept,
            "derived_history_purged": self.derived_history_purged,
            "audit_export": self.audit_export,
            "resolved_roots": list(self.resolved_roots),
            "pending_roots": list(self.pending_roots),
            "removed_paths": [
                {"path": tree.path, "files": tree.files, "bytes": tree.bytes}
                for tree in self.removed_paths
            ],
            "sweep_failures": [
                {"path": failure.path, "error": failure.error}
                for failure in self.sweep_failures
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
    # The snapshot rows go with their observations.  Not because the bank would
    # otherwise stay empty -- ``ensure_synthetic_in_house_data`` short-circuits
    # only on a matching ``dataset_version``, and after this reset the invoices
    # and vehicles it derives that signature from are gone, so it will normally
    # differ and the bank will regenerate.  The reason is simpler: a
    # ``source_imports`` row is a snapshot *of* the deleted observations, and
    # leaving it behind leaves a provenance record pointing at nothing.
    # (A signature collision would additionally make the short-circuit fire and
    # strand the bank empty, which is why this is the defensive choice.)
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


def _case_derived_observation_ids(session: Session) -> list[str]:
    """Ids of every price observation that was minted from a case document.

    Must be evaluated *before* ``external_evidence`` is wiped:
    ``price_observations.evidence_id`` is ``ON DELETE SET NULL``, so the wipe
    erases the very marker that proves an observation can no longer be audited.
    """

    return list(
        session.scalars(
            select(PriceObservation.id).where(
                or_(
                    PriceObservation.source_type.in_(CASE_DERIVED_SOURCE_TYPES),
                    PriceObservation.source_url_or_ref.like("invoice-line:%"),
                    PriceObservation.evidence_id.in_(select(ExternalEvidence.id)),
                    PriceObservation.created_in_version_id.in_(
                        select(OntologyVersion.id).where(
                            OntologyVersion.label.like(f"{RESEARCH_VERSION_LABEL_PREFIX}%")
                        )
                    ),
                )
            )
        ).all()
    )


def _purge_case_derived_reference(
    session: Session, observation_ids: list[str]
) -> dict[str, int]:
    """Delete the "reference library" rows that are really case data.

    Runs *after* ``WIPE_ORDER`` so ``ontology_mappings`` (``SET NULL``),
    ``research_items`` (``SET NULL``) and ``mapping_runs``
    (``ontology_versions`` ``RESTRICT``) are already gone and cannot block the
    deletes or be silently re-pointed.

    Order is forced by the constraints: observations first, then synonyms, then
    items (``ontology_items.created_in_version_id`` is ``RESTRICT``), then the
    versions -- and a version only goes if nothing at all still points at it.

    An item is kept if it still has a surviving observation that was *not*
    case-derived: that means it also carries governed reference pricing and
    deleting it would take real library data with it.
    """

    counts: dict[str, int] = {}

    if observation_ids:
        counts["price_observations (case-derived)"] = int(
            session.execute(
                delete(PriceObservation.__table__).where(
                    PriceObservation.id.in_(observation_ids)
                ),
                execution_options={"synchronize_session": False},
            ).rowcount
            or 0
        )
    else:
        counts["price_observations (case-derived)"] = 0

    counts["ontology_synonyms (case-derived)"] = int(
        session.execute(
            delete(OntologySynonym.__table__).where(
                or_(
                    OntologySynonym.source_type.in_(CASE_DERIVED_SYNONYM_SOURCE_TYPES),
                    OntologySynonym.source_reference.like("invoice_line:%"),
                )
            ),
            execution_options={"synchronize_session": False},
        ).rowcount
        or 0
    )

    research_versions = select(OntologyVersion.id).where(
        OntologyVersion.label.like(f"{RESEARCH_VERSION_LABEL_PREFIX}%")
    )
    derived_item = or_(
        OntologyItem.price_source.in_(CASE_DERIVED_SOURCE_TYPES),
        OntologyItem.source_url_or_ref.like("invoice-line:%"),
        OntologyItem.created_in_version_id.in_(research_versions),
    )
    # ``ontology_items.superseded_by_id`` is self-referential (``SET NULL``), so
    # clear it first rather than relying on delete order.
    session.execute(
        update(OntologyItem.__table__)
        .where(
            OntologyItem.superseded_by_id.in_(
                select(OntologyItem.id).where(derived_item)
            )
        )
        .values(superseded_by_id=None),
        execution_options={"synchronize_session": False},
    )
    surviving_observation = (
        select(PriceObservation.id)
        .where(PriceObservation.ontology_item_id == OntologyItem.id)
        .exists()
    )
    counts["ontology_items (case-derived)"] = int(
        session.execute(
            delete(OntologyItem.__table__).where(
                derived_item, not_(surviving_observation)
            ),
            execution_options={"synchronize_session": False},
        ).rowcount
        or 0
    )

    version = OntologyVersion.__table__.c.id
    unreferenced = not_(
        or_(
            select(OntologyItem.id)
            .where(
                or_(
                    OntologyItem.created_in_version_id == version,
                    OntologyItem.retired_in_version_id == version,
                )
            )
            .exists(),
            select(OntologySynonym.id)
            .where(OntologySynonym.created_in_version_id == version)
            .exists(),
            select(PriceObservation.id)
            .where(PriceObservation.created_in_version_id == version)
            .exists(),
            select(OntologyVersion.id)
            .where(OntologyVersion.parent_id == version)
            .exists(),
        )
    )
    counts["ontology_versions (case-derived)"] = int(
        session.execute(
            delete(OntologyVersion.__table__).where(
                OntologyVersion.label.like(f"{RESEARCH_VERSION_LABEL_PREFIX}%"),
                unreferenced,
            ),
            execution_options={"synchronize_session": False},
        ).rowcount
        or 0
    )
    return counts


def _synthetic_provider_name() -> str:
    from app.services.in_house_repair_data import PROVIDER_NAME

    return PROVIDER_NAME


def _count_case_derived(session: Session) -> dict[str, int]:
    """How many *kept* rows are still case-derived, per table.

    The whole point of splitting the report: ``price_observations: 123`` reads
    as reassurance right up until you learn 58 of them were minted from the
    invoice the client asked to be erased.
    """

    def _count(model: Any, condition: Any) -> int:
        return int(session.scalar(select(func.count(model.id)).where(condition)) or 0)

    research_versions = select(OntologyVersion.id).where(
        OntologyVersion.label.like(f"{RESEARCH_VERSION_LABEL_PREFIX}%")
    )
    return {
        "price_observations": _count(
            PriceObservation,
            or_(
                PriceObservation.source_type.in_(CASE_DERIVED_SOURCE_TYPES),
                PriceObservation.source_url_or_ref.like("invoice-line:%"),
                PriceObservation.created_in_version_id.in_(research_versions),
            ),
        ),
        "ontology_items": _count(
            OntologyItem,
            or_(
                OntologyItem.price_source.in_(CASE_DERIVED_SOURCE_TYPES),
                OntologyItem.source_url_or_ref.like("invoice-line:%"),
                OntologyItem.created_in_version_id.in_(research_versions),
            ),
        ),
        "ontology_versions": _count(
            OntologyVersion,
            OntologyVersion.label.like(f"{RESEARCH_VERSION_LABEL_PREFIX}%"),
        ),
        "ontology_synonyms": _count(
            OntologySynonym,
            or_(
                OntologySynonym.source_type.in_(CASE_DERIVED_SYNONYM_SOURCE_TYPES),
                OntologySynonym.source_reference.like("invoice_line:%"),
            ),
        ),
        # Same three populations ``_purge_derived_history`` removes, so the
        # count is honest when the operator opts out of purging them.
        "historical_observations": _count(
            HistoricalObservation,
            or_(
                HistoricalObservation.source_import_id.in_(
                    select(SourceImport.id).where(
                        SourceImport.provider_id.in_(
                            select(SourceProvider.id).where(
                                SourceProvider.name == _synthetic_provider_name()
                            )
                        )
                    )
                ),
                HistoricalObservation.source_record_id.like("finalised:%"),
                HistoricalObservation.source_invoice_id.is_not(None),
                HistoricalObservation.source_line_item_id.is_not(None),
            ),
        ),
    }


def _export_audit_events(session: Session, destination: Path) -> dict[str, Any]:
    """Write the whole append-only chain to JSON Lines before it is destroyed.

    The triggers plus ``previous_event_hash`` exist to make the log tamper
    evident; wiping the table restarts the chain from ``NULL`` and is therefore
    a supported way to erase that evidence.  It is only defensible if the log
    leaves first.  The file is a straight row dump -- every column, in chain
    order -- plus a SHA-256 the report quotes, so the export can be shown to be
    the one this run took.

    Written before the deletes and therefore before the caller's ``commit()``:
    if that commit then fails, the export describes rows that still exist,
    which is harmless.  Losing it would not be.
    """

    table = AuditEvent.__table__
    rows = session.execute(
        select(table).order_by(table.c.created_at, table.c.id)
    ).mappings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with destination.open("w", encoding="utf-8") as handle:
        for row in rows:
            line = json.dumps(dict(row), default=str, sort_keys=True) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return {
        "path": str(destination),
        "events": count,
        "sha256": digest.hexdigest(),
    }


def _resolve_delete_root(
    raw: Path | str,
    *,
    label: str,
    must_match: Path | str | None = None,
    must_match_label: str = "",
) -> Path:
    """Resolve a root this job is allowed to ``rmtree`` inside, or refuse.

    ``storage_dir`` is a plain unvalidated ``Path`` field fed by
    ``CLAIM_GUARD_STORAGE_DIR``.  Three verified ways that goes wrong::

        CLAIM_GUARD_STORAGE_DIR=''        -> PosixPath('.')       -> ./cases
        CLAIM_GUARD_STORAGE_DIR='storage' -> PosixPath('storage') -> ./storage/cases
        CLAIM_GUARD_STORAGE_DIR='/'       -> PosixPath('/')       -> /cases

    The first two are worse than they look: the API server runs with cwd
    ``backend/`` and ``claimguard-reset`` is typically run from the repo root,
    so the two address different trees -- the CLI deletes nothing, prints
    ``Files removed: 0``, exits 0, and the operator believes the files are gone.
    The third is an ``rm -rf`` of an unrelated directory as the API user.

    So: absolute, resolved, and at least ``MINIMUM_ROOT_DEPTH`` segments below
    the filesystem root.  For the storage tree, additionally the *same* resolved
    path the writer uses, because ``document_processing`` binds its ``settings``
    at import while this module used to call ``get_settings()`` fresh -- deleting
    a tree nobody writes to is exactly the silent no-op above.
    """

    text = str(raw)
    if not text or text == ".":
        raise ValueError(
            f"Refusing to reset: the {label} is empty, so it would resolve "
            f"relative to the current working directory ({Path.cwd()}). "
            "Set it to an absolute path."
        )
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        raise ValueError(
            f"Refusing to reset: the {label} {text!r} is a relative path, so it "
            f"resolves against the current working directory ({Path.cwd()}) and "
            "means a different tree for the API server and the CLI. "
            "Set it to an absolute path."
        )
    root = candidate.resolve()
    depth = len(root.parts) - 1  # parts[0] is the anchor
    if depth < MINIMUM_ROOT_DEPTH:
        raise ValueError(
            f"Refusing to reset: the {label} resolves to {root}, which is at or "
            f"near the filesystem root. A delete root must be at least "
            f"{MINIMUM_ROOT_DEPTH} segments below it."
        )
    if must_match is not None:
        writer = Path(str(must_match)).expanduser()
        if not writer.is_absolute() or writer.resolve() != root:
            raise ValueError(
                f"Refusing to reset: the {label} resolves to {root} but "
                f"{must_match_label} writes to {writer}. Deleting a tree the "
                "writer does not use removes nothing and reports success. "
                "Point both at the same absolute path."
            )
    return root


def _writer_storage_dir() -> Path:
    """The storage root ``store_pdf`` actually writes into.

    Imported lazily: ``document_processing`` pulls in the whole extraction
    stack, and this module is also a standalone console script.
    """

    from app.services import document_processing

    return Path(document_processing.settings.storage_dir)


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


def _clear_directory(root: Path) -> tuple[list[RemovedTree], list[SweepFailure]]:
    """Delete every child of ``root``, keeping ``root`` itself.

    Case directories are removed by what is on disk, not by what the database
    lists, so directories whose row disappeared in an earlier partial cleanup
    are collected too.

    One unreadable directory must not abort the sweep.  The database half is
    already committed by the time this runs, so raising here would leave rows
    deleted and an arbitrary prefix of the tree still on disk, with nothing in
    the response saying which.  Failures are collected per path and reported.
    """

    removed: list[RemovedTree] = []
    failures: list[SweepFailure] = []
    if not root.is_dir():
        return removed, failures
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        return removed, [SweepFailure(path=str(root), error=str(exc))]
    for child in children:
        try:
            if child.is_dir() and not child.is_symlink():
                files, total = _measure_tree(child)
                shutil.rmtree(child)
            else:
                files, total = 1, child.stat().st_size if child.is_file() else 0
                child.unlink()
        except OSError as exc:
            failures.append(SweepFailure(path=str(child), error=str(exc)))
            continue
        removed.append(RemovedTree(path=str(child), files=files, bytes=total))
    return removed, failures


def clear_reset_paths(report: ResetReport) -> ResetReport:
    """Sweep the roots :func:`reset_case_data` resolved.  **Call after commit.**

    Separated from the database work because it is the only irreversible half.
    ``reset_case_data`` resolves and reports the roots; the caller commits; only
    then does anything leave the disk.  The other order -- which this module
    used to have, while its docstring claimed the opposite -- means a commit
    that fails after the sweep (SQLite ``database is locked`` past the busy
    timeout, a full disk, a killed process) leaves every case, document and
    invoice row in place and every PDF, page image and export behind them gone.

    Idempotent: the roots are cleared from the report as they are swept.
    """

    for raw in list(report.pending_roots):
        removed, failures = _clear_directory(Path(raw))
        report.removed_paths.extend(removed)
        report.sweep_failures.extend(failures)
    report.pending_roots = []
    return report


def create_empty_case(session: Session, case_reference: str, created_by: str) -> dict[str, Any]:
    """Create the one case the client works in next.

    Shared with ``claimguard-setup`` so a fresh install and a post-reset
    database open on a case in exactly the same state.

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
    audit_export_dir: Path | None = None,
    actor: str = "claimguard.reset",
) -> ResetReport:
    """Delete every per-case artefact, keep the reference library, start fresh.

    The caller owns the transaction boundary.  Nothing here commits, and
    nothing here deletes a file, so a failure anywhere leaves the database
    exactly as it was *and* leaves every stored PDF, page image and export in
    place.  The roots to sweep come back in ``report.pending_roots``; the
    caller passes the report to :func:`clear_reset_paths` once its ``commit()``
    has returned.

    Both roots are resolved and validated up front -- before a single row goes
    -- so a misconfigured ``CLAIM_GUARD_STORAGE_DIR`` refuses the whole job
    rather than deleting the database half and silently sweeping nothing.
    """

    exports_root = _resolve_delete_root(
        exports_dir if exports_dir is not None else DEFAULT_EXPORTS_DIR,
        label="exports directory",
    )
    writer_root = _writer_storage_dir()
    storage_root = _resolve_delete_root(
        storage_dir if storage_dir is not None else writer_root,
        label="storage directory (CLAIM_GUARD_STORAGE_DIR)",
        must_match=writer_root,
        must_match_label="document_processing.store_pdf",
    )
    audit_export_root = (
        Path(audit_export_dir)
        if audit_export_dir is not None
        else exports_root.parent / AUDIT_EXPORT_DIRNAME
    )

    report = ResetReport(derived_history_purged=purge_derived_history)
    report.resolved_roots = [str(storage_root / "cases"), str(exports_root)]
    report.pending_roots = list(report.resolved_roots)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report.audit_export = _export_audit_events(
        session, audit_export_root / f"audit-events-{stamp}.jsonl"
    )

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
            # Snapshot the evidence-backed observations while
            # ``external_evidence`` still exists; the wipe nulls ``evidence_id``.
            derived_observation_ids = _case_derived_observation_ids(session)
        # The circular ``use_alter`` FK: null the pointer before the runs it
        # points at are deleted, so the cascade never has to update a case row
        # that is itself on the way out.
        session.execute(
            update(Case.__table__).values(current_processing_run_id=None),
            execution_options={"synchronize_session": False},
        )
        for label, target in WIPE_ORDER:
            report.deleted_rows[label] = _delete(session, target)
        if purge_derived_history:
            report.deleted_rows.update(
                _purge_case_derived_reference(session, derived_observation_ids)
            )
    finally:
        _set_audit_triggers(session, enabled=True)

    if new_case_reference:
        report.new_case = create_empty_case(session, new_case_reference, actor)
    # Always recorded, with or without a replacement case: it is the first row
    # of the new chain and the only thing in the database that says the old one
    # was deleted on purpose.  ``claimguard-bootstrap`` reads it to refuse
    # rebuilding the demo case a reset deliberately removed.
    session.add(
        AuditEvent(
            case_id=report.new_case["id"] if report.new_case else None,
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
                "audit_export": report.audit_export,
                "roots_to_clear": list(report.pending_roots),
            },
        )
    )
    session.flush()

    for label, model in KEPT_TABLES:
        report.kept_rows[label] = int(session.scalar(select(func.count(model.id))) or 0)
    report.kept_case_derived = {
        label: count
        for label, count in _count_case_derived(session).items()
        if label in report.kept_rows
    }

    # No filesystem work here on purpose -- see ``clear_reset_paths``.
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
    reference = report.kept_reference_rows
    lines.append("")
    lines.append("Rows kept")
    lines.append(f"  {'table'.ljust(kept_width)}  reference  case-derived")
    lines.append(f"  {'-' * kept_width}  ---------  ------------")
    for label in report.kept_rows:
        derived = report.kept_case_derived.get(label, 0)
        lines.append(
            f"  {label.ljust(kept_width)}  {reference[label]:>9d}  {derived:>12d}"
        )
    if report.total_case_derived_kept:
        lines.append(
            f"  WARNING: {report.total_case_derived_kept} kept rows were derived "
            "from case documents and can still price a comparison."
        )

    lines.append("")
    if report.audit_export:
        lines.append(
            f"Audit log exported before deletion: {report.audit_export['path']} "
            f"({report.audit_export['events']} events, "
            f"sha256={report.audit_export['sha256']})"
        )

    lines.append("")
    lines.append("Delete roots (resolved before anything was removed):")
    for raw in report.resolved_roots:
        lines.append(f"  {raw}")
    if report.pending_roots:
        lines.append("Nothing removed yet - the caller has not swept them.")
    else:
        lines.append(
            f"Files removed: {sum(tree.files for tree in report.removed_paths)} "
            f"in {len(report.removed_paths)} directories "
            f"({report.total_bytes_removed} bytes)"
        )
        for tree in report.removed_paths:
            lines.append(f"  {tree.path}  ({tree.files} files, {tree.bytes} bytes)")
    for failure in report.sweep_failures:
        lines.append(f"  COULD NOT REMOVE {failure.path}: {failure.error}")

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

    # Only now, with the database half durable, is anything removed from disk.
    # The resolved absolute roots are announced first, on stderr so ``--json``
    # stays machine-readable: an operator who is about to lose files should see
    # exactly which tree they are.
    for raw in report.pending_roots:
        print(f"Clearing {raw}", file=sys.stderr)
    clear_reset_paths(report)
    if report.sweep_failures:
        for failure in report.sweep_failures:
            print(f"Could not remove {failure.path}: {failure.error}", file=sys.stderr)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        print(render_report(report))
    # Non-zero when the database is wiped but files are still on disk: that is
    # not "done", and a wrapper script must be able to see the difference.
    return 1 if report.sweep_failures else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
