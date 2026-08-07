from __future__ import annotations

from functools import lru_cache

from app.data_sources.base import SourceAdapterRegistry
from app.data_sources.excel import ExcelSeedDataAdapter
from app.data_sources.future import (
    AudatexAdapter,
    GTMotiveAdapter,
    InsurerScheduleAdapter,
    TecAllianceAdapter,
)


@lru_cache(maxsize=1)
def get_source_adapter_registry() -> SourceAdapterRegistry:
    registry = SourceAdapterRegistry()
    for adapter in (
        ExcelSeedDataAdapter(),
        AudatexAdapter(),
        GTMotiveAdapter(),
        TecAllianceAdapter(),
        InsurerScheduleAdapter(),
    ):
        registry.register_seed(adapter)
    return registry
