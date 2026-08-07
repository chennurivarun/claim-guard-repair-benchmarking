from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.init_db import initialize_database
from app.models import Vehicle, VehicleCategoryLookup
from app.services.vehicle_category_lookup import (
    apply_lookup_to_vehicle,
    import_vehicle_category_lookup,
    lookup_vehicle_category,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    return Session(engine)


def test_lookup_seeds_supplied_vehicle_groups_and_normalises_aliases() -> None:
    with _session() as session:
        assert session.scalar(select(VehicleCategoryLookup).where(
            VehicleCategoryLookup.make == "Ford",
            VehicleCategoryLookup.model == "Fiesta 1.0",
        ))
        match = lookup_vehicle_category(session, make="Ford", model="Fiesta 1.0 Zetec")

        assert match is not None
        assert match.group_range == "6-10"
        assert match.group_category == "Low"
        assert match.match_status == "model_family"

        adam = lookup_vehicle_category(session, make="Vauxhall", model="Adam Glam")
        assert adam is not None
        assert adam.group_range == "6-10"
        assert adam.match_status == "alias"


def test_lookup_keeps_unmatched_vehicle_for_manual_review() -> None:
    with _session() as session:
        vehicle = Vehicle(make="Unknown", model="Mystery", source="pytest")
        session.add(vehicle)
        apply_lookup_to_vehicle(session, vehicle)

        assert vehicle.insurance_group_range is None
        assert vehicle.insurance_group_match_status == "manual_review"


def test_lookup_prefers_specific_variant_over_generic_family() -> None:
    with _session() as session:
        match = lookup_vehicle_category(
            session,
            make="VW",
            model="Polo 1.0 TSI",
        )

        assert match is not None
        assert match.group_range == "11-15"
        assert match.matched_model == "Polo 1.0 TSI"


def test_lookup_matches_a_known_model_variant_inside_extracted_trim_text() -> None:
    with _session() as session:
        match = lookup_vehicle_category(
            session,
            make="BMW",
            model="320d Sport",
        )

        assert match is not None
        assert match.group_range == "26-30"
        assert match.matched_model == "3 Series"


def test_client_csv_import_adds_and_updates_without_duplicates(tmp_path) -> None:
    catalogue = tmp_path / "vehicles.csv"
    catalogue.write_text(
        "make,model,group_range,group_category,body_type,fuel_type,aliases,source\n"
        "Ford,Fiesta 1.0,7-10,Client Updated,Small car,Petrol,Fiesta|Fiesta Zetec,Client CSV\n"
        "Vauxhall,Mokka,16-20,Average,SUV,Petrol,Mokka X,Client CSV\n",
        encoding="utf-8",
    )
    with _session() as session:
        before = len(session.scalars(select(VehicleCategoryLookup)).all())
        created, updated = import_vehicle_category_lookup(session, catalogue)
        session.commit()

        assert (created, updated) == (1, 1)
        assert len(session.scalars(select(VehicleCategoryLookup)).all()) == before + 1
        fiesta = lookup_vehicle_category(session, make="Ford", model="Fiesta Zetec")
        mokka = lookup_vehicle_category(session, make="Vauxhall", model="Mokka X")
        assert fiesta is not None
        assert fiesta.group_category == "Client Updated"
        assert mokka is not None
        assert mokka.matched_model == "Mokka"
