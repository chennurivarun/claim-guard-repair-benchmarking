"""The clean-slate reset: wipe case data, keep the reference library.

Every assertion here is about a trap that a naive ``DELETE FROM cases`` walks
into -- the append-only audit triggers, the ``SET NULL`` vehicle orphans, the
circular processing-run FK, and the files no cascade ever touches.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.bootstrap as bootstrap
import app.reset as reset_module
from app.config import get_settings
from app.database import get_db
from app.enums import (
    ApprovalStatus,
    AuditActorType,
    CaseStatus,
    DocumentRole,
    LineItemKind,
    OntologyVersionStatus,
    PriceObservationKind,
    PriceVatBasis,
    RunStatus,
    RunType,
    SourceProviderType,
    UploadStatus,
)
from app.init_db import initialize_database
from app.main import app
from app.models import (
    AuditEvent,
    Case,
    ClaimContext,
    ConfigVersion,
    Document,
    DocumentPage,
    ExternalEvidence,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    OntologyItem,
    OntologySynonym,
    OntologyVersion,
    PriceObservation,
    ProcessingRun,
    RegulatoryRule,
    ResearchItem,
    ResearchTask,
    SourceImport,
    SourceProvider,
    Vehicle,
    VehicleCategoryLookup,
)
from app.reset import CONFIRMATION_PHRASE, DEFAULT_NEW_CASE_REFERENCE, reset_case_data
from app.services import document_processing
from app.services.in_house_repair_data import PROVIDER_NAME as SYNTHETIC_PROVIDER_NAME
from app.services.research_workflow import AUTO_STAGED_SOURCE_TYPE

DEMO_CASE_REFERENCE = "CG-2026-0048"


@pytest.fixture
def engine(tmp_path: Path):
    database = create_engine(
        f"sqlite:///{tmp_path / 'reset.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(database, "connect")
    def pragmas(connection, record):  # noqa: ARG001 - SQLAlchemy event signature
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(database, seed_defaults=True)
    yield database
    database.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@pytest.fixture
def storage_root(tmp_path: Path, monkeypatch) -> Path:
    """Point *both* views of the settings at a throwaway storage root.

    ``document_processing`` binds ``settings`` at import time while
    ``app.reset`` calls ``get_settings()`` each run, and another test in this
    suite clears that cache -- after which the two are different objects and
    patching only the imported one would aim a delete at the developer's real
    ``backend/data/storage``.
    """

    root = tmp_path / "storage"
    live = get_settings()
    monkeypatch.setattr(live, "storage_dir", root)
    monkeypatch.setattr(document_processing, "settings", live)
    return root


@pytest.fixture
def exports_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "exports"
    monkeypatch.setattr(reset_module, "DEFAULT_EXPORTS_DIR", root)
    return root


@pytest.fixture
def audit_export_root(tmp_path: Path) -> Path:
    return tmp_path / "audit-exports"


@pytest.fixture
def run_reset(
    session_factory, storage_root: Path, exports_root: Path, audit_export_root: Path
):
    """Call the reset with explicit roots, so no test can depend on settings.

    Mirrors the caller contract exactly: the database half commits first, and
    only then does ``clear_reset_paths`` touch the disk.
    """

    def _run(**kwargs) -> reset_module.ResetReport:
        kwargs.setdefault("storage_dir", storage_root)
        kwargs.setdefault("exports_dir", exports_root)
        kwargs.setdefault("audit_export_dir", audit_export_root)
        with session_factory() as session:
            report = reset_case_data(session, **kwargs)
            session.commit()
        return reset_module.clear_reset_paths(report)

    return _run


def _seed_reference_library(session: Session) -> None:
    """Rows that must survive: ontology, price library and seed history."""

    version = session.scalar(
        select(OntologyVersion).where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
    )
    item = OntologyItem(
        canonical_code="PANEL-FRONT-WING",
        canonical_name="Front wing panel",
        item_type=LineItemKind.PART,
        category="body_panel",
        unit="each",
        created_by="pytest",
        created_in_version_id=version.id,
    )
    session.add(item)
    session.flush()
    session.add(
        PriceObservation(
            ontology_item_id=item.id,
            price_net="120.00",
            vat_basis=PriceVatBasis.NET,
            unit="each",
            source_type="seed_workbook",
            effective_from=date(2025, 1, 1),
            observation_kind=PriceObservationKind.REFERENCE,
        )
    )
    workbook_provider = SourceProvider(
        name="ClaimGuard seed workbook",
        provider_type=SourceProviderType.EXCEL,
        adapter_name="excel_seed",
    )
    session.add(workbook_provider)
    session.flush()
    workbook_import = SourceImport(provider_id=workbook_provider.id, dataset_version="seed-v1")
    session.add(workbook_import)
    session.flush()
    session.add(
        HistoricalObservation(
            source_import_id=workbook_import.id,
            source_record_id="workbook:row-1",
            raw_description="Front wing panel replacement",
        )
    )


def _seed_derived_history(session: Session, invoice: Invoice, line: InvoiceLineItem) -> None:
    """Rows derived from the old demo files, which must NOT survive."""

    synthetic_provider = SourceProvider(
        name=SYNTHETIC_PROVIDER_NAME,
        provider_type=SourceProviderType.INTERNAL,
        adapter_name="synthetic_in_house",
    )
    session.add(synthetic_provider)
    session.flush()
    synthetic_import = SourceImport(
        provider_id=synthetic_provider.id,
        dataset_version="synthetic-in-house-1-abc",
    )
    session.add(synthetic_import)
    session.flush()
    session.add_all(
        [
            HistoricalObservation(
                source_import_id=synthetic_import.id,
                source_record_id="synthetic:row-1",
                raw_description="Synthetic in-house benchmark row",
            ),
            HistoricalObservation(
                source_invoice_id=invoice.id,
                source_line_item_id=line.id,
                source_record_id=f"finalised:{invoice.case_id}:{line.id}",
                raw_description="Write-back from the finalised demo case",
            ),
        ]
    )


def _seed_demo_case(session: Session, storage_root: Path) -> str:
    case = Case(
        case_reference=DEMO_CASE_REFERENCE,
        status=CaseStatus.COMPARISON_REVIEW,
        created_by="pilot.handler",
    )
    session.add(case)
    session.flush()
    session.add(ClaimContext(case_id=case.id, claim_number="CLM-CG-0048"))
    run = ProcessingRun(
        case_id=case.id,
        run_type=RunType.FULL,
        application_version="0.1.0",
        configuration_hash="deadbeef",
        benchmark_policy_version="claimguard-v1.4",
        status=RunStatus.SUCCEEDED,
    )
    session.add(run)
    session.flush()
    # The circular ``use_alter`` FK that a plain cascade delete trips over.
    case.current_processing_run_id = run.id

    stored = storage_root / "cases" / case.id / "abc123def456"
    stored.mkdir(parents=True, exist_ok=True)
    (stored / "invoice.pdf").write_bytes(b"%PDF-1.4 demo")
    (stored / "pages").mkdir(exist_ok=True)
    (stored / "pages" / "page-1.png").write_bytes(b"png-bytes")

    document = Document(
        case_id=case.id,
        document_role=DocumentRole.CURRENT,
        original_filename="invoice-91283.pdf",
        storage_path=str(stored / "invoice.pdf"),
        sha256="abc123def456",
        file_size=13,
        upload_status=UploadStatus.READY,
    )
    session.add(document)
    session.flush()
    page = DocumentPage(document_id=document.id, page_number=1)
    session.add(page)
    invoice = Invoice(
        case_id=case.id,
        document_id=document.id,
        document_group_id="group-1",
        invoice_number="91283",
    )
    session.add(invoice)
    session.flush()
    line = InvoiceLineItem(invoice_id=invoice.id, sequence_no=1, raw_description="Front wing")
    session.add(line)
    session.flush()
    # ``vehicles.case_id`` is SET NULL: deleting the case orphans this row.
    session.add(Vehicle(case_id=case.id, registration="EK18 NXR", make="Ford", model="Fiesta"))
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=run.id,
            actor_type=AuditActorType.USER,
            actor_id="pilot.handler",
            event_type="PILOT_CASE_CREATED",
            entity_type="case",
            entity_id=case.id,
        )
    )
    _seed_derived_history(session, invoice, line)
    session.flush()
    return case.id


@pytest.fixture
def populated(session_factory, storage_root: Path, exports_root: Path) -> dict[str, object]:
    with session_factory() as session:
        _seed_reference_library(session)
        case_id = _seed_demo_case(session, storage_root)
        session.commit()

    # One orphan storage directory (there are six on disk for one case in the
    # developer's database) and one generated export tree.
    orphan = storage_root / "cases" / "00000000-orphaned-case"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "stale.pdf").write_bytes(b"%PDF-1.4 stale")
    export_dir = exports_root / DEMO_CASE_REFERENCE
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / f"{DEMO_CASE_REFERENCE}-claimguard.xlsx").write_bytes(b"xlsx")
    return {"case_id": case_id, "orphan": orphan, "export_dir": export_dir}


def test_reset_wipes_case_data_and_keeps_the_reference_library(
    session_factory, populated, run_reset
) -> None:
    report = run_reset()

    assert report.deleted_rows["cases"] == 1
    assert report.deleted_rows["documents"] == 1
    assert report.deleted_rows["document_pages"] == 1
    assert report.deleted_rows["invoices"] == 1
    assert report.deleted_rows["invoice_line_items"] == 1
    assert report.deleted_rows["processing_runs"] == 1
    assert report.deleted_rows["audit_events"] == 1
    # vehicles.case_id is SET NULL, so this row survives a cascade delete.
    assert report.deleted_rows["vehicles"] == 1

    with session_factory() as session:
        for model in (Document, DocumentPage, Invoice, InvoiceLineItem, Vehicle, ProcessingRun):
            assert session.scalar(select(func.count(model.id))) == 0, model.__name__
        assert session.scalar(select(func.count(Case.id))) == 1
        assert session.scalar(select(Case.case_reference)) == DEFAULT_NEW_CASE_REFERENCE
        assert session.scalar(select(func.count(OntologyItem.id))) == 1
        assert session.scalar(select(func.count(PriceObservation.id))) == 1
        assert session.scalar(select(func.count(VehicleCategoryLookup.id))) > 0
        assert session.scalar(select(func.count(ConfigVersion.id))) >= 2
        assert session.scalar(select(func.count(RegulatoryRule.id))) >= 2

    assert report.kept_rows["ontology_items"] == 1
    assert report.kept_rows["price_observations"] == 1
    assert report.kept_rows["vehicle_category_lookup"] > 0


def test_reset_purges_only_the_derived_history(session_factory, populated, run_reset) -> None:
    report = run_reset()

    assert report.deleted_rows["historical_observations (derived)"] == 2
    assert report.deleted_rows["source_imports (synthetic in-house)"] == 1

    with session_factory() as session:
        remaining = session.scalars(select(HistoricalObservation)).all()
        assert [row.source_record_id for row in remaining] == ["workbook:row-1"]
        # The synthetic snapshot row has to go with its observations, or
        # ``ensure_synthetic_in_house_data`` short-circuits on the matching
        # dataset version and never regenerates the bank.
        providers = {row.name for row in session.scalars(select(SourceProvider)).all()}
        assert SYNTHETIC_PROVIDER_NAME in providers
        imports = session.scalars(select(SourceImport)).all()
        assert [row.dataset_version for row in imports] == ["seed-v1"]


def test_reset_can_keep_the_derived_history(session_factory, populated, run_reset) -> None:
    report = run_reset(purge_derived_history=False)

    assert "historical_observations (derived)" not in report.deleted_rows
    with session_factory() as session:
        assert session.scalar(select(func.count(HistoricalObservation.id))) == 3


def test_audit_triggers_survive_and_still_block_mutation(
    session_factory, populated, run_reset
) -> None:
    run_reset()

    with session_factory() as session:
        names = set(
            session.scalars(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            ).all()
        )
        assert {"audit_events_no_update", "audit_events_no_delete"} <= names

        with pytest.raises(IntegrityError, match="append-only"):
            session.execute(text("UPDATE audit_events SET actor_id = 'tamper'"))
        session.rollback()

        with pytest.raises(IntegrityError, match="append-only"):
            session.execute(text("DELETE FROM audit_events"))
        session.rollback()

    # The reset writes its own record, which becomes the first row of the new chain.
    with session_factory() as session:
        events = session.scalars(select(AuditEvent)).all()
        assert [event.event_type for event in events] == ["CASE_DATA_RESET"]
        assert events[0].previous_event_hash is None
        assert events[0].event_hash


def test_reset_removes_stored_files_and_exports(
    populated, run_reset, storage_root: Path, exports_root: Path
) -> None:
    report = run_reset()

    assert not any((storage_root / "cases").iterdir())
    assert not any(exports_root.iterdir())
    # The orphan directory - on disk with no row behind it - is cleaned too.
    assert not populated["orphan"].exists()
    assert not populated["export_dir"].exists()
    removed = {tree.path for tree in report.removed_paths}
    assert str(populated["orphan"]) in removed
    assert report.total_bytes_removed > 0


def test_reset_creates_an_upload_ready_case(session_factory, populated, run_reset) -> None:
    report = run_reset(new_case_reference="CG-CLIENT-042")

    assert report.new_case is not None
    assert report.new_case["case_reference"] == "CG-CLIENT-042"
    assert report.new_case["status"] == CaseStatus.CLAIM_REVIEW.value
    assert report.new_case["liability_gate_status"] == "awaiting_human_review"
    assert report.new_case["human_confirmed"] is False

    with session_factory() as session:
        case = session.scalar(select(Case).where(Case.case_reference == "CG-CLIENT-042"))
        assert case.documents == []
        assert case.invoices == []
        context = session.scalar(select(ClaimContext).where(ClaimContext.case_id == case.id))
        assert context is not None


def test_reset_default_case_reference_is_not_the_demo_case(populated, run_reset) -> None:
    assert DEFAULT_NEW_CASE_REFERENCE != DEMO_CASE_REFERENCE
    report = run_reset()
    assert report.new_case["case_reference"] == DEFAULT_NEW_CASE_REFERENCE


def test_reset_leaves_the_schema_intact(populated, run_reset, engine) -> None:
    before = set(
        engine.connect().execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()
    )
    run_reset()
    after = set(
        engine.connect().execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()
    )
    assert before == after


# --------------------------------------------------------------------------
# The guarded admin endpoint
# --------------------------------------------------------------------------


@pytest.fixture
def client(session_factory, populated):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_reset_endpoint_refuses_without_the_confirmation_phrase(
    client: TestClient, session_factory
) -> None:
    for payload in ({}, {"confirm": ""}, {"confirm": "delete all case data"}, {"confirm": "yes"}):
        response = client.post("/api/v1/admin/case-data/reset", json=payload)
        assert response.status_code == 422, payload

    with session_factory() as session:
        assert session.scalar(select(func.count(Case.id))) == 1
        assert session.scalar(select(Case.case_reference)) == DEMO_CASE_REFERENCE
        assert session.scalar(select(func.count(Document.id))) == 1


def test_reset_endpoint_wipes_and_reports(client: TestClient, session_factory) -> None:
    response = client.post(
        "/api/v1/admin/case-data/reset",
        json={"confirm": CONFIRMATION_PHRASE, "new_case_reference": "CG-CLIENT-007"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deleted_rows"]["cases"] == 1
    assert body["new_case"]["case_reference"] == "CG-CLIENT-007"
    assert body["kept_rows"]["ontology_items"] == 1
    assert body["total_rows_deleted"] > 0

    claims = client.get("/api/v1/claims")
    assert [claim["case_reference"] for claim in claims.json()] == ["CG-CLIENT-007"]


def test_fresh_case_accepts_an_upload_after_the_reset(
    client: TestClient, tmp_path: Path
) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data/1643919_doc_16439191.pdf.pdf"
    if not source.exists():
        pytest.skip("Supplied native PDF is not available")

    reset = client.post("/api/v1/admin/case-data/reset", json={"confirm": CONFIRMATION_PHRASE})
    assert reset.status_code == 200
    reference = reset.json()["new_case"]["case_reference"]

    with source.open("rb") as handle:
        uploaded = client.post(
            f"/api/v1/claims/{reference}/documents",
            files={"file": (source.name, handle, "application/pdf")},
            data={"role": "current"},
        )
    assert uploaded.status_code == 200
    # The liability gate blocks comparison and finalisation, not intake: the
    # fresh case is created unconfirmed and still takes an upload, processes it
    # and answers /extracts without any workflow step in between.
    empty = client.get(f"/api/v1/claims/{reference}/extracts")
    assert empty.status_code == 200
    assert empty.json() == {
        "invoice_extracts": [],
        "assessment_extracts": [],
        "section_breakdowns": [],
    }

    processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
    assert processed.status_code == 200
    assert processed.json()["status"] == "succeeded"

    extracts = client.get(f"/api/v1/claims/{reference}/extracts")
    assert extracts.status_code == 200
    assert len(extracts.json()["invoice_extracts"]) == 1

    claim = client.get(f"/api/v1/claims/{reference}")
    assert claim.json()["claim"]["liability_gate_status"] == "awaiting_human_review"
    assert claim.json()["claim"]["human_confirmed"] is False


# --------------------------------------------------------------------------
# The claimguard-reset console script
# --------------------------------------------------------------------------


@pytest.fixture
def cli(session_factory, storage_root: Path, exports_root: Path, monkeypatch):
    """Point the console script at the temporary database, never the real one."""

    monkeypatch.setattr(reset_module, "SessionLocal", session_factory)
    monkeypatch.setattr(reset_module, "initialize_database", lambda *a, **k: None)
    return reset_module.main


def test_cli_refuses_without_the_confirmation_phrase(cli, populated, session_factory) -> None:
    for argv in ([], ["--confirm", "yes"], ["--confirm", "delete all case data"]):
        with pytest.raises(SystemExit) as exit_info:
            cli(argv)
        assert exit_info.value.code == 2

    with session_factory() as session:
        assert session.scalar(select(Case.case_reference)) == DEMO_CASE_REFERENCE


def test_cli_wipes_and_prints_a_table(cli, populated, session_factory, capsys) -> None:
    assert cli(["--confirm", CONFIRMATION_PHRASE, "--case-reference", "CG-CLIENT-CLI"]) == 0
    printed = capsys.readouterr().out
    assert "Rows deleted" in printed
    assert "Rows kept" in printed
    # The operator must be able to tell reference data from case-derived data.
    assert "reference  case-derived" in printed
    assert "Files removed:" in printed
    assert "Audit log exported before deletion:" in printed
    assert "CG-CLIENT-CLI" in printed

    with session_factory() as session:
        assert session.scalar(select(Case.case_reference)) == "CG-CLIENT-CLI"
        assert session.scalar(select(func.count(Document.id))) == 0


def test_cli_can_wipe_without_creating_a_case(cli, populated, session_factory) -> None:
    assert cli(["--confirm", CONFIRMATION_PHRASE, "--no-new-case", "--json"]) == 0
    with session_factory() as session:
        assert session.scalar(select(func.count(Case.id))) == 0


# --------------------------------------------------------------------------
# The "kept reference library" that was really case data
# --------------------------------------------------------------------------


def _seed_case_derived_reference(
    session: Session, *, case_id: str, invoice: Invoice, line: InvoiceLineItem
) -> dict[str, str]:
    """Exactly what ``stage_unmatched_line_proposal`` writes for one line.

    ResearchTask -> OntologyVersion(``research-<task>``) -> provisional
    OntologyItem -> ExternalEvidence -> PriceObservation, plus the approved
    variant that a handler promotion produces. 58 of the 130 ontology items and
    58 of the 123 price observations in the developer's database look like this.
    """

    task = ResearchTask(
        case_id=case_id,
        invoice_line_item_id=line.id,
        requested_by="claimguard.auto-staging",
        initiated_automatically=True,
        query_text="Auto-staged ontology proposal for an unmatched priced invoice line",
        source_allow_list_version="internal-invoice-provenance-v1",
    )
    session.add(task)
    session.flush()
    version = OntologyVersion(
        sequence_number=90,
        label=f"research-{task.id}",
        status=OntologyVersionStatus.DRAFT,
        created_by="claimguard.auto-staging",
    )
    session.add(version)
    session.flush()
    item = OntologyItem(
        canonical_code="AUTO-STAGED-BUMPER",
        canonical_name="Rear bumper (auto-staged)",
        item_type=LineItemKind.PART,
        category="body_panel",
        unit="each",
        price_source=AUTO_STAGED_SOURCE_TYPE,
        source_url_or_ref=f"invoice-line:{line.id}",
        created_by="claimguard.auto-staging",
        created_in_version_id=version.id,
    )
    session.add(item)
    session.flush()
    evidence = ExternalEvidence(
        research_task_id=task.id,
        source_record_id=line.id,
        source_uri=f"invoice-line://{invoice.id}/{line.id}",
        title="Invoice 91283 line: Rear bumper",
        content_hash="a" * 64,
    )
    session.add(evidence)
    session.flush()
    session.add(
        ResearchItem(
            research_task_id=task.id,
            provisional_ontology_item_id=item.id,
            suggested_canonical_name="Rear bumper (auto-staged)",
            suggested_item_type=LineItemKind.PART,
            suggested_category="body_panel",
            suggested_unit="each",
            suggested_price_net="410.00",
            vat_basis=PriceVatBasis.NET,
            date_checked=date(2026, 1, 4),
            rationale="Machine-staged proposal from an unmatched priced invoice line.",
        )
    )
    provisional = PriceObservation(
        ontology_item_id=item.id,
        price_net="410.00",
        vat_basis=PriceVatBasis.NET,
        unit="each",
        source_type=AUTO_STAGED_SOURCE_TYPE,
        source_record_id=line.id,
        source_url_or_ref=evidence.source_uri,
        effective_from=date(2026, 1, 4),
        approval_status=ApprovalStatus.PROVISIONAL,
        observation_kind=PriceObservationKind.PROVISIONAL,
        evidence_id=evidence.id,
        created_in_version_id=version.id,
    )
    # The one in the developer's database that a handler already promoted: it
    # is APPROVED and MARKET, so nothing downstream filters it out.
    approved = PriceObservation(
        ontology_item_id=item.id,
        price_net="415.00",
        vat_basis=PriceVatBasis.NET,
        unit="each",
        source_type=AUTO_STAGED_SOURCE_TYPE,
        source_record_id=line.id,
        source_url_or_ref=evidence.source_uri,
        effective_from=date(2026, 1, 4),
        approval_status=ApprovalStatus.APPROVED,
        observation_kind=PriceObservationKind.MARKET,
        evidence_id=evidence.id,
        created_in_version_id=version.id,
    )
    session.add_all([provisional, approved])
    session.flush()

    # ``mapping_review._learn_approved_synonym``: attached to a *surviving*
    # reference item, with a reference into the invoice line that is about to
    # be deleted. Zero rows today; real the first time a handler approves.
    reference_item = session.scalar(
        select(OntologyItem).where(OntologyItem.canonical_code == "PANEL-FRONT-WING")
    )
    published = session.scalar(
        select(OntologyVersion).where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
    )
    session.add(
        OntologySynonym(
            ontology_item_id=reference_item.id,
            synonym="Front wing o/s",
            normalised_synonym="front wing os",
            source_type="handler_approved_invoice_mapping",
            source_reference=f"invoice_line:{line.id}",
            created_in_version_id=published.id,
        )
    )
    session.flush()
    return {"item": item.id, "version": version.id, "observations": [provisional.id, approved.id]}


@pytest.fixture
def contaminated(session_factory, populated) -> dict[str, object]:
    with session_factory() as session:
        invoice = session.scalar(select(Invoice))
        line = session.scalar(select(InvoiceLineItem))
        seeded = _seed_case_derived_reference(
            session, case_id=invoice.case_id, invoice=invoice, line=line
        )
        session.commit()
    return seeded


def test_reset_deletes_the_case_derived_reference_population(
    session_factory, contaminated, run_reset
) -> None:
    """A benchmark derived from the erased invoice must not price the next claim.

    ``external_evidence`` is wiped, so these observations also cannot be
    audited or explained any more -- they would be unfalsifiable numbers.
    """

    report = run_reset()

    assert report.deleted_rows["price_observations (case-derived)"] == 2
    assert report.deleted_rows["ontology_items (case-derived)"] == 1
    assert report.deleted_rows["ontology_versions (case-derived)"] == 1
    assert report.deleted_rows["ontology_synonyms (case-derived)"] == 1

    with session_factory() as session:
        surviving_observations = session.scalars(select(PriceObservation)).all()
        assert [row.source_type for row in surviving_observations] == ["seed_workbook"]
        assert all(row.evidence_id is None for row in surviving_observations)
        surviving_items = session.scalars(select(OntologyItem)).all()
        assert [row.canonical_code for row in surviving_items] == ["PANEL-FRONT-WING"]
        # The governed seed row and its published version are untouched.
        assert session.scalars(select(OntologySynonym)).all() == []
        labels = {row.label for row in session.scalars(select(OntologyVersion)).all()}
        assert not any(label.startswith("research-") for label in labels)
        assert labels


def test_report_separates_reference_rows_from_case_derived_rows(
    contaminated, run_reset
) -> None:
    """``price_observations: 123`` reads as reassurance until you split it."""

    report = run_reset()
    payload = report.as_dict()

    assert payload["kept_rows"]["price_observations"] == 1
    assert payload["kept_rows_reference"]["price_observations"] == 1
    assert payload["kept_rows_case_derived"]["price_observations"] == 0
    assert payload["kept_rows_case_derived"]["ontology_items"] == 0
    assert payload["total_case_derived_kept"] == 0


def test_keeping_the_derived_history_says_so_instead_of_hiding_it(
    contaminated, run_reset
) -> None:
    """Opting out is allowed; opting out quietly is not."""

    report = run_reset(purge_derived_history=False)
    payload = report.as_dict()

    assert payload["kept_rows_case_derived"]["price_observations"] == 2
    assert payload["kept_rows_case_derived"]["ontology_items"] == 1
    assert payload["kept_rows_case_derived"]["ontology_versions"] == 1
    # The synthetic in-house bank and the finalised write-back are counted too.
    assert payload["kept_rows_case_derived"]["historical_observations"] == 2
    assert payload["total_case_derived_kept"] > 0
    assert "WARNING" in reset_module.render_report(report)


def test_an_observation_is_case_derived_because_its_evidence_was(
    session_factory, populated, run_reset
) -> None:
    """The marker that the wipe itself erases.

    ``price_observations.evidence_id`` is ``ON DELETE SET NULL``: deleting
    ``external_evidence`` first destroys the only proof that an observation can
    no longer be audited. So the set is snapshotted before the wipe, and an
    observation with an innocuous ``source_type`` still goes.
    """

    with session_factory() as session:
        invoice = session.scalar(select(Invoice))
        line = session.scalar(select(InvoiceLineItem))
        task = ResearchTask(
            case_id=invoice.case_id,
            invoice_line_item_id=line.id,
            requested_by="handler",
            query_text="manual research",
            source_allow_list_version="v1",
        )
        session.add(task)
        session.flush()
        evidence = ExternalEvidence(
            research_task_id=task.id,
            source_uri="https://example.invalid/part",
            title="Supplier listing",
            content_hash="b" * 64,
        )
        session.add(evidence)
        session.flush()
        item = session.scalar(
            select(OntologyItem).where(OntologyItem.canonical_code == "PANEL-FRONT-WING")
        )
        session.add(
            PriceObservation(
                ontology_item_id=item.id,
                price_net="99.00",
                vat_basis=PriceVatBasis.NET,
                unit="each",
                source_type="looks_like_reference_data",
                effective_from=date(2026, 2, 1),
                observation_kind=PriceObservationKind.MARKET,
                evidence_id=evidence.id,
            )
        )
        session.commit()

    report = run_reset()

    assert report.deleted_rows["price_observations (case-derived)"] == 1
    with session_factory() as session:
        assert [row.source_type for row in session.scalars(select(PriceObservation)).all()] == [
            "seed_workbook"
        ]
        # Its item keeps a governed observation, so the item itself survives.
        assert session.scalar(select(func.count(OntologyItem.id))) == 1


# --------------------------------------------------------------------------
# Files: after the commit, contained, and never aborting
# --------------------------------------------------------------------------


def test_a_failed_commit_leaves_every_file_in_place(
    session_factory, populated, storage_root: Path, exports_root: Path, audit_export_root: Path
) -> None:
    """The scenario the old docstring promised could not happen.

    Files used to be deleted inside ``reset_case_data``, before the caller's
    ``commit()``. A commit that then failed -- SQLite ``database is locked``
    past the busy timeout, a full disk, a killed process -- rolled the database
    back and left every case row in place with every PDF behind it gone.
    """

    with session_factory() as session:
        report = reset_case_data(
            session,
            storage_dir=storage_root,
            exports_dir=exports_root,
            audit_export_dir=audit_export_root,
        )
        # Stand-in for the commit failing.
        session.rollback()

    assert report.pending_roots
    assert report.removed_paths == []
    assert populated["orphan"].exists()
    assert populated["export_dir"].exists()
    assert any((storage_root / "cases").iterdir())
    with session_factory() as session:
        assert session.scalar(select(func.count(Case.id))) == 1
        assert session.scalar(select(Case.case_reference)) == DEMO_CASE_REFERENCE
        assert session.scalar(select(func.count(Document.id))) == 1


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("", "empty"),
        (".", "empty"),
        ("storage", "relative"),
        ("/", "root"),
        ("/cases", "root"),
    ],
)
def test_reset_refuses_an_uncontained_storage_root(
    session_factory, populated, exports_root: Path, audit_export_root: Path, value, reason
) -> None:
    """``CLAIM_GUARD_STORAGE_DIR`` is an unvalidated env-fed ``Path``.

    ``''`` and ``'storage'`` resolve against the process cwd, so the API server
    (cwd ``backend/``) and ``claimguard-reset`` run from the repo root address
    different trees -- the CLI deletes nothing, prints ``Files removed: 0`` and
    exits 0. ``'/'`` turns the sweep into an ``rm -rf /cases``.
    """

    with session_factory() as session:
        with pytest.raises(ValueError, match="Refusing to reset"):
            reset_case_data(
                session,
                storage_dir=value,
                exports_dir=exports_root,
                audit_export_dir=audit_export_root,
            )
        session.rollback()

    # Nothing moved: the check runs before the first delete.
    with session_factory() as session:
        assert session.scalar(select(Case.case_reference)) == DEMO_CASE_REFERENCE
        assert session.scalar(select(func.count(Document.id))) == 1


def test_reset_refuses_a_root_the_writer_does_not_use(
    session_factory, populated, tmp_path: Path, exports_root: Path, audit_export_root: Path
) -> None:
    """Deleting a tree nobody writes to removes nothing and reports success.

    ``document_processing`` binds its ``settings`` at import; this module used
    to call ``get_settings()`` fresh. Identical in production, divergent the
    moment the cache is cleared or one of the two is patched.
    """

    elsewhere = tmp_path / "not-the-writers-tree"
    elsewhere.mkdir()
    with session_factory() as session:
        with pytest.raises(ValueError, match="store_pdf"):
            reset_case_data(
                session,
                storage_dir=elsewhere,
                exports_dir=exports_root,
                audit_export_dir=audit_export_root,
            )
        session.rollback()


def test_a_permission_error_mid_sweep_is_reported_not_raised(
    session_factory, populated, run_reset, storage_root: Path, monkeypatch
) -> None:
    """The database half is already committed, so raising here helps nobody."""

    real_rmtree = reset_module.shutil.rmtree
    blocked = populated["orphan"]

    def selective_rmtree(path, *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError(13, "Permission denied", str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(reset_module.shutil, "rmtree", selective_rmtree)

    report = run_reset()

    assert [failure.path for failure in report.sweep_failures] == [str(blocked)]
    assert "Permission denied" in report.sweep_failures[0].error
    assert blocked.exists()
    # Every other directory still went, and the wipe still happened.
    assert report.removed_paths
    assert "COULD NOT REMOVE" in reset_module.render_report(report)
    with session_factory() as session:
        assert session.scalar(select(func.count(Document.id))) == 0


def test_the_report_names_the_roots_before_anything_is_deleted(
    session_factory, populated, storage_root: Path, exports_root: Path, audit_export_root: Path
) -> None:
    with session_factory() as session:
        report = reset_case_data(
            session,
            storage_dir=storage_root,
            exports_dir=exports_root,
            audit_export_dir=audit_export_root,
        )
        session.commit()

    assert report.pending_roots == [
        str((storage_root / "cases").resolve()),
        str(exports_root.resolve()),
    ]
    printed = reset_module.render_report(report)
    assert "Delete roots (resolved before anything was removed)" in printed
    assert "Nothing removed yet" in printed
    assert str(exports_root.resolve()) in printed
    reset_module.clear_reset_paths(report)
    assert report.pending_roots == []


# --------------------------------------------------------------------------
# The audit chain leaves before it is destroyed
# --------------------------------------------------------------------------


def test_the_audit_chain_is_exported_before_it_is_wiped(
    session_factory, populated, run_reset, audit_export_root: Path
) -> None:
    """Wiping ``audit_events`` erases the tamper evidence it exists to provide.

    That is only defensible if the log leaves first, in full, with a digest.
    """

    with session_factory() as session:
        before = session.scalars(select(AuditEvent)).all()
        expected = {row.id for row in before}
    assert expected

    report = run_reset()

    export = Path(report.audit_export["path"])
    assert export.parent == audit_export_root
    assert export.is_file()
    lines = export.read_text(encoding="utf-8").splitlines()
    assert report.audit_export["events"] == len(lines) == len(expected)
    assert {json.loads(line)["id"] for line in lines} == expected
    # Every column, not a summary: the chain has to be reconstructable.
    first = json.loads(lines[0])
    assert {"event_hash", "previous_event_hash", "event_type", "actor_id"} <= set(first)
    digest = hashlib.sha256(export.read_bytes()).hexdigest()
    assert digest == report.audit_export["sha256"]

    assert report.deleted_rows["audit_events"] == len(expected)
    with session_factory() as session:
        remaining = session.scalars(select(AuditEvent)).all()
        assert [row.event_type for row in remaining] == ["CASE_DATA_RESET"]
        assert remaining[0].event_payload_json["audit_export"]["sha256"] == digest


def test_a_reset_without_a_new_case_still_records_itself(
    session_factory, populated, run_reset
) -> None:
    """The only row that says the old chain was deleted on purpose."""

    run_reset(new_case_reference=None)

    with session_factory() as session:
        events = session.scalars(select(AuditEvent)).all()
        assert [row.event_type for row in events] == ["CASE_DATA_RESET"]
        assert events[0].case_id is None


def test_reset_endpoint_reports_an_uncontained_root_instead_of_deleting(
    client: TestClient, session_factory, monkeypatch
) -> None:
    """A misconfigured env var must fail the request, not the database."""

    monkeypatch.setattr(document_processing.settings, "storage_dir", Path("/"))
    response = client.post(
        "/api/v1/admin/case-data/reset", json={"confirm": CONFIRMATION_PHRASE}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESET_FAILED"
    assert "filesystem root" in response.json()["detail"]["message"]

    with session_factory() as session:
        assert session.scalar(select(Case.case_reference)) == DEMO_CASE_REFERENCE
        assert session.scalar(select(func.count(Document.id))) == 1


def test_reset_endpoint_reports_the_split_and_the_audit_export(
    client: TestClient, contaminated, audit_export_root: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        reset_module, "AUDIT_EXPORT_DIRNAME", audit_export_root.name
    )
    response = client.post(
        "/api/v1/admin/case-data/reset", json={"confirm": CONFIRMATION_PHRASE}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_case_derived_kept"] == 0
    assert body["kept_rows_case_derived"]["price_observations"] == 0
    assert body["deleted_rows"]["price_observations (case-derived)"] == 2
    assert Path(body["audit_export"]["path"]).is_file()
    assert body["sweep_failures"] == []
    # The sweep runs after the commit, so by the time the client sees the body
    # the roots are cleared and nothing is still pending.
    assert body["pending_roots"] == []
    # ...but the roots this run addressed are still named, because the silent
    # failure mode is a wrong root, not a missing one.
    assert len(body["resolved_roots"]) == 2
    assert all(root.startswith("/") for root in body["resolved_roots"])
    assert body["removed_paths"]


def test_cli_exits_non_zero_when_files_are_left_behind(
    cli, populated, capsys, monkeypatch
) -> None:
    """Rows gone, files still on disk: that is not "done"."""

    monkeypatch.setattr(
        reset_module.shutil,
        "rmtree",
        lambda path, *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")),
    )
    assert cli(["--confirm", CONFIRMATION_PHRASE]) == 1
    captured = capsys.readouterr()
    assert "Clearing" in captured.err
    assert "Could not remove" in captured.err
    assert "COULD NOT REMOVE" in captured.out


# --------------------------------------------------------------------------
# claimguard-bootstrap must not undo the reset
# --------------------------------------------------------------------------


def test_bootstrap_refuses_to_rebuild_a_case_the_reset_removed(
    session_factory, populated, run_reset
) -> None:
    """Renaming the demo case would not help: the harm is the data, not the label.

    ``claimguard-bootstrap``'s idempotence check is "does this reference
    exist", which is the right question until a reset makes the answer
    deliberately no. Rebuilding would re-ingest the demo invoice and re-mint the
    ontology rows derived from it -- exactly what the client asked to be rid of.
    """

    with session_factory() as session:
        # Before any reset the guard is silent.
        bootstrap._refuse_after_reset(session, bootstrap.DEFAULT_CASE_REFERENCE, force=False)

    run_reset()

    with session_factory() as session:
        with pytest.raises(RuntimeError, match="deliberately"):
            bootstrap._refuse_after_reset(
                session, bootstrap.DEFAULT_CASE_REFERENCE, force=False
            )
        # ``--force`` is the deliberate override.
        bootstrap._refuse_after_reset(session, bootstrap.DEFAULT_CASE_REFERENCE, force=True)


def test_bootstrap_default_reference_is_still_the_demo_case_but_overridable(
    session_factory, populated, run_reset
) -> None:
    assert bootstrap.DEFAULT_CASE_REFERENCE == DEMO_CASE_REFERENCE
    assert bootstrap.CASE_REFERENCE == bootstrap.DEFAULT_CASE_REFERENCE

    run_reset()
    # The refusal is on the reset marker, so a different reference is refused too.
    with session_factory() as session:
        with pytest.raises(RuntimeError, match="CG-SOMETHING-ELSE"):
            bootstrap._refuse_after_reset(session, "CG-SOMETHING-ELSE", force=False)
