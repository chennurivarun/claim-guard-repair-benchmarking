"""An empty database is a starting point, not a dead end.

A downloaded ZIP served without ``claimguard-setup`` -- or a database left by
``claimguard-reset --no-new-case`` -- holds no claim at all. The app used to
tell that user to "upload a repair invoice" while offering no upload control
anywhere, because every upload screen needs a claim to upload into.

``POST /claims/start`` is the one-click way out. These tests pin down that it
leaves exactly the state ``claimguard-setup`` leaves (the same empty case, the
same reference library), that every screen of the upload flow answers on it,
and that it can never add a claim to a database that already has one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap import HISTORY_PATH, ONTOLOGY_PATH
from app.database import get_db
from app.enums import CaseStatus, LiabilityGateStatus
from app.init_db import initialize_database
from app.main import app
from app.models import Case, ClaimContext, HistoricalObservation, OntologyItem
from app.reset import DEFAULT_NEW_CASE_REFERENCE

START_URL = "/api/v1/claims/start"


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'empty.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, record):  # noqa: ARG001 - SQLAlchemy event signature
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
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


def _case_count(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count(Case.id))) or 0


def test_starting_on_an_empty_database_creates_the_setup_case(
    client: TestClient, session_factory
) -> None:
    assert client.get("/api/v1/claims").json() == []

    response = client.post(START_URL)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["case_reference"] == DEFAULT_NEW_CASE_REFERENCE
    assert body["upload_ready"] is True

    with session_factory() as session:
        case = session.scalar(select(Case))
        context = session.scalar(select(ClaimContext))
        assert case is not None and context is not None
        # Exactly what ``create_empty_case`` -- shared by setup and reset -- writes.
        assert case.case_reference == DEFAULT_NEW_CASE_REFERENCE
        assert case.status == CaseStatus.CLAIM_REVIEW
        assert context.case_id == case.id
        assert context.claim_number == DEFAULT_NEW_CASE_REFERENCE
        assert context.liability_gate_status == LiabilityGateStatus.AWAITING_HUMAN_REVIEW
        assert context.human_confirmed is False
        if ONTOLOGY_PATH.is_file() and HISTORY_PATH.is_file():
            # The reference library setup imports: without it comparison refuses.
            assert (session.scalar(select(func.count(OntologyItem.id))) or 0) > 0
            assert (session.scalar(select(func.count(HistoricalObservation.id))) or 0) > 0

    listed = client.get("/api/v1/claims").json()
    assert [entry["case_reference"] for entry in listed] == [DEFAULT_NEW_CASE_REFERENCE]


def test_every_screen_of_the_upload_flow_answers_on_the_started_claim(
    client: TestClient,
) -> None:
    reference = client.post(START_URL).json()["case_reference"]
    base = f"/api/v1/claims/{reference}"

    assert client.get(f"{base}/document-mapping").status_code == 200
    assert client.get(f"{base}/extracts").status_code == 200
    for source in ("third_party", "aviva_dlg"):
        response = client.get(f"{base}/benchmarks", params={"source": source})
        assert response.status_code == 200, response.text
    # No new invoice is uploaded yet: the analysis says so, it does not crash.
    analysis = client.get(f"{base}/benchmark-analysis")
    assert analysis.status_code < 500, analysis.text


def test_starting_twice_never_makes_a_second_claim(
    client: TestClient, session_factory
) -> None:
    assert client.post(START_URL).status_code == 201

    again = client.post(START_URL)

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "CLAIMS_EXIST"
    assert again.json()["detail"]["case_reference"] == DEFAULT_NEW_CASE_REFERENCE
    assert _case_count(session_factory) == 1


def test_starting_never_adds_a_claim_when_any_claim_exists(
    client: TestClient, session_factory
) -> None:
    created = client.post(
        "/api/v1/claims",
        json={"case_reference": "CG-HANDMADE-7", "claim_number": "HM-7"},
    )
    assert created.status_code == 201, created.text

    response = client.post(START_URL)

    assert response.status_code == 409
    assert response.json()["detail"]["case_reference"] == "CG-HANDMADE-7"
    assert _case_count(session_factory) == 1
