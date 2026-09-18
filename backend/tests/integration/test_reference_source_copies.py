"""One client file, copied into both reference sources.

On 17 Sep the client asked for copies of the same invoices to be shown under
Aviva DLG *and* under third party, "because the same kind of invoices will
come from both".  A copied Word file is byte-identical, so the upload used to
de-duplicate the second copy against the first and refuse it as "another
intake group".  A byte-identical file may now exist once per reference source;
it still may not also be the new (``live``) invoice, because an invoice
benchmarked against its own twin matches itself and hides every discrepancy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- register every mapper before create_all
from app.config import get_settings
from app.database import get_db
from app.enums import DocumentRole
from app.init_db import initialize_database
from app.main import app
from app.models import Case, Document, EngineerAssessment, Invoice
from app.services.document_processing import store_pdf

FIXTURES = Path(__file__).resolve().parents[3] / "sample-data" / "client-formats"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REFERENCE = "CG-COPIES-001"
INVOICE = "DL_Repair_Invoice_format_7.docx"
ASSESSMENT = "DL_Auda_format_7_assessment.docx"


@pytest.fixture
def copies_client(tmp_path, monkeypatch):
    if not FIXTURES.is_dir():
        pytest.skip("Client format fixtures are not available")
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'copies.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    from app.services import document_processing

    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    with TestClient(app) as client:
        client.factory = factory
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def _batch(client: TestClient, group: str, *, estimate: bool = True) -> dict:
    files = [("invoice_files", (INVOICE, (FIXTURES / INVOICE).read_bytes(), DOCX_MIME))]
    if estimate:
        files.append(
            ("estimate_files", (ASSESSMENT, (FIXTURES / ASSESSMENT).read_bytes(), DOCX_MIME))
        )
    response = client.post(
        f"/api/v1/claims/{REFERENCE}/documents/batch",
        files=files,
        data={"intake_group": group},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _benchmarks(client: TestClient, source: str) -> dict:
    response = client.get(f"/api/v1/claims/{REFERENCE}/benchmarks?source={source}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_same_file_is_one_document_per_reference_source(copies_client):
    client = copies_client
    created = client.post(
        "/api/v1/claims",
        json={"case_reference": REFERENCE, "claim_number": "2026/COPY/1", "created_by": "pytest"},
    )
    assert created.status_code == 201, created.text

    third_party = _batch(client, "historical_claim")
    assert third_party["failed"] == 0, third_party
    aviva = _batch(client, "in_house")
    # The client's own instruction: the copy goes into Aviva DLG as well.
    assert aviva["failed"] == 0, aviva
    assert {row["status"] for row in aviva["results"]} == {"processed"}

    with client.factory() as session:
        documents = session.scalars(select(Document)).all()
        assert len(documents) == 4
        by_group: dict[str, list[Document]] = {}
        for document in documents:
            # The column and the metadata key never disagree.
            assert document.intake_group == (document.metadata_json or {}).get("intake_group")
            by_group.setdefault(document.intake_group, []).append(document)
        assert set(by_group) == {"historical_claim", "in_house"}
        # Each copy is stored and rendered in its own directory.
        paths = {document.storage_path for document in documents}
        assert len(paths) == 4

        invoices = session.scalars(select(Invoice)).all()
        assert len(invoices) == 2
        invoice_group = {
            invoice.id: invoice.document.intake_group for invoice in invoices
        }
        assert set(invoice_group.values()) == {"historical_claim", "in_house"}

        assessments = session.scalars(select(EngineerAssessment)).all()
        assert len(assessments) == 2
        for assessment in assessments:
            # Each copy pairs with its own source's invoice copy, never the twin.
            assert assessment.paired_invoice_id is not None, assessment.document.original_filename
            assert invoice_group[assessment.paired_invoice_id] == assessment.document.intake_group

    tp_bench = _benchmarks(client, "third_party")
    aviva_bench = _benchmarks(client, "aviva_dlg")
    assert tp_bench["invoice_count"] == 1
    assert aviva_bench["invoice_count"] == 1
    tp_invoice = tp_bench["invoices"][0]["invoice_id"]
    aviva_invoice = aviva_bench["invoices"][0]["invoice_id"]
    assert tp_invoice != aviva_invoice
    assert invoice_group[tp_invoice] == "historical_claim"
    assert invoice_group[aviva_invoice] == "in_house"
    for row in tp_bench["rows"]:
        assert {evidence["invoice_id"] for evidence in row["evidence"]} <= {tp_invoice}

    # Re-uploading into the same source creates nothing.
    again = _batch(client, "in_house")
    assert again["failed"] == 0, again
    assert {row["status"] for row in again["results"]} == {"already_processed"}
    assert {row["document_id"] for row in again["results"]} == {
        document.id for document in by_group["in_house"]
    }
    with client.factory() as session:
        assert len(session.scalars(select(Document)).all()) == 4

    # ...but the file can never also be the new invoice being checked.
    live = _batch(client, "live", estimate=False)
    assert live["failed"] == 1
    error = live["results"][0]["error"]
    assert "Third party insured invoices" in error and "Aviva DLG invoices" in error, error
    assert "live demo" not in error
    assert "match itself" in error, error
    with client.factory() as session:
        assert len(session.scalars(select(Document)).all()) == 4


def _case(session: Session) -> Case:
    case = Case(case_reference=REFERENCE, created_by="pytest")
    session.add(case)
    session.flush()
    return case


def test_live_file_cannot_become_a_reference_copy(copies_client):
    content = (FIXTURES / INVOICE).read_bytes()
    with copies_client.factory() as session:
        case = _case(session)
        live = store_pdf(session, case=case, filename=INVOICE, content=content, intake_group="live")
        with pytest.raises(ValueError) as refused:
            store_pdf(
                session, case=case, filename=INVOICE, content=content,
                role=DocumentRole.HISTORICAL, intake_group="in_house",
            )
        message = str(refused.value)
        assert "new invoice" in message and "Aviva DLG invoices" in message, message
        assert live.intake_group == "live"


def test_ungrouped_document_is_adopted_into_a_reference_source(copies_client):
    content = (FIXTURES / INVOICE).read_bytes()
    with copies_client.factory() as session:
        case = _case(session)
        loose = store_pdf(session, case=case, filename=INVOICE, content=content)
        assert loose.intake_group is None
        adopted = store_pdf(
            session, case=case, filename=INVOICE, content=content,
            role=DocumentRole.HISTORICAL, intake_group="historical_claim",
        )
        assert adopted.id == loose.id
        assert adopted.intake_group == "historical_claim"
        assert adopted.metadata_json["intake_group"] == "historical_claim"
        assert adopted.document_role == DocumentRole.HISTORICAL
        session.flush()
        # The copy into the other reference source is a new document.
        copy = store_pdf(
            session, case=case, filename=INVOICE, content=content,
            role=DocumentRole.HISTORICAL, intake_group="in_house",
        )
        assert copy.id != loose.id
        assert copy.intake_group == "in_house"
        assert len(session.scalars(select(Document)).all()) == 2


def _copy(case: Case, group: str | None) -> Document:
    return Document(
        case_id=case.id,
        original_filename="copy.pdf",
        storage_path="/nowhere/copy.pdf",
        sha256="a" * 64,
        file_size=1,
        metadata_json={"intake_group": group},
    )


def test_database_holds_one_copy_per_source_and_one_ungrouped_copy(copies_client):
    """The rule is enforced by the database, not only by ``store_pdf``.

    NULLs are distinct under a plain unique constraint, so the three-column
    constraint alone would let two ungrouped copies in; the partial index
    ``uq_documents_case_sha256_ungrouped`` is what keeps them out.
    """

    with copies_client.factory() as session:
        case = _case(session)
        session.add_all([_copy(case, "historical_claim"), _copy(case, "in_house"), _copy(case, None)])
        session.flush()

        for group in (None, "in_house"):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(_copy(case, group))
                session.flush()
