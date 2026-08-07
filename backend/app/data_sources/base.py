from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.importers.seed_workbooks import SeedWorkbookBundle


@runtime_checkable
class SeedDataAdapter(Protocol):
    """Translate provider-specific files into ClaimGuard's canonical seed bundle."""

    provider_key: str

    def load(self, ontology_path: Path, historical_path: Path) -> SeedWorkbookBundle: ...


class SourceAdapterRegistry:
    """Explicit registry kept outside the deterministic comparison engine."""

    def __init__(self) -> None:
        self._seed_adapters: dict[str, SeedDataAdapter] = {}

    def register_seed(self, adapter: SeedDataAdapter) -> None:
        if not isinstance(adapter, SeedDataAdapter):
            raise TypeError("Adapter does not satisfy the SeedDataAdapter contract.")
        if not adapter.provider_key.strip():
            raise ValueError("Adapter provider_key is required.")
        self._seed_adapters[adapter.provider_key] = adapter

    def seed(self, provider_key: str) -> SeedDataAdapter:
        try:
            return self._seed_adapters[provider_key]
        except KeyError as exc:
            available = ", ".join(sorted(self._seed_adapters)) or "none"
            raise KeyError(
                f"Unknown seed adapter {provider_key!r}; available adapters: {available}."
            ) from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._seed_adapters))
