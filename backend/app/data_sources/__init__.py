"""Provider-neutral source adapter contracts and built-in implementations."""

from app.data_sources.base import SeedDataAdapter, SourceAdapterRegistry
from app.data_sources.registry import get_source_adapter_registry

__all__ = ["SeedDataAdapter", "SourceAdapterRegistry", "get_source_adapter_registry"]
