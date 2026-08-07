from __future__ import annotations

from pathlib import Path

from app.importers.seed_workbooks import SeedWorkbookBundle, load_seed_workbooks


class ExcelSeedDataAdapter:
    """Pilot Excel adapter for ontology and historical invoice workbooks."""

    provider_key = "excel_seed"

    def load(self, ontology_path: Path, historical_path: Path) -> SeedWorkbookBundle:
        return load_seed_workbooks(ontology_path, historical_path)
