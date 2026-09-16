"""The clean-slate reset: wipe case data, keep the reference library.

Every assertion here is about a trap that a naive ``DELETE FROM cases`` walks
into -- the append-only audit triggers, the ``SET NULL`` vehicle orphans, the
circular processing-run FK, and the files no cascade ever touches.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.reset as reset_module
from app.config import get_settings
from app.database import get_db
from app.enums import (
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
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    OntologyItem,
    OntologyVersion,
    PriceObservation,
    ProcessingRun,
    RegulatoryRule,
    SourceImport,
    SourceProvider,
    Vehicle,
    VehicleCategoryLookup,
)
from app.reset import CONFIRMATION_PHRASE, DEFAULT_NEW_CASE_REFERENCE, reset_case_data
from app.services import document_processing
from app.services.in_house_repair_data import PROVIDER_NAME as SYNTHETIC_PROVIDER_NAME

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
def run_reset(session_factory, storage_root: Path, exports_root: Path):
    """Call the reset with explicit roots, so no test can depend on settings."""

    def _run(**kwargs) -> reset_module.ResetReport:
        kwargs.setdefault("storage_dir", storage_root)
        kwargs.setdefault("exports_dir", exports_root)
        with session_factory() as session:
            report = reset_case_data(session, **kwargs)
            session.commit()
        return report

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
    assert "Reference data kept" in printed
    assert "Files removed:" in printed
    assert "CG-CLIENT-CLI" in printed

    with session_factory() as session:
        assert session.scalar(select(Case.case_reference)) == "CG-CLIENT-CLI"
        assert session.scalar(select(func.count(Document.id))) == 0


def test_cli_can_wipe_without_creating_a_case(cli, populated, session_factory) -> None:
    assert cli(["--confirm", CONFIRMATION_PHRASE, "--no-new-case", "--json"]) == 0
    with session_factory() as session:
        assert session.scalar(select(func.count(Case.id))) == 0
