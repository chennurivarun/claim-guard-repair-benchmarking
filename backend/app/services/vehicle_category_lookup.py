from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Vehicle, VehicleCategoryLookup

LOOKUP_SOURCE = "Client-provided UK insurance-group reference, 2026-07-30"
DEFAULT_CATALOGUE_PATH = (
    Path(__file__).resolve().parents[3]
    / "sample-data"
    / "vehicle_category_lookup.csv"
)

# The supplied reference is intentionally data, not branching application code.
# More catalogue rows can be added without changing the matching algorithm.
DEFAULT_VEHICLE_CATEGORIES = (
    ("Volkswagen", "Up", "1-5", "Cheapest", "City car", None, ["VW Up"]),
    ("Citroen", "C1", "1-5", "Cheapest", "City car", None, ["Citroën C1"]),
    ("Toyota", "Aygo", "1-5", "Cheapest", "City car", None, []),
    ("Kia", "Picanto", "1-5", "Cheapest", "City car", None, []),
    ("SEAT", "Ibiza 1.0", "1-5", "Cheapest", "Supermini", "Petrol", []),
    ("Hyundai", "i10", "1-5", "Cheapest", "City car", None, []),
    ("Ford", "Fiesta 1.0", "6-10", "Low", "Small car", "Petrol", ["Fiesta"]),
    (
        "Vauxhall",
        "Adam",
        "6-10",
        "Low",
        "Small car",
        "Petrol",
        ["Adam Jam", "Adam Glam"],
    ),
    ("Vauxhall", "Corsa", "6-10", "Low", "Small car", None, []),
    ("Honda", "Jazz", "6-10", "Low", "Small car", None, []),
    ("Mazda", "2", "6-10", "Low", "Small car", None, ["Mazda2"]),
    ("Hyundai", "i20", "6-10", "Low", "Small car", None, []),
    ("Volkswagen", "Polo", "6-10", "Low", "Small car", None, ["VW Polo"]),
    (
        "Volkswagen",
        "Polo 1.0 TSI",
        "11-15",
        "Below Average",
        "Family hatchback",
        "Petrol",
        ["VW Polo 1.0 TSI"],
    ),
    ("Skoda", "Octavia 1.0", "11-15", "Below Average", "Family car", "Petrol", []),
    ("Ford", "Focus 1.0", "11-15", "Below Average", "Family hatchback", "Petrol", []),
    ("Toyota", "Corolla", "16-20", "Average", "Family car", None, []),
    ("Honda", "Civic", "16-20", "Average", "Family car", None, []),
    ("Kia", "Sportage", "16-20", "Average", "SUV", None, []),
    ("Nissan", "Qashqai", "16-20", "Average", "SUV", None, []),
    ("BMW", "1 Series", "21-25", "Above Average", "Premium hatchback", None, []),
    ("Audi", "A3", "21-25", "Above Average", "Premium car", None, []),
    (
        "Volkswagen",
        "Golf GTD",
        "21-25",
        "Above Average",
        "Performance hatchback",
        "Diesel",
        ["VW Golf GTD"],
    ),
    ("Mazda", "CX-5", "21-25", "Above Average", "SUV", None, ["CX5"]),
    (
        "BMW",
        "3 Series",
        "26-30",
        "High",
        "Premium car",
        None,
        ["320d", "320d Sport"],
    ),
    ("Audi", "A4", "26-30", "High", "Premium car", None, []),
    ("Volkswagen", "Golf R", "26-30", "High", "Performance hatchback", "Petrol", []),
    ("Mercedes-Benz", "A-Class AMG", "26-30", "High", "Performance car", None, []),
    ("BMW", "M135i", "31-35", "Very High", "Performance hatchback", "Petrol", []),
    ("Audi", "S3", "31-35", "Very High", "Performance car", "Petrol", []),
    ("Mercedes-Benz", "C300", "31-35", "Very High", "Premium car", None, []),
    ("Tesla", "Model 3 LR", "31-35", "Very High", "Electric car", "Electric", []),
    ("BMW", "M3", "36-40", "Premium", "Performance car", "Petrol", []),
    ("Audi", "RS3", "36-40", "Premium", "Performance car", "Petrol", []),
    ("Porsche", "Boxster", "36-40", "Premium", "Sports car", "Petrol", []),
    ("Tesla", "Model S", "36-40", "Premium", "Electric car", "Electric", []),
    ("Porsche", "911", "41-45", "Luxury", "Sports car", "Petrol", []),
    ("BMW", "M5", "41-45", "Luxury", "Performance car", "Petrol", []),
    ("Mercedes-Benz", "AMG GT", "41-45", "Luxury", "Performance car", "Petrol", []),
    (
        "Land Rover",
        "Range Rover Sport SVR",
        "41-45",
        "Luxury",
        "Large SUV",
        "Petrol",
        ["Range Rover Sport SVR"],
    ),
    ("Ferrari", "*", "46-50", "Supercar", "Supercar", "Petrol", []),
    ("Lamborghini", "*", "46-50", "Supercar", "Supercar", "Petrol", []),
    ("McLaren", "*", "46-50", "Supercar", "Supercar", "Petrol", []),
    ("Rolls-Royce", "*", "46-50", "Supercar", "Luxury car", None, ["Rolls Royce"]),
    ("BMW", "X5", "31-40", "Premium", "Large SUV", None, []),
    ("Ford", "Transit", "LCV", "Light Commercial Vehicle", "Van", None, ["Transit 350"]),
)

MAKE_ALIASES = {
    "vw": "volkswagen",
    "merc": "mercedesbenz",
    "mercedes": "mercedesbenz",
    "range rover": "landrover",
    "rolls royce": "rollsroyce",
}


def normalise_vehicle_name(value: str | None) -> str:
    if (value or "").strip() == "*":
        return "*"
    normalised = re.sub(r"[^a-z0-9]+", "", (value or "").lower())
    return MAKE_ALIASES.get((value or "").strip().lower(), normalised)


def load_vehicle_category_catalogue(
    path: Path = DEFAULT_CATALOGUE_PATH,
) -> list[tuple[str, str, str, str, str | None, str | None, list[str], str]]:
    """Load the client-editable catalogue, with the bundled rows as a safe fallback."""

    if not path.exists():
        return [
            (*row, LOOKUP_SOURCE)
            for row in DEFAULT_VEHICLE_CATEGORIES
        ]
    required = {"make", "model", "group_range", "group_category"}
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"Vehicle catalogue is missing columns: {', '.join(sorted(missing))}"
            )
        for line_number, raw in enumerate(reader, start=2):
            make = (raw.get("make") or "").strip()
            model = (raw.get("model") or "").strip()
            group_range = (raw.get("group_range") or "").strip()
            group_category = (raw.get("group_category") or "").strip()
            if not all((make, model, group_range, group_category)):
                raise ValueError(
                    f"Vehicle catalogue row {line_number} needs make, model, "
                    "group_range and group_category."
                )
            rows.append(
                (
                    make,
                    model,
                    group_range,
                    group_category,
                    (raw.get("body_type") or "").strip() or None,
                    (raw.get("fuel_type") or "").strip() or None,
                    [
                        alias.strip()
                        for alias in (raw.get("aliases") or "").split("|")
                        if alias.strip()
                    ],
                    (raw.get("source") or "").strip() or LOOKUP_SOURCE,
                )
            )
    return rows


@dataclass(frozen=True, slots=True)
class VehicleCategoryMatch:
    group_range: str
    group_category: str
    body_type: str | None
    fuel_type: str | None
    source: str
    matched_make: str
    matched_model: str
    match_status: str


def import_vehicle_category_lookup(
    session: Session,
    path: Path = DEFAULT_CATALOGUE_PATH,
) -> tuple[int, int]:
    """Idempotently add or update catalogue rows using normalized make/model keys."""

    existing = {
        (row.normalised_make, row.normalised_model): row
        for row in session.scalars(select(VehicleCategoryLookup)).all()
    }
    created = 0
    updated = 0
    for make, model, group_range, category, body, fuel, aliases, source in (
        load_vehicle_category_catalogue(path)
    ):
        key = (normalise_vehicle_name(make), normalise_vehicle_name(model))
        row = existing.get(key)
        if row is not None:
            row.make = make
            row.model = model
            row.group_range = group_range
            row.group_category = category
            row.body_type = body
            row.fuel_type = fuel
            row.aliases_json = aliases
            row.source = source
            updated += 1
            continue
        row = VehicleCategoryLookup(
            make=make,
            model=model,
            normalised_make=key[0],
            normalised_model=key[1],
            group_range=group_range,
            group_category=category,
            body_type=body,
            fuel_type=fuel,
            aliases_json=aliases,
            source=source,
        )
        session.add(row)
        existing[key] = row
        created += 1
    session.flush()
    for vehicle in session.scalars(select(Vehicle)).all():
        apply_lookup_to_vehicle(session, vehicle)
    return created, updated


def seed_vehicle_category_lookup(session: Session) -> int:
    created, _ = import_vehicle_category_lookup(session)
    return created


def lookup_vehicle_category(
    session: Session,
    *,
    make: str | None,
    model: str | None,
) -> VehicleCategoryMatch | None:
    normalised_make = normalise_vehicle_name(make)
    normalised_model = normalise_vehicle_name(model)
    if not normalised_make or not normalised_model:
        return None
    rows = list(
        session.scalars(
            select(VehicleCategoryLookup).where(
                VehicleCategoryLookup.normalised_make == normalised_make
            )
        ).all()
    )
    candidates: list[tuple[int, VehicleCategoryLookup, str]] = []
    for row in rows:
        aliases = [normalise_vehicle_name(alias) for alias in (row.aliases_json or [])]
        if row.normalised_model == normalised_model:
            candidates.append((10_000 + len(row.normalised_model), row, "exact"))
        elif normalised_model in aliases:
            candidates.append((9_000 + len(normalised_model), row, "alias"))
        elif row.normalised_model == "*":
            candidates.append((1, row, "make_family"))
        elif row.normalised_model in normalised_model:
            candidates.append((len(row.normalised_model), row, "model_family"))
        elif matching_aliases := [
            alias for alias in aliases if alias and alias in normalised_model
        ]:
            longest_alias = max(matching_aliases, key=len)
            candidates.append((8_000 + len(longest_alias), row, "alias_family"))
    if not candidates:
        return None
    _, row, status = max(candidates, key=lambda candidate: candidate[0])
    return VehicleCategoryMatch(
        group_range=row.group_range,
        group_category=row.group_category,
        body_type=row.body_type,
        fuel_type=row.fuel_type,
        source=row.source,
        matched_make=row.make,
        matched_model=row.model,
        match_status=status,
    )


def apply_lookup_to_vehicle(
    session: Session,
    vehicle: Any,
) -> VehicleCategoryMatch | None:
    match = lookup_vehicle_category(session, make=vehicle.make, model=vehicle.model)
    if match is None:
        vehicle.insurance_group_match_status = "manual_review"
        return None
    vehicle.insurance_group_range = match.group_range
    vehicle.insurance_group_category = match.group_category
    vehicle.insurance_group_source = match.source
    vehicle.insurance_group_match_status = match.match_status
    if not vehicle.fuel_type and match.fuel_type:
        vehicle.fuel_type = match.fuel_type
    return match
