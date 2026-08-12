"""Command-line entry point for the curated UK external benchmark staging file."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.database import SessionLocal
from app.init_db import initialize_database
from app.services.external_benchmark_import_service import import_external_uk_benchmarks


def main() -> None:
    initialize_database()
    path = Path(__file__).resolve().parents[2] / "sample-data" / "uk_external_benchmarks.csv"
    with SessionLocal() as session:
        result = import_external_uk_benchmarks(session, path)
        session.commit()
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
