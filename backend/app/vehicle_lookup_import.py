"""Import the client-editable UK vehicle category catalogue."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.database import SessionLocal
from app.init_db import initialize_database
from app.services.vehicle_category_lookup import (
    DEFAULT_CATALOGUE_PATH,
    import_vehicle_category_lookup,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add or update ClaimGuard vehicle category lookup rows."
    )
    parser.add_argument(
        "catalogue",
        nargs="?",
        type=Path,
        default=DEFAULT_CATALOGUE_PATH,
        help="CSV path (defaults to sample-data/vehicle_category_lookup.csv).",
    )
    args = parser.parse_args()
    catalogue = args.catalogue.expanduser().resolve()
    if not catalogue.is_file():
        parser.error(f"catalogue not found: {catalogue}")

    initialize_database()
    with SessionLocal.begin() as session:
        created, updated = import_vehicle_category_lookup(session, catalogue)
    print(
        f"Vehicle lookup imported: {created} added, {updated} updated "
        f"from {catalogue}"
    )


if __name__ == "__main__":
    main()
