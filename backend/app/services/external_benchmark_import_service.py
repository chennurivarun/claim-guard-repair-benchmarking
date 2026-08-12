"""Import reviewed UK public benchmark observations into the governed price bank.

The importer deliberately stages rows as provisional market observations.  They
remain visible and traceable in the Ontology Bank, but cannot silently become a
runtime comparison rule until a human approves the source policy.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import (
    ApprovalStatus,
    ImportStatus,
    OntologyVersionStatus,
    PriceObservationKind,
    PriceScope,
    PriceVatBasis,
    SourceProviderType,
)
from app.models import (
    OntologyItem,
    OntologyVersion,
    PriceObservation,
    SourceImport,
    SourceProvider,
)

SCHEMA_VERSION = "uk-external-benchmark-v1"


@dataclass(frozen=True)
class ExternalBenchmarkImportResult:
    providers_created: int
    imports_created: int
    observations_created: int
    rows_skipped: int


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _active_version(session: Session) -> OntologyVersion:
    version = session.scalar(
        select(OntologyVersion)
        .where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
        .order_by(OntologyVersion.sequence_number.desc())
        .limit(1)
    )
    if version is None:
        raise RuntimeError("No published ontology version exists")
    return version


def _provider(session: Session, row: dict[str, str]) -> tuple[SourceProvider, bool]:
    name = row["provider_name"].strip()
    existing = session.scalar(select(SourceProvider).where(SourceProvider.name == name))
    if existing is not None:
        return existing, False
    provider = SourceProvider(
        name=name,
        provider_type=SourceProviderType.WEB,
        adapter_name="app.services.external_benchmark_import_service",
        enabled=True,
        priority=0,
        licence_status=row["licence_status"].strip(),
        permitted_use=row["permitted_use"].strip(),
        requires_human_approval=True,
        configuration_json={
            "schema_version": SCHEMA_VERSION,
            "runtime_priority_assigned": False,
            "challenge_rule_enabled": False,
        },
    )
    session.add(provider)
    session.flush()
    return provider, True


def _money(value: str) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def import_external_uk_benchmarks(
    session: Session, csv_path: str | Path
) -> ExternalBenchmarkImportResult:
    """Idempotently stage curated observations without committing the session."""

    path = Path(csv_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    required = {
        "source_record_id",
        "provider_name",
        "ontology_code",
        "price_net_gbp",
        "original_price_gbp",
        "vat_basis",
        "unit",
        "price_scope",
        "effective_from",
        "source_url",
        "licence_status",
        "permitted_use",
    }
    if not rows or not required.issubset(rows[0]):
        missing = sorted(required - set(rows[0] if rows else []))
        raise ValueError(f"External benchmark CSV is empty or missing columns: {missing}")

    version = _active_version(session)
    digest = _digest(path)
    providers_created = imports_created = observations_created = rows_skipped = 0

    for provider_name in sorted({row["provider_name"].strip() for row in rows}):
        provider_rows = [row for row in rows if row["provider_name"].strip() == provider_name]
        provider, created = _provider(session, provider_rows[0])
        providers_created += int(created)
        dataset_version = f"{SCHEMA_VERSION}:{provider_name}:sha256:{digest}"
        existing_import = session.scalar(
            select(SourceImport).where(
                SourceImport.provider_id == provider.id,
                SourceImport.dataset_version == dataset_version,
                SourceImport.status == ImportStatus.IMPORTED,
            )
        )
        if existing_import is not None:
            rows_skipped += len(provider_rows)
            continue

        resolved: list[tuple[dict[str, str], OntologyItem]] = []
        rejected = 0
        for row in provider_rows:
            item = session.scalar(
                select(OntologyItem).where(
                    OntologyItem.canonical_code == row["ontology_code"].strip()
                )
            )
            if item is None:
                rejected += 1
                continue
            resolved.append((row, item))

        source_import = SourceImport(
            provider_id=provider.id,
            dataset_version=dataset_version,
            row_count=len(provider_rows),
            accepted_count=len(resolved),
            rejected_count=rejected,
            quarantined_count=0,
            status=ImportStatus.IMPORTED,
            validation_report_json={
                "schema_version": SCHEMA_VERSION,
                "currency": "GBP",
                "region": "UK",
                "runtime_priority_assigned": False,
                "challenge_rule_enabled": False,
                "review_note": "Curated public observation; human source-policy approval required.",
            },
        )
        session.add(source_import)
        session.flush()
        imports_created += 1
        rows_skipped += rejected

        for row, item in resolved:
            session.add(
                PriceObservation(
                    ontology_item_id=item.id,
                    price_net=_money(row["price_net_gbp"]),
                    original_price=_money(row["original_price_gbp"]),
                    currency="GBP",
                    vat_basis=PriceVatBasis(row["vat_basis"].strip().lower()),
                    unit=row["unit"].strip(),
                    price_scope=PriceScope(row["price_scope"].strip().lower()),
                    source_provider_id=provider.id,
                    source_import_id=source_import.id,
                    source_type="external_uk_public_research",
                    source_record_id=row["source_record_id"].strip(),
                    source_url_or_ref=row["source_url"].strip(),
                    observed_at=datetime.now(UTC),
                    effective_from=date.fromisoformat(row["effective_from"].strip()),
                    region="UK",
                    quality_tier="official-public-source",
                    condition=row.get("vehicle_applicability", "").strip() or None,
                    approval_status=ApprovalStatus.PROVISIONAL,
                    observation_kind=PriceObservationKind.PROVISIONAL,
                    created_in_version_id=version.id,
                )
            )
            observations_created += 1

    session.flush()
    return ExternalBenchmarkImportResult(
        providers_created=providers_created,
        imports_created=imports_created,
        observations_created=observations_created,
        rows_skipped=rows_skipped,
    )
