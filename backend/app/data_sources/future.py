from __future__ import annotations

from pathlib import Path

from app.importers.seed_workbooks import SeedWorkbookBundle


class UnconfiguredProviderAdapter:
    """Contract-valid placeholder for a provider not configured in the pilot."""

    provider_key = "unconfigured"

    def load(self, ontology_path: Path, historical_path: Path) -> SeedWorkbookBundle:
        raise RuntimeError(
            f"Provider adapter {self.provider_key!r} is not configured for this pilot."
        )


class AudatexAdapter(UnconfiguredProviderAdapter):
    provider_key = "audatex"


class GTMotiveAdapter(UnconfiguredProviderAdapter):
    provider_key = "gt_motive"


class TecAllianceAdapter(UnconfiguredProviderAdapter):
    provider_key = "tecalliance"


class InsurerScheduleAdapter(UnconfiguredProviderAdapter):
    provider_key = "insurer_schedule"
