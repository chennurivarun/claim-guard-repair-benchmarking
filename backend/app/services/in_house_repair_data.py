from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

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
from app.models import (
    HistoricalObservation,
    Invoice,
    OntologyItem,
    SourceImport,
    SourceProvider,
)

PROVIDER_NAME = "ClaimGuard synthetic in-house repair data"
SAMPLES_PER_COMBINATION = 3


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
            "columns": [
                "ontology_item",
                "vehicle_make",
                "vehicle_model",
                "repair_invoice_date",
                "amount_net",
            ],
        },
    )
    session.add(provider)
    session.flush()
    return provider


def _base_price(item: OntologyItem) -> Decimal:
    if item.reference_price_net and Decimal(str(item.reference_price_net)) > 0:
        return Decimal(str(item.reference_price_net))
    digest = hashlib.sha256(item.canonical_code.encode()).hexdigest()
    return Decimal(40 + int(digest[:8], 16) % 261)


def _source_record_id(item: OntologyItem, make: str, model: str, sample: int) -> str:
    raw_value = f"synthetic:{item.canonical_code}:{make}:{model}:{sample}"
    if len(raw_value) <= 200:
        return raw_value
    digest = hashlib.sha256(raw_value.encode()).hexdigest()[:20]
    return f"{raw_value[:178]}:{digest}"


def ensure_synthetic_in_house_data(
    session: Session,
    *,
    invoices: list[Invoice],
    ontology_items: list[OntologyItem],
) -> int:
    """Create deterministic, traceable demo CSV-equivalent rows for current coverage."""

    vehicles = sorted(
        {
            (invoice.vehicle.make.strip(), invoice.vehicle.model.strip())
            for invoice in invoices
            if invoice.vehicle and invoice.vehicle.make and invoice.vehicle.model
        }
    )
    if not vehicles or not ontology_items:
        return 0
    signature = "|".join(
        [
            *(item.id for item in ontology_items),
            *(f"{make}:{model}" for make, model in vehicles),
        ]
    )
    dataset_version = f"synthetic-in-house-v1-{hashlib.sha256(signature.encode()).hexdigest()[:16]}"
    provider = _provider(session)
    existing = session.scalar(
        select(SourceImport).where(
            SourceImport.provider_id == provider.id,
            SourceImport.dataset_version == dataset_version,
        )
    )
    if existing:
        # v1 datasets created before the three-source policy was finalised were
        # deliberately marked display-only. Promote those same governed rows
        # in place so an existing deployment does not keep showing an in-house
        # P90 that the challenge calculation silently ignores.
        existing_rows = session.scalars(
            select(HistoricalObservation).where(
                HistoricalObservation.source_import_id == existing.id
            )
        ).all()
        for row in existing_rows:
            metadata = dict(row.comparability_metadata_json or {})
            if metadata.get("eligible_for_price_decision") is not True:
                metadata["eligible_for_price_decision"] = True
                row.comparability_metadata_json = metadata
        session.flush()
        return 0

    row_count = len(ontology_items) * len(vehicles) * SAMPLES_PER_COMBINATION
    source_import = SourceImport(
        provider_id=provider.id,
        dataset_version=dataset_version,
        row_count=row_count,
        accepted_count=row_count,
        rejected_count=0,
        quarantined_count=0,
        validation_report_json={
            "synthetic": True,
            "source_group": "in_house",
            "ontology_items": len(ontology_items),
            "vehicle_make_models": len(vehicles),
            "samples_per_combination": SAMPLES_PER_COMBINATION,
        },
        status=ImportStatus.IMPORTED,
    )
    session.add(source_import)
    session.flush()

    as_of = max(
        (invoice.invoice_date for invoice in invoices if invoice.invoice_date),
        default=date.today(),
    )
    factors = (Decimal("0.90"), Decimal("1.00"), Decimal("1.10"))
    for item in ontology_items:
        base = _base_price(item)
        for make, model in vehicles:
            for sample_index, factor in enumerate(factors, start=1):
                amount = (base * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
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
                            "eligible_for_price_decision": True,
                            "invoice_number": source_record_id,
                            "garage_name": "Synthetic in-house garage",
                            "classification_status": "exact_make_model",
                        },
                    )
                )
    session.flush()
    return row_count


def synthetic_in_house_csv(session: Session) -> str:
    provider = session.scalar(select(SourceProvider).where(SourceProvider.name == PROVIDER_NAME))
    if not provider:
        return "ontology_item,vehicle_make,vehicle_model,repair_invoice_date,amount_net\n"
    import_ids = session.scalars(
        select(SourceImport.id).where(SourceImport.provider_id == provider.id)
    ).all()
    rows = session.scalars(
        select(HistoricalObservation)
        .where(HistoricalObservation.source_import_id.in_(import_ids))
        .order_by(
            HistoricalObservation.raw_description,
            HistoricalObservation.vehicle_make,
            HistoricalObservation.vehicle_model,
            HistoricalObservation.invoice_date,
        )
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ontology_item",
            "vehicle_make",
            "vehicle_model",
            "repair_invoice_date",
            "amount_net",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.raw_description,
                row.vehicle_make,
                row.vehicle_model,
                row.invoice_date.isoformat() if row.invoice_date else "",
                row.line_total_net,
            ]
        )
    return output.getvalue()
