from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import (
    ApprovalStatus,
    ImportStatus,
    InvoiceDocumentRole,
    PriceScope,
    PriceVatBasis,
    SettlementStatus,
    SourceProviderType,
)
from app.llm.base import LLMProviderError, StructuredLLMClient
from app.models import (
    HistoricalObservation,
    Invoice,
    OntologyItem,
    SourceImport,
    SourceProvider,
)

PROVIDER_NAME = "ClaimGuard synthetic in-house repair data"
DATASET_SCHEMA_VERSION = "v4"
SAMPLES_PER_COMBINATION = 6
LLM_BATCH_SIZE = 40
SYNTHETIC_VEHICLE_MIX = (
    ("Audi", "A4"),
    ("BMW", "3 Series"),
    ("Ford", "Focus"),
    ("Honda", "Civic"),
    ("Toyota", "Corolla"),
    ("Volkswagen", "Golf"),
)
FALLBACK_SAMPLE_FACTORS = (
    Decimal("0.82"),
    Decimal("0.91"),
    Decimal("0.98"),
    Decimal("1.04"),
    Decimal("1.11"),
    Decimal("1.19"),
)
CSV_COLUMNS = (
    "repair_part",
    "billed_amount",
    "vehicle_make",
    "vehicle_model",
    "repair_invoice_date",
)


def _eligible_for_in_house_pricing(item: OntologyItem) -> bool:
    """Keep governed seed coverage usable while excluding new proposals."""

    return item.approval_status == ApprovalStatus.APPROVED or item.created_by.startswith(
        ("seed-import:", "system-bootstrap")
    )


def _provider(session: Session) -> SourceProvider:
    existing = session.scalar(select(SourceProvider).where(SourceProvider.name == PROVIDER_NAME))
    if existing:
        return existing
    provider = SourceProvider(
        name=PROVIDER_NAME,
        provider_type=SourceProviderType.CSV,
        adapter_name="app.services.in_house_repair_data",
        enabled=True,
        priority=90,
        licence_status="Synthetic demonstration data",
        permitted_use="ClaimGuard benchmark demonstrations only; not production evidence.",
        requires_human_approval=False,
        configuration_json={
            "source_group": "in_house",
            "synthetic": True,
            "columns": list(CSV_COLUMNS),
        },
    )
    session.add(provider)
    session.flush()
    return provider


def _base_price(item: OntologyItem) -> Decimal:
    """Return an independent, deterministic synthetic price for a repair item.

    The in-house repair book must be an independent evidence source, so this
    deliberately does not use the item's external reference price.
    """

    digest = hashlib.sha256(item.canonical_code.encode()).hexdigest()
    return Decimal(40 + int(digest[:8], 16) % 261)


def _source_record_id(item: OntologyItem, make: str, model: str, sample: int) -> str:
    raw_value = f"synthetic:{item.canonical_code}:{make}:{model}:{sample}"
    if len(raw_value) <= 200:
        return raw_value
    digest = hashlib.sha256(raw_value.encode()).hexdigest()[:20]
    return f"{raw_value[:178]}:{digest}"


def _vehicle_mix(invoices: list[Invoice]) -> tuple[tuple[str, str], ...]:
    """Return six distinct synthetic vehicle examples, preferring uploaded vehicles."""

    candidates = [
        *(
            (invoice.vehicle.make.strip(), invoice.vehicle.model.strip())
            for invoice in invoices
            if invoice.vehicle and invoice.vehicle.make and invoice.vehicle.model
        ),
        *SYNTHETIC_VEHICLE_MIX,
    ]
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for make, model in candidates:
        key = (make.casefold(), model.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append((make, model))
        if len(unique) == SAMPLES_PER_COMBINATION:
            break
    return tuple(unique)


def _llm_seed_prices(
    client: StructuredLLMClient | None,
    *,
    invoices: list[Invoice],
    ontology_items: list[OntologyItem],
) -> tuple[dict[str, tuple[Decimal, ...]], dict[str, Any]]:
    """Ask the configured model for six independent synthetic prices per item.

    Model output is schema-constrained, allow-listed to supplied repair-item codes,
    range-checked, and never allowed to interrupt comparison. Any missing or invalid
    value receives the deterministic fallback so offline deployments still work.
    """

    fallback = {
        item.canonical_code: tuple(
            (_base_price(item) * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for factor in FALLBACK_SAMPLE_FACTORS
        )
        for item in ontology_items
    }
    if client is None:
        return fallback, {
            "generation_method": "deterministic_fallback",
            "llm_generated_items": 0,
            "fallback_items": len(ontology_items),
        }

    observed_invoice_parts = sorted(
        {
            line.raw_description.strip()
            for invoice in invoices
            for line in getattr(invoice, "line_items", [])
            if line.raw_description and line.raw_description.strip()
        }
    )[:250]
    generated: dict[str, tuple[Decimal, ...]] = {}
    errors: list[str] = []
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "prices": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "repair_item_code": {"type": "string"},
                        "sample_net_prices": {
                            "type": "array",
                            "items": {"type": "number", "minimum": 1, "maximum": 10000},
                            "minItems": SAMPLES_PER_COMBINATION,
                            "maxItems": SAMPLES_PER_COMBINATION,
                        },
                    },
                    "required": ["repair_item_code", "sample_net_prices"],
                },
            }
        },
        "required": ["prices"],
    }
    for start in range(0, len(ontology_items), LLM_BATCH_SIZE):
        batch = ontology_items[start : start + LLM_BATCH_SIZE]
        allowed = {item.canonical_code for item in batch}
        try:
            raw = client.complete_json(
                system_instruction=(
                    "Create a synthetic UK in-house motor-repair price dataset for demonstration. "
                    "Return exactly six different realistic NET GBP prices for every supplied "
                    "repair item, representing plausible in-house invoices on different dates. "
                    "Use general automotive knowledge and the supplied invoice-part context only; "
                    "do not copy any external-reference or uploaded billed price. Return only the "
                    "schema-constrained JSON and never invent repair-item codes."
                ),
                payload={
                    "repair_items": [
                        {
                            "repair_item_code": item.canonical_code,
                            "repair_part": item.canonical_name,
                            "unit": item.unit,
                        }
                        for item in batch
                    ],
                    "observed_invoice_parts": observed_invoice_parts,
                    "currency": "GBP",
                    "vat_basis": "NET",
                    "purpose": "synthetic demonstration benchmark only",
                },
                schema=schema,
            )
            for row in raw.get("prices", []):
                code = str(row.get("repair_item_code") or "")
                amounts = tuple(
                    Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    for value in row.get("sample_net_prices", [])
                )
                if (
                    code in allowed
                    and len(amounts) == SAMPLES_PER_COMBINATION
                    and len(set(amounts)) == SAMPLES_PER_COMBINATION
                    and all(Decimal("1") <= amount <= Decimal("10000") for amount in amounts)
                ):
                    generated[code] = amounts
        except (LLMProviderError, ValueError, TypeError, ArithmeticError) as exc:
            errors.append(type(exc).__name__)

    prices = {**fallback, **generated}
    return prices, {
        "generation_method": (
            "llm_generated" if len(generated) == len(ontology_items) else "llm_with_fallback"
        ),
        "llm_provider": getattr(client, "provider", "configured_llm"),
        "llm_model": getattr(client, "model_id", "configured_model"),
        "llm_generated_items": len(generated),
        "fallback_items": len(ontology_items) - len(generated),
        "generation_errors": errors,
    }


def ensure_synthetic_in_house_data(
    session: Session,
    *,
    invoices: list[Invoice],
    ontology_items: list[OntologyItem],
    llm_client: StructuredLLMClient | None = None,
) -> int:
    """Create traceable LLM-seeded synthetic rows for current repair-item coverage."""

    vehicles = _vehicle_mix(invoices)
    if not ontology_items:
        return 0
    eligible_item_ids = {item.id for item in ontology_items if _eligible_for_in_house_pricing(item)}
    generator_key = (
        f"{getattr(llm_client, 'provider', 'fallback')}:"
        f"{getattr(llm_client, 'model_id', 'deterministic')}"
    )
    signature = "|".join(
        [
            *(f"{item.id}:{item.approval_status.value}" for item in ontology_items),
            *(f"{make}:{model}" for make, model in vehicles),
            generator_key,
        ]
    )
    dataset_version = (
        f"synthetic-in-house-{DATASET_SCHEMA_VERSION}-"
        f"{hashlib.sha256(signature.encode()).hexdigest()[:16]}"
    )
    provider = _provider(session)
    existing = session.scalar(
        select(SourceImport).where(
            SourceImport.provider_id == provider.id,
            SourceImport.dataset_version == dataset_version,
        )
    )
    if existing:
        all_imports = session.scalars(
            select(SourceImport).where(SourceImport.provider_id == provider.id)
        ).all()
        other_import_ids = [row.id for row in all_imports if row.id != existing.id]
        if other_import_ids:
            other_rows = session.scalars(
                select(HistoricalObservation).where(
                    HistoricalObservation.source_import_id.in_(other_import_ids)
                )
            ).all()
            for row in other_rows:
                metadata = dict(row.comparability_metadata_json or {})
                metadata["active_dataset"] = False
                metadata["eligible_for_price_decision"] = False
                row.comparability_metadata_json = metadata
        for source_import in all_imports:
            report = dict(source_import.validation_report_json or {})
            report["active_dataset"] = source_import.id == existing.id
            source_import.validation_report_json = report
        existing_rows = session.scalars(
            select(HistoricalObservation).where(
                HistoricalObservation.source_import_id == existing.id
            )
        ).all()
        for row in existing_rows:
            metadata = dict(row.comparability_metadata_json or {})
            if metadata.get("active_dataset") is not True:
                metadata["active_dataset"] = True
            metadata["eligible_for_price_decision"] = row.ontology_item_id in eligible_item_ids
            row.comparability_metadata_json = metadata
        session.flush()
        return 0

    # A changed item/vehicle coverage signature creates one replacement
    # snapshot. Older snapshots remain auditable but are excluded from current
    # benchmarks and from the downloadable CSV.
    prior_imports = session.scalars(
        select(SourceImport).where(SourceImport.provider_id == provider.id)
    ).all()
    prior_import_ids = [source_import.id for source_import in prior_imports]
    if prior_import_ids:
        prior_rows = session.scalars(
            select(HistoricalObservation).where(
                HistoricalObservation.source_import_id.in_(prior_import_ids)
            )
        ).all()
        for row in prior_rows:
            metadata = dict(row.comparability_metadata_json or {})
            metadata["active_dataset"] = False
            metadata["eligible_for_price_decision"] = False
            row.comparability_metadata_json = metadata
        for source_import in prior_imports:
            report = dict(source_import.validation_report_json or {})
            report["active_dataset"] = False
            source_import.validation_report_json = report

    base_prices, generation_report = _llm_seed_prices(
        llm_client,
        invoices=invoices,
        ontology_items=ontology_items,
    )
    row_count = len(ontology_items) * SAMPLES_PER_COMBINATION
    source_import = SourceImport(
        provider_id=provider.id,
        dataset_version=dataset_version,
        row_count=row_count,
        accepted_count=row_count,
        rejected_count=0,
        quarantined_count=0,
        validation_report_json={
            "synthetic": True,
            "active_dataset": True,
            "schema_version": DATASET_SCHEMA_VERSION,
            "source_group": "in_house",
            "ontology_items": len(ontology_items),
            "vehicle_make_models": len(vehicles),
            "samples_per_repair_item": SAMPLES_PER_COMBINATION,
            **generation_report,
        },
        status=ImportStatus.IMPORTED,
    )
    session.add(source_import)
    session.flush()

    as_of = max(
        (invoice.invoice_date for invoice in invoices if invoice.invoice_date),
        default=date.today(),
    )
    for item in ontology_items:
        for sample_index, sample_price in enumerate(base_prices[item.canonical_code], start=1):
            make, model = vehicles[sample_index - 1]
            vehicle_digest = hashlib.sha256(f"{make}:{model}".casefold().encode()).hexdigest()
            vehicle_adjustment = Decimal(85 + int(vehicle_digest[:8], 16) % 31) / Decimal("100")
            amount = (sample_price * vehicle_adjustment).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            observed_on = as_of - timedelta(days=sample_index * 90)
            source_record_id = _source_record_id(item, make, model, sample_index)
            session.add(
                HistoricalObservation(
                    source_import_id=source_import.id,
                    source_record_id=source_record_id,
                    observation_type=InvoiceDocumentRole.INVOICE,
                    invoice_date=observed_on,
                    ontology_item_id=item.id,
                    part_number=item.manufacturer_part_number,
                    raw_description=item.canonical_name,
                    vehicle_make=make,
                    vehicle_model=model,
                    region=item.region or "UK",
                    quantity="1",
                    unit=item.unit,
                    price_scope=PriceScope.LINE_TOTAL,
                    unit_price_net=str(amount),
                    line_total_net=str(amount),
                    approved_amount_net=str(amount),
                    settled_amount_net=str(amount),
                    vat_basis=PriceVatBasis.NET,
                    settlement_status=SettlementStatus.SETTLED,
                    approval_status=ApprovalStatus.APPROVED,
                    comparability_metadata_json={
                        "source": PROVIDER_NAME,
                        "source_group": "in_house",
                        "dataset_role": "in_house_repair_book",
                        "synthetic": True,
                        "active_dataset": True,
                        "eligible_for_price_decision": item.id in eligible_item_ids,
                        "invoice_number": source_record_id,
                        "garage_name": "Synthetic in-house garage",
                        "classification_status": "mixed_vehicle_sample",
                        "generation_method": generation_report["generation_method"],
                        "llm_model": generation_report.get("llm_model"),
                    },
                )
            )
    session.flush()
    return row_count


def synthetic_in_house_csv(session: Session) -> str:
    provider = session.scalar(select(SourceProvider).where(SourceProvider.name == PROVIDER_NAME))
    if not provider:
        return ",".join(CSV_COLUMNS) + "\n"
    imports = session.scalars(
        select(SourceImport)
        .where(SourceImport.provider_id == provider.id)
        .order_by(SourceImport.created_at.desc())
    ).all()
    active_import = next(
        (
            source_import
            for source_import in imports
            if (source_import.validation_report_json or {}).get("active_dataset") is True
        ),
        imports[0] if imports else None,
    )
    if not active_import:
        return ",".join(CSV_COLUMNS) + "\n"
    rows = session.scalars(
        select(HistoricalObservation)
        .where(HistoricalObservation.source_import_id == active_import.id)
        .order_by(
            HistoricalObservation.raw_description,
            HistoricalObservation.vehicle_make,
            HistoricalObservation.vehicle_model,
            HistoricalObservation.invoice_date,
        )
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.raw_description,
                row.line_total_net,
                row.vehicle_make,
                row.vehicle_model,
                row.invoice_date.isoformat() if row.invoice_date else "",
            ]
        )
    return output.getvalue()
