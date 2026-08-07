from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.enums import (
    ApprovalStatus,
    InvoiceDocumentRole,
    OntologyItemStatus,
)
from app.importers.seed_workbooks import load_seed_workbooks
from app.init_db import initialize_database
from app.models import (
    HistoricalObservation,
    OntologyItem,
    OntologySynonym,
    OntologyVersion,
    PriceObservation,
    SourceImport,
    SourceProvider,
    VehicleApplicability,
)
from app.services.benchmarking import benchmark_observations, build_benchmark_dashboard
from app.services.seed_import_service import import_seed_workbooks

SAMPLE_DATA = Path(__file__).resolve().parents[2] / "sample-data"
ONTOLOGY_PATH = SAMPLE_DATA / "ontology_seed.xlsx"
HISTORY_PATH = SAMPLE_DATA / "historical_claims_seed.xlsx"


@pytest.fixture()
def seed_engine(tmp_path: Path):
    if not ONTOLOGY_PATH.exists() or not HISTORY_PATH.exists():
        pytest.skip("Supplied seed workbooks are not available")

    test_engine = create_engine(f"sqlite:///{tmp_path / 'seed-import.db'}")

    @event.listens_for(test_engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(test_engine, seed_defaults=True)
    yield test_engine
    test_engine.dispose()


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_governed_seed_import_persists_expected_rows_and_lineage(seed_engine) -> None:
    bundle = load_seed_workbooks(ONTOLOGY_PATH, HISTORY_PATH)

    with Session(seed_engine, expire_on_commit=False) as session:
        result = import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        session.commit()

        assert result.ontology_items_created == 72
        assert result.price_observations_created == 63
        assert result.historical_observations_created == 191
        assert result.acceptance_gold_excluded == 34

        assert _count(session, SourceProvider) == 1
        assert _count(session, SourceImport) == 2
        assert _count(session, OntologyVersion) == 1
        assert _count(session, OntologyItem) == 72
        assert _count(session, OntologySynonym) == 195
        assert _count(session, VehicleApplicability) == 72
        assert _count(session, PriceObservation) == 63
        assert _count(session, HistoricalObservation) == 191

        assert (
            session.scalar(
                select(func.count())
                .select_from(HistoricalObservation)
                .where(HistoricalObservation.observation_type == InvoiceDocumentRole.INVOICE)
            )
            == 188
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(HistoricalObservation)
                .where(HistoricalObservation.observation_type == InvoiceDocumentRole.ESTIMATE)
            )
            == 3
        )

        gold_ids = {row.claim_line_id for row in bundle.acceptance_gold}
        runtime_ids = set(session.scalars(select(HistoricalObservation.source_record_id)).all())
        assert gold_ids.isdisjoint(runtime_ids)

        assert (
            session.scalar(
                select(func.count())
                .select_from(OntologyItem)
                .where(OntologyItem.status != OntologyItemStatus.PROVISIONAL)
            )
            == 0
        )
        for model in (
            OntologyItem,
            OntologySynonym,
            VehicleApplicability,
            PriceObservation,
            HistoricalObservation,
        ):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.approval_status != ApprovalStatus.PROVISIONAL)
                )
                == 0
            )

        assert (
            session.scalar(
                select(func.count())
                .select_from(HistoricalObservation)
                .join(
                    OntologyItem,
                    HistoricalObservation.ontology_item_id == OntologyItem.id,
                )
            )
            == 191
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OntologyItem)
                .where(OntologyItem.created_in_version_id == result.ontology_version_id)
            )
            == 72
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(PriceObservation)
                .where(PriceObservation.source_import_id == result.ontology_import_id)
            )
            == 63
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(HistoricalObservation)
                .where(HistoricalObservation.source_import_id == result.history_import_id)
            )
            == 191
        )

        imports = session.scalars(select(SourceImport)).all()
        by_role = {
            source_import.validation_report_json["dataset_role"]: source_import
            for source_import in imports
        }
        ontology_import = by_role["ontology"]
        history_import = by_role["previous_repair_and_service_invoices"]
        assert ontology_import.row_count == ontology_import.accepted_count == 72
        assert history_import.row_count == history_import.accepted_count == 191
        assert len(ontology_import.validation_report_json["sha256"]) == 64
        assert len(history_import.validation_report_json["sha256"]) == 64
        assert ontology_import.validation_report_json["missing_price_count"] == 9
        assert history_import.validation_report_json["runtime_counts"] == {
            "invoice": 188,
            "estimate": 3,
        }
        assert history_import.validation_report_json["acceptance_gold"] == {
            "excluded_from_runtime_history": True,
            "excluded_count": 34,
            "invoice_numbers": ["90538", "91283"],
        }


def test_seed_history_populates_the_invoice_only_benchmark_dashboard(seed_engine) -> None:
    with Session(seed_engine, expire_on_commit=False) as session:
        import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        session.commit()

        dashboard = build_benchmark_dashboard(session)

        assert dashboard["summary"]["observationCount"] == 187
        assert dashboard["summary"]["averageRepairCost"] is not None
        assert dashboard["benchmarks"]
        assert all(row["statistics"]["count"] > 0 for row in dashboard["benchmarks"])
        assert all(row["invoiceCount"] > 0 for row in dashboard["benchmarks"])
        assert all(
            row["exceptionCount"] == len(row["exceptions"])
            for row in dashboard["benchmarks"]
        )
        assert all(
            row["exceptionInvoiceCount"]
            == len({item["invoiceNumber"] for item in row["exceptions"]})
            for row in dashboard["benchmarks"]
        )
        assert dashboard["appliedFilters"]["challengeThresholdPct"] == 10.0
        assert dashboard["appliedFilters"]["minimumChallengeAmount"] == 5.0
        assert dashboard["repairerTrends"]
        assert all(row["items"] for row in dashboard["repairerTrends"])
        assert dashboard["dataQuality"]["invoiceObservationCount"] == 188
        assert dashboard["dataQuality"]["invalidOrMissingCostCount"] == 1
        assert dashboard["dataQuality"]["classifiedCount"] == 187
        assert dashboard["dataQuality"]["unclassifiedCount"] == 0
        assert dashboard["dataQuality"]["classifiedCoveragePct"] == 100.0
        assert {row["vehicleClass"] for row in dashboard["vehicleCategories"]} == {
            "Compact SUV",
            "Family car",
            "Large SUV",
        }

        strong_only = build_benchmark_dashboard(session, minimum_count=10)
        assert strong_only["benchmarks"]
        assert all(row["statistics"]["count"] >= 10 for row in strong_only["benchmarks"])
        first = strong_only["benchmarks"][0]
        sources = benchmark_observations(
            session,
            first["ontologyItemId"],
            vehicle_class=first["vehicleClass"],
        )
        assert len(sources) == first["sourceCount"]
        assert all(source["amount"] and source["amount"] > 0 for source in sources)
        assert all(source["vehicleClass"] != "Unclassified" for source in sources)


def test_reimporting_identical_workbooks_is_idempotent(seed_engine) -> None:
    with Session(seed_engine, expire_on_commit=False) as session:
        first = import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        session.commit()
        import_times = {
            row.id: row.created_at for row in session.scalars(select(SourceImport)).all()
        }

        replay = import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        session.commit()

        assert replay.provider_id == first.provider_id
        assert replay.ontology_import_id == first.ontology_import_id
        assert replay.history_import_id == first.history_import_id
        assert replay.ontology_version_id == first.ontology_version_id
        assert replay.ontology_items_created == 0
        assert replay.price_observations_created == 0
        assert replay.historical_observations_created == 0
        assert replay.acceptance_gold_excluded == 34

        assert _count(session, SourceProvider) == 1
        assert _count(session, SourceImport) == 2
        assert _count(session, OntologyItem) == 72
        assert _count(session, OntologySynonym) == 195
        assert _count(session, VehicleApplicability) == 72
        assert _count(session, PriceObservation) == 63
        assert _count(session, HistoricalObservation) == 191
        assert {
            row.id: row.created_at for row in session.scalars(select(SourceImport)).all()
        } == import_times
