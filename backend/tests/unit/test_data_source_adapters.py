from __future__ import annotations

from pathlib import Path

import pytest

from app.data_sources.base import SourceAdapterRegistry
from app.data_sources.registry import get_source_adapter_registry
from app.importers.seed_workbooks import SeedWorkbookBundle


class EmptyAdapter:
    provider_key = "empty"

    def load(self, ontology_path: Path, historical_path: Path) -> SeedWorkbookBundle:
        return SeedWorkbookBundle((), (), (), ())


def test_registry_accepts_contract_compatible_replacement_adapter() -> None:
    registry = SourceAdapterRegistry()
    registry.register_seed(EmptyAdapter())
    assert registry.seed("empty").load(Path("ontology"), Path("history")) == SeedWorkbookBundle(
        (), (), (), ()
    )


def test_builtin_registry_declares_pilot_and_future_provider_boundaries() -> None:
    registry = get_source_adapter_registry()
    assert registry.keys() == (
        "audatex",
        "excel_seed",
        "gt_motive",
        "insurer_schedule",
        "tecalliance",
    )
    with pytest.raises(RuntimeError, match="not configured"):
        registry.seed("audatex").load(Path("ontology"), Path("history"))
