"""Batch intake: a folder of repair invoices and a folder of engineer estimates.

The client asked to hand over a whole set at once -- Neha's first population
pass is "five invoices plus corresponding estimates" -- where the form takes
one of each. The pairing gate in ``_select_invoice`` makes this more than a
convenience: an assessment and an invoice in different ``intake_group`` buckets
can never pair, so a batch that splits the two folders across groups would
silently pair nothing. These tests hold that end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.init_db import initialize_database
from app.main import app
from app.models import Case, Document, EngineerAssessment
from app.services import document_processing

PAIR_DIR = Path(__file__).resolve().parents[3] / "sample-data" / "engineer-invoice-pairs"
CASE_REFERENCE = "CG-BATCH-001"


@pytest.fixture
def session_factory(tmp_path: Path, monkeypatch):
    if not PAIR_DIR.is_dir():
        pytest.skip("Engineer Assessment fixtures are not available")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'batch.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, record):  # noqa: ARG001 - SQLAlchemy event signature
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    yield sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(session_factory):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def case(session_factory) -> str:
    with session_factory() as session:
        session.add(Case(case_reference=CASE_REFERENCE, created_by="pytest.handler"))
        session.commit()
    return CASE_REFERENCE


def _files(field: str, suffix: str, count: int = 5) -> list[tuple[str, tuple[str, bytes, str]]]:
    payload = []
    for sequence in range(1, count + 1):
        path = PAIR_DIR / f"CLM-UK-{sequence:03d}_{suffix}.pdf"
        payload.append((field, (path.name, path.read_bytes(), "application/pdf")))
    return payload


def test_batch_accepts_both_folders_and_reports_every_file(client: TestClient, case: str) -> None:
    response = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=[*_files("invoice_files", "Repair_Invoice"), *_files("estimate_files", "Engineer_Assessment")],
        data={"role": "current"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 10
    assert body["failed"] == 0
    assert len(body["results"]) == 10
    # Invoices are queued first so each estimate has something to pair against
    # by the time it is processed.
    assert [row["slot"] for row in body["results"]] == ["invoice"] * 5 + ["estimate"] * 5
    assert all(row["status"] == "processed" for row in body["results"])
    assert all(row["document_id"] for row in body["results"])
    assert sum(row["invoice_units"] for row in body["results"]) == 5
    assert sum(1 for row in body["results"] if row["assessment_id"]) == 5


def test_batch_lands_both_folders_in_one_intake_group_and_pairs(
    client: TestClient, case: str, session_factory
) -> None:
    response = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=[*_files("invoice_files", "Repair_Invoice"), *_files("estimate_files", "Engineer_Assessment")],
        data={"intake_group": "live"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intake_group"] == "live"
    assert body["pairing"]["assessments"] == 5
    assert body["pairing"]["paired"] == 5
    assert body["pairing"]["unpaired"] == 0
    assert all(row["paired_invoice_id"] for row in body["pairing"]["details"])

    # The gate is on document metadata, so prove both folders really landed in
    # the same bucket rather than trusting the pairing result alone.
    with session_factory() as session:
        groups = {
            (document.metadata_json or {}).get("intake_group")
            for document in session.scalars(select(Document)).all()
        }
        assert groups == {"live"}


def test_mismatched_intake_groups_never_pair(client: TestClient, case: str) -> None:
    """The trap the batch endpoint exists to avoid, held as a regression."""

    invoice = PAIR_DIR / "CLM-UK-001_Repair_Invoice.pdf"
    estimate = PAIR_DIR / "CLM-UK-001_Engineer_Assessment.pdf"
    for path, group in ((invoice, "live"), (estimate, None)):
        uploaded = client.post(
            f"/api/v1/claims/{case}/documents",
            files={"file": (path.name, path.read_bytes(), "application/pdf")},
            data={"role": "current", **({"intake_group": group} if group else {})},
        )
        assert uploaded.status_code == 200
        processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
        assert processed.status_code == 200

    swept = client.post(f"/api/v1/claims/{case}/documents/link-sweep")
    assert swept.status_code == 200
    assert swept.json()["paired"] == 0
    assert swept.json()["unpaired"] == 1


def test_link_sweep_pairs_estimates_uploaded_before_their_invoices(
    client: TestClient, case: str
) -> None:
    """Neha's step 3: "at the end, run a check" over all the documents."""

    estimates = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=_files("estimate_files", "Engineer_Assessment"),
        data={"intake_group": "live", "run_sweep": "false"},
    )
    assert estimates.status_code == 200
    assert estimates.json()["accepted"] == 5

    invoices = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=_files("invoice_files", "Repair_Invoice"),
        data={"intake_group": "live", "run_sweep": "false"},
    )
    assert invoices.status_code == 200
    assert invoices.json()["pairing"] is None

    swept = client.post(f"/api/v1/claims/{case}/documents/link-sweep")
    assert swept.status_code == 200
    body = swept.json()
    assert body["case_reference"] == case
    assert body["assessments"] == 5
    assert body["paired"] == 5

    # Idempotent: the fill reverses its own earlier writes before re-evaluating.
    again = client.post(f"/api/v1/claims/{case}/documents/link-sweep")
    assert again.json()["paired"] == 5


def test_one_unreadable_file_fails_alone(client: TestClient, case: str, session_factory) -> None:
    good = PAIR_DIR / "CLM-UK-001_Repair_Invoice.pdf"
    response = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=[
            ("invoice_files", (good.name, good.read_bytes(), "application/pdf")),
            ("invoice_files", ("broken.pdf", b"not a pdf at all", "application/pdf")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["failed"] == 1
    failed = [row for row in body["results"] if row["status"] == "failed"]
    assert failed[0]["filename"] == "broken.pdf"
    assert failed[0]["error"]

    with session_factory() as session:
        stored = session.scalars(select(Document)).all()
        assert [document.original_filename for document in stored] == [good.name]


def test_empty_batch_is_rejected(client: TestClient, case: str) -> None:
    response = client.post(f"/api/v1/claims/{case}/documents/batch", data={"role": "current"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMPTY_BATCH"


def test_batch_can_store_without_processing(
    client: TestClient, case: str, session_factory
) -> None:
    response = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=_files("invoice_files", "Repair_Invoice", count=2),
        data={"process": "false"},
    )
    assert response.status_code == 200
    assert [row["status"] for row in response.json()["results"]] == ["stored", "stored"]
    assert response.json()["pairing"] is None
    with session_factory() as session:
        assert len(session.scalars(select(Document)).all()) == 2
        assert session.scalars(select(EngineerAssessment)).all() == []


def test_batch_rejects_an_unknown_case_and_intake_group(client: TestClient, case: str) -> None:
    good = PAIR_DIR / "CLM-UK-001_Repair_Invoice.pdf"
    payload = [("invoice_files", (good.name, good.read_bytes(), "application/pdf"))]

    missing = client.post("/api/v1/claims/CG-DOES-NOT-EXIST/documents/batch", files=payload)
    assert missing.status_code == 404

    bad_group = client.post(
        f"/api/v1/claims/{case}/documents/batch",
        files=payload,
        data={"intake_group": "not_a_group"},
    )
    assert bad_group.status_code == 422
    assert bad_group.json()["detail"]["code"] == "INVALID_DOCUMENT"
