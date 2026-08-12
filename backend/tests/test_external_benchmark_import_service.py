from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.enums import ApprovalStatus, PriceObservationKind
from app.init_db import initialize_database
from app.models import OntologyItem, PriceObservation, SourceImport, SourceProvider
from app.services.external_benchmark_import_service import import_external_uk_benchmarks
from app.services.seed_import_service import import_seed_workbooks

SAMPLE_DATA = Path(__file__).resolve().parents[2] / "sample-data"


@pytest.fixture()
def research_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'external-research.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    yield engine
    engine.dispose()


def test_external_uk_observations_are_traceable_provisional_and_idempotent(
    research_engine,
) -> None:
    with Session(research_engine, expire_on_commit=False) as session:
        import_seed_workbooks(
            session,
            SAMPLE_DATA / "ontology_seed.xlsx",
            SAMPLE_DATA / "historical_claims_seed.xlsx",
        )
        first = import_external_uk_benchmarks(
            session, SAMPLE_DATA / "uk_external_benchmarks.csv"
        )
        session.commit()

        assert first.providers_created == 2
        assert first.imports_created == 2
        assert first.observations_created == 2
        assert first.rows_skipped == 0

        observations = list(
            session.scalars(
                select(PriceObservation).where(
                    PriceObservation.source_type == "external_uk_public_research"
                )
            ).all()
        )
        assert len(observations) == 2
        assert {row.currency for row in observations} == {"GBP"}
        assert {row.region for row in observations} == {"UK"}
        assert {row.approval_status for row in observations} == {
            ApprovalStatus.PROVISIONAL
        }
        assert {row.observation_kind for row in observations} == {
            PriceObservationKind.PROVISIONAL
        }
        assert all(row.source_url_or_ref.startswith("https://") for row in observations)

        by_code = {
            item.canonical_code: item
            for item in session.scalars(
                select(OntologyItem).where(OntologyItem.canonical_code.in_(["LAB-0001", "LAB-0007"]))
            ).all()
        }
        mot = next(row for row in observations if row.ontology_item_id == by_code["LAB-0001"].id)
        alignment = next(
            row for row in observations if row.ontology_item_id == by_code["LAB-0007"].id
        )
        assert mot.price_net == "54.85"
        assert mot.original_price == "54.85"
        assert alignment.price_net == "62.50"
        assert alignment.original_price == "75.00"

        second = import_external_uk_benchmarks(
            session, SAMPLE_DATA / "uk_external_benchmarks.csv"
        )
        session.commit()
        assert second.imports_created == 0
        assert second.observations_created == 0
        assert second.rows_skipped == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(PriceObservation)
                .where(PriceObservation.source_type == "external_uk_public_research")
            )
            == 2
        )

        providers = list(
            session.scalars(
                select(SourceProvider).where(
                    SourceProvider.adapter_name
                    == "app.services.external_benchmark_import_service"
                )
            ).all()
        )
        assert len(providers) == 2
        assert all(provider.priority == 0 for provider in providers)
        assert all(provider.requires_human_approval for provider in providers)
        assert all(provider.configuration_json["challenge_rule_enabled"] is False for provider in providers)
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceImport)
                .where(SourceImport.provider_id.in_([provider.id for provider in providers]))
            )
            == 2
        )
