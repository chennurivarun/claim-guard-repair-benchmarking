"""Governed, replay-safe persistence for the supplied pilot seed workbooks.

The workbook parser deliberately exposes ``current_test_invoices`` as acceptance
gold.  This service records that sheet in source-import metadata but never writes
its rows to ``historical_observations``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_sources.base import SeedDataAdapter
from app.data_sources.registry import get_source_adapter_registry
from app.domain.normalisation import normalise_description
from app.enums import (
    ApprovalStatus,
    ConfidenceLevel,
    ImportStatus,
    InvoiceDocumentRole,
    LineItemKind,
    OntologyItemStatus,
    OntologyVersionStatus,
    PriceObservationKind,
    PriceScope,
    PriceVatBasis,
    SettlementStatus,
    SourceProviderType,
)
from app.importers.seed_workbooks import (
    HistoricalSeedRecord,
    OntologySeedRecord,
    SeedWorkbookBundle,
)
from app.models import (
    HistoricalObservation,
    OntologyItem,
    OntologySynonym,
    OntologyVersion,
    PriceObservation,
    SourceImport,
    SourceProvider,
    VehicleApplicability,
)
from app.services.vehicle_classification import validate_vehicle_classification

SEED_PROVIDER_NAME = "ClaimGuard supplied seed workbooks"
SEED_SCHEMA_VERSION = "seed-workbook-v1"


@dataclass(frozen=True)
class SeedImportResult:
    """Stable identifiers plus per-call insert counts for one seed import."""

    provider_id: str
    ontology_import_id: str
    history_import_id: str
    ontology_version_id: str
    ontology_items_created: int
    price_observations_created: int
    historical_observations_created: int
    acceptance_gold_excluded: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_version(role: str, digest: str) -> str:
    return f"{role}:{SEED_SCHEMA_VERSION}:sha256:{digest}"


def _active_ontology_version(session: Session) -> OntologyVersion:
    version = session.scalar(
        select(OntologyVersion)
        .where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
        .order_by(OntologyVersion.sequence_number.desc())
        .limit(1)
    )
    if version is None:
        raise RuntimeError("No published ontology version exists; call initialize_database first")
    return version


def _get_or_create_provider(session: Session) -> SourceProvider:
    provider = session.scalar(
        select(SourceProvider).where(SourceProvider.name == SEED_PROVIDER_NAME)
    )
    if provider is not None:
        return provider

    provider = SourceProvider(
        name=SEED_PROVIDER_NAME,
        provider_type=SourceProviderType.EXCEL,
        adapter_name="app.importers.seed_workbooks",
        enabled=True,
        priority=100,
        licence_status="User-supplied pilot data",
        permitted_use=(
            "Pilot ontology seeding and previous repair & service invoice comparison evidence."
        ),
        requires_human_approval=True,
        configuration_json={
            "schema_version": SEED_SCHEMA_VERSION,
            "ontology_sheet": "ontology_items",
            "runtime_history_sheet": "claims_line_items",
            "acceptance_only_sheet": "current_test_invoices",
        },
    )
    session.add(provider)
    session.flush()
    return provider


def _find_source_import(
    session: Session,
    *,
    provider_id: str,
    dataset_version: str,
) -> SourceImport | None:
    return session.scalar(
        select(SourceImport)
        .where(
            SourceImport.provider_id == provider_id,
            SourceImport.dataset_version == dataset_version,
            SourceImport.status == ImportStatus.IMPORTED,
        )
        .order_by(SourceImport.created_at.asc())
        .limit(1)
    )


def _line_item_kind(value: str) -> LineItemKind:
    normalised = value.strip().lower()
    if normalised == "rate":
        # The persistence model represents a labour-rate reference as labour
        # with an hourly price scope; the original workbook type is retained in
        # source metadata.
        return LineItemKind.LABOUR
    try:
        return LineItemKind(normalised)
    except ValueError as exc:
        raise ValueError(f"Unsupported ontology item type: {value!r}") from exc


def _confidence(value: str | None) -> ConfidenceLevel:
    normalised = (value or "low").strip().lower()
    if normalised.startswith("none"):
        return ConfidenceLevel.LOW
    try:
        return ConfidenceLevel(normalised)
    except ValueError as exc:
        raise ValueError(f"Unsupported confidence level: {value!r}") from exc


def _vat_basis(value: str) -> PriceVatBasis:
    try:
        return PriceVatBasis(value.strip().lower())
    except ValueError as exc:
        raise ValueError(f"Unsupported VAT basis: {value!r}") from exc


def _description(record: OntologySeedRecord) -> str | None:
    details: list[str] = []
    if record.notes:
        details.append(record.notes)
    if record.part_number_examples:
        details.append("Part number examples: " + "; ".join(record.part_number_examples))
    return "\n".join(details) or None


def _vehicle_hint(note: str) -> tuple[str | None, str | None, str | None]:
    """Extract only unambiguous make/model hints while retaining the full note."""

    lowered = note.lower()
    if lowered.startswith("mini countryman"):
        return "MINI", "Countryman", note
    if lowered.startswith("mini"):
        return "MINI", None, note
    if lowered.startswith("skoda octavia"):
        return "Skoda", "Octavia", note
    if lowered.startswith("range rover"):
        return "Land Rover", "Range Rover", note
    if lowered.startswith("vauxhall adam"):
        return "Vauxhall", "Adam", note
    return None, None, note


def _new_source_import(
    session: Session,
    *,
    provider: SourceProvider,
    dataset_version: str,
    row_count: int,
    validation_report: dict[str, object],
) -> SourceImport:
    source_import = SourceImport(
        provider_id=provider.id,
        dataset_version=dataset_version,
        row_count=row_count,
        accepted_count=row_count,
        rejected_count=0,
        quarantined_count=0,
        validation_report_json=validation_report,
        status=ImportStatus.IMPORTED,
    )
    session.add(source_import)
    session.flush()
    return source_import


def _persist_ontology(
    session: Session,
    *,
    records: tuple[OntologySeedRecord, ...],
    provider: SourceProvider,
    active_version: OntologyVersion,
    source_path: Path,
    file_digest: str,
) -> tuple[SourceImport, int, int]:
    version = _dataset_version("ontology", file_digest)
    existing_import = _find_source_import(session, provider_id=provider.id, dataset_version=version)
    if existing_import is not None:
        return existing_import, 0, 0

    priced_count = sum(record.reference_price_net is not None for record in records)
    source_import = _new_source_import(
        session,
        provider=provider,
        dataset_version=version,
        row_count=len(records),
        validation_report={
            "schema_version": SEED_SCHEMA_VERSION,
            "dataset_role": "ontology",
            "source_filename": source_path.name,
            "sha256": file_digest,
            "sheet_counts": {"ontology_items": len(records)},
            "active_ontology_version": {
                "id": active_version.id,
                "label": active_version.label,
                "sequence_number": active_version.sequence_number,
            },
            "priced_item_count": priced_count,
            "missing_price_count": len(records) - priced_count,
            "approval_status": ApprovalStatus.PROVISIONAL.value,
        },
    )

    canonical_codes = [record.ontology_id for record in records]
    existing_codes = set(
        session.scalars(
            select(OntologyItem.canonical_code).where(
                OntologyItem.canonical_code.in_(canonical_codes)
            )
        ).all()
    )
    if existing_codes:
        duplicates = ", ".join(sorted(existing_codes))
        raise ValueError(
            f"Ontology canonical codes already exist under a different source version: {duplicates}"
        )

    items_by_code: dict[str, OntologyItem] = {}
    for record in records:
        if record.approval_status.strip().lower() != ApprovalStatus.PROVISIONAL.value:
            raise ValueError(f"Seed ontology item {record.ontology_id} must remain provisional")

        source_reference = (
            f"{source_path.name}#ontology_items:{record.ontology_id}@sha256:{file_digest}"
        )
        part_number = (
            record.part_number_examples[0] if len(record.part_number_examples) == 1 else None
        )
        item = OntologyItem(
            canonical_code=record.ontology_id,
            canonical_name=record.canonical_name,
            item_type=_line_item_kind(record.item_type),
            category=record.category,
            unit=record.unit,
            manufacturer_part_number=part_number,
            part_grade=record.part_grade,
            description=_description(record),
            region=record.region or "UK",
            reference_price_net=record.reference_price_net,
            price_vat_basis=_vat_basis(record.price_vat_basis),
            currency=record.currency,
            price_source=record.price_source,
            source_url_or_ref=source_reference,
            effective_date=record.effective_date,
            status=OntologyItemStatus.PROVISIONAL,
            approval_status=ApprovalStatus.PROVISIONAL,
            confidence_level=_confidence(record.confidence_level),
            created_by=f"seed-import:{source_import.id}",
            created_in_version_id=active_version.id,
        )
        session.add(item)
        items_by_code[record.ontology_id] = item

    session.flush()

    price_observations_created = 0
    for record in records:
        item = items_by_code[record.ontology_id]
        source_reference = (
            f"{source_path.name}#ontology_items:{record.ontology_id}@sha256:{file_digest}"
        )
        seen_synonyms: set[str] = set()
        for synonym in record.synonyms:
            normalised = normalise_description(synonym)
            if not normalised or normalised in seen_synonyms:
                continue
            seen_synonyms.add(normalised)
            session.add(
                OntologySynonym(
                    ontology_item_id=item.id,
                    synonym=synonym,
                    normalised_synonym=normalised,
                    source_type="supplied_ontology_workbook",
                    source_reference=source_reference,
                    approval_status=ApprovalStatus.PROVISIONAL,
                    created_in_version_id=active_version.id,
                )
            )

        if record.vehicle_applicability:
            make, model, note = _vehicle_hint(record.vehicle_applicability)
            session.add(
                VehicleApplicability(
                    ontology_item_id=item.id,
                    make=make,
                    model=model,
                    source_reference=f"{source_reference}: {note}",
                    approval_status=ApprovalStatus.PROVISIONAL,
                )
            )

        if record.reference_price_net is None:
            continue
        if record.effective_date is None:
            raise ValueError(f"Priced ontology item {record.ontology_id} lacks an effective date")
        session.add(
            PriceObservation(
                ontology_item_id=item.id,
                price_net=record.reference_price_net,
                original_price=record.reference_price_net,
                currency=record.currency,
                vat_basis=_vat_basis(record.price_vat_basis),
                unit=record.unit,
                price_scope=(PriceScope.HOURLY if record.unit == "hour" else PriceScope.UNIT),
                source_provider_id=provider.id,
                source_import_id=source_import.id,
                source_type="supplied_ontology_workbook",
                source_record_id=record.ontology_id,
                source_url_or_ref=f"{source_reference}; {record.price_source}",
                effective_from=record.effective_date,
                region=record.region or "UK",
                condition=record.part_grade,
                approval_status=ApprovalStatus.PROVISIONAL,
                observation_kind=PriceObservationKind.PROVISIONAL,
                created_in_version_id=active_version.id,
            )
        )
        price_observations_created += 1

    session.flush()
    return source_import, len(records), price_observations_created


def _persist_history(
    session: Session,
    *,
    bundle: SeedWorkbookBundle,
    provider: SourceProvider,
    active_version: OntologyVersion,
    source_path: Path,
    file_digest: str,
) -> tuple[SourceImport, int]:
    version = _dataset_version("history", file_digest)
    existing_import = _find_source_import(session, provider_id=provider.id, dataset_version=version)
    if existing_import is not None:
        return existing_import, 0

    invoice_count = sum(
        record.document_role == InvoiceDocumentRole.INVOICE.value
        for record in bundle.runtime_history
    )
    estimate_count = sum(
        record.document_role == InvoiceDocumentRole.ESTIMATE.value
        for record in bundle.runtime_history
    )
    acceptance_invoice_numbers = sorted(
        {record.invoice_number for record in bundle.acceptance_gold}
    )
    source_import = _new_source_import(
        session,
        provider=provider,
        dataset_version=version,
        row_count=len(bundle.runtime_history),
        validation_report={
            "schema_version": SEED_SCHEMA_VERSION,
            "dataset_role": "previous_repair_and_service_invoices",
            "source_filename": source_path.name,
            "sha256": file_digest,
            "sheet_counts": {
                "claims_line_items": len(bundle.runtime_history),
                "invoice_summary": len(bundle.invoice_summaries),
                "current_test_invoices": len(bundle.acceptance_gold),
            },
            "runtime_counts": {
                "invoice": invoice_count,
                "estimate": estimate_count,
            },
            "acceptance_gold": {
                "excluded_from_runtime_history": True,
                "excluded_count": len(bundle.acceptance_gold),
                "invoice_numbers": acceptance_invoice_numbers,
            },
            "active_ontology_version": {
                "id": active_version.id,
                "label": active_version.label,
                "sequence_number": active_version.sequence_number,
            },
            "approval_status": ApprovalStatus.PROVISIONAL.value,
        },
    )

    ontology_codes = {record.mapped_ontology_id for record in bundle.runtime_history}
    ontology_items = {
        item.canonical_code: item
        for item in session.scalars(
            select(OntologyItem).where(OntologyItem.canonical_code.in_(ontology_codes))
        ).all()
    }
    missing_codes = ontology_codes - ontology_items.keys()
    if missing_codes:
        raise ValueError(
            "Historical seed rows reference missing ontology codes: "
            + ", ".join(sorted(missing_codes))
        )

    for record in bundle.runtime_history:
        item = ontology_items[record.mapped_ontology_id]
        session.add(
            _historical_observation(
                record,
                ontology_item=item,
                source_import=source_import,
                file_digest=file_digest,
            )
        )

    session.flush()
    return source_import, len(bundle.runtime_history)


def _historical_observation(
    record: HistoricalSeedRecord,
    *,
    ontology_item: OntologyItem,
    source_import: SourceImport,
    file_digest: str,
) -> HistoricalObservation:
    try:
        document_role = InvoiceDocumentRole(record.document_role)
    except ValueError as exc:
        raise ValueError(f"Unsupported historical document role: {record.document_role!r}") from exc
    classification = validate_vehicle_classification(
        official_vehicle_class=record.official_vehicle_class,
        bodywork_code=record.bodywork_code,
        market_segment=record.market_segment,
        classification_source=record.classification_source,
    )

    return HistoricalObservation(
        source_import_id=source_import.id,
        source_record_id=record.claim_line_id,
        observation_type=document_role,
        invoice_date=record.invoice_date,
        ontology_item_id=ontology_item.id,
        part_number=record.part_number,
        raw_description=record.raw_description,
        vehicle_make=record.vehicle_make,
        vehicle_model=record.vehicle_model,
        vehicle_year=record.vehicle_year,
        official_vehicle_class=classification.official_vehicle_class,
        bodywork_code=classification.bodywork_code,
        market_segment=classification.market_segment,
        classification_source=classification.classification_source,
        repair_operation=(
            record.raw_description
            if record.item_kind in {LineItemKind.LABOUR.value, LineItemKind.SERVICE.value}
            else None
        ),
        workshop_category=record.workshop_category,
        region=record.region or "UK",
        part_grade=ontology_item.part_grade,
        quantity=record.quantity,
        unit=ontology_item.unit,
        price_scope=PriceScope.LINE_TOTAL,
        unit_price_net=record.unit_price_net,
        line_total_net=record.line_total_net,
        vat_basis=PriceVatBasis.NET,
        settlement_status=SettlementStatus.PROPOSED,
        comparability_metadata_json={
            "evidence_label": "Previous repair & service invoice",
            "source_group": "historical_claim",
            "dataset_role": "historical_claims_seed",
            "amount_status": "invoiced",
            "source_file": record.source_file,
            "invoice_number": record.invoice_number,
            "garage_name": record.garage_name,
            "registration": record.registration,
            "mileage": record.mileage,
            "item_kind": record.item_kind,
            "vat_rate_pct": str(record.vat_rate),
            "notes": record.notes,
            "source_sha256": file_digest,
            "classification_status": (
                "verified" if classification.classification_source else "unclassified"
            ),
        },
        approval_status=ApprovalStatus.PROVISIONAL,
    )


def import_seed_workbooks(
    session: Session,
    ontology_path: str | Path,
    historical_path: str | Path,
    *,
    adapter: SeedDataAdapter | None = None,
    adapter_key: str = "excel_seed",
) -> SeedImportResult:
    """Import the pilot seed workbooks without committing the caller's session.

    Replaying identical workbook bytes returns the original immutable
    ``SourceImport`` identifiers and inserts no additional governed rows.
    """

    ontology_path = Path(ontology_path).expanduser().resolve()
    historical_path = Path(historical_path).expanduser().resolve()
    for path in (ontology_path, historical_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    ontology_digest = _sha256_file(ontology_path)
    history_digest = _sha256_file(historical_path)
    source_adapter = adapter or get_source_adapter_registry().seed(adapter_key)
    bundle = source_adapter.load(ontology_path, historical_path)

    provider = _get_or_create_provider(session)
    active_version = _active_ontology_version(session)
    ontology_import, ontology_created, price_created = _persist_ontology(
        session,
        records=bundle.ontology_items,
        provider=provider,
        active_version=active_version,
        source_path=ontology_path,
        file_digest=ontology_digest,
    )
    history_import, history_created = _persist_history(
        session,
        bundle=bundle,
        provider=provider,
        active_version=active_version,
        source_path=historical_path,
        file_digest=history_digest,
    )
    session.flush()

    return SeedImportResult(
        provider_id=provider.id,
        ontology_import_id=ontology_import.id,
        history_import_id=history_import.id,
        ontology_version_id=active_version.id,
        ontology_items_created=ontology_created,
        price_observations_created=price_created,
        historical_observations_created=history_created,
        acceptance_gold_excluded=len(bundle.acceptance_gold),
    )
