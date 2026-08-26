"""A governed, invoice-only repair-cost benchmarking layer.

The existing ``historical_observations`` table is the benchmark database: each
row remains tied to a source invoice line and a canonical ontology item.  This
module intentionally calculates statistics on demand so a dashboard can always
show the exact observation count and source coverage behind a benchmark.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.comparison.models import ComparisonPolicy
from app.domain.normalisation import normalise_description
from app.enums import (
    ApprovalStatus,
    InvoiceDocumentRole,
    LineItemKind,
    MappingStatus,
    PriceVatBasis,
)
from app.models import (
    Case,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    MappingRun,
    OntologyItem,
    OntologyMapping,
    SourceImport,
    SourceProvider,
)
from app.services.vehicle_category_lookup import lookup_vehicle_category
from app.services.vehicle_classification import (
    M1_BODYWORK_CODES,
    OFFICIAL_VEHICLE_CLASSES,
    classification_from_record,
)

OFFICIAL_CLASSIFICATION_REFERENCE = {
    **OFFICIAL_VEHICLE_CLASSES,
    **{code: f"M1 bodywork: {label}" for code, label in M1_BODYWORK_CODES.items()},
}
DEFAULT_COMPARISON_POLICY = ComparisonPolicy()


@dataclass(frozen=True)
class BenchmarkStatistics:
    minimum: Decimal | None
    maximum: Decimal | None
    mean: Decimal | None
    median: Decimal | None
    mode: Decimal | None
    percentile_25: Decimal | None
    percentile_75: Decimal | None
    percentile_90: Decimal | None
    outlier_count: int
    count: int

    def payload(self) -> dict[str, float | int | None]:
        return {
            "min": _number(self.minimum),
            "max": _number(self.maximum),
            "mean": _number(self.mean),
            "median": _number(self.median),
            "mode": _number(self.mode),
            "p25": _number(self.percentile_25),
            "p75": _number(self.percentile_75),
            "p90": _number(self.percentile_90),
            "outlierCount": self.outlier_count,
            "count": self.count,
        }


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _number(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _observation_source_group(observation: HistoricalObservation) -> str:
    metadata = observation.comparability_metadata_json or {}
    source_file = str(metadata.get("source_file") or "").lower()
    if "historical_claim" in source_file:
        return "historical_claim"
    explicit_group = metadata.get("source_group")
    if explicit_group:
        return str(explicit_group)
    if metadata.get("source") == "ClaimGuard finalised invoice":
        return "historical_claim"
    return "historical_claim"


def _active_in_house_import_id(session: Session) -> str | None:
    imports = session.scalars(
        select(SourceImport)
        .join(SourceProvider, SourceProvider.id == SourceImport.provider_id)
        .where(SourceProvider.name == "ClaimGuard synthetic in-house repair data")
        .order_by(SourceImport.created_at.desc())
    ).all()
    active = next(
        (
            source_import
            for source_import in imports
            if (source_import.validation_report_json or {}).get("active_dataset") is True
        ),
        imports[0] if imports else None,
    )
    return active.id if active else None


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal:
    """Return an interpolated percentile for an already sorted population."""

    if len(values) == 1:
        return values[0]
    position = Decimal(len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - Decimal(lower)
    return values[lower] + ((values[upper] - values[lower]) * fraction)


def canonical_benchmark_category(description: str, normalised: str | None = None) -> str:
    """Return a stable category for uploaded-line benchmarking.

    Governed repair-item mappings remain the primary identity in the comparison
    workflow.  This narrow fallback keeps common oil-disposal wording together
    before a handler has approved a mapping, which makes the first P90 pilot
    useful immediately after batch extraction.
    """

    value = normalised or normalise_description(description)
    tokens = set(value.replace("&", " and ").replace("/", " ").split())
    if "oil" in tokens and "disposal" in tokens:
        return "Oil & Filter Disposal"
    return value


def calculate_benchmark_statistics(values: Iterable[Decimal]) -> BenchmarkStatistics:
    """Calculate unweighted, explainable values for a benchmark population."""

    ordered = sorted(value for value in values if value > 0)
    count = len(ordered)
    if not ordered:
        return BenchmarkStatistics(None, None, None, None, None, None, None, None, 0, 0)
    midpoint = count // 2
    median = (
        ordered[midpoint]
        if count % 2
        else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")
    )
    frequencies = Counter(ordered)
    highest_frequency = max(frequencies.values())
    # A unique repeated value is a useful mode; a no-repeat population has none.
    modes = sorted(
        value for value, frequency in frequencies.items() if frequency == highest_frequency
    )
    mode = modes[0] if highest_frequency > 1 and len(modes) == 1 else None
    percentile_25 = _percentile(ordered, Decimal("0.25"))
    percentile_75 = _percentile(ordered, Decimal("0.75"))
    percentile_90 = _percentile(ordered, Decimal("0.90"))
    interquartile_range = percentile_75 - percentile_25
    lower_fence = percentile_25 - (interquartile_range * Decimal("1.5"))
    upper_fence = percentile_75 + (interquartile_range * Decimal("1.5"))
    return BenchmarkStatistics(
        minimum=_money(ordered[0]),
        maximum=_money(ordered[-1]),
        mean=_money(sum(ordered, Decimal("0")) / Decimal(count)),
        median=_money(median),
        mode=_money(mode),
        percentile_25=_money(percentile_25),
        percentile_75=_money(percentile_75),
        percentile_90=_money(percentile_90),
        outlier_count=sum(value < lower_fence or value > upper_fence for value in ordered),
        count=count,
    )


def _observed_cost(observation: HistoricalObservation) -> Decimal | None:
    return _decimal(observation.line_total_net) or _decimal(observation.unit_price_net)


def _vehicle_label(session: Session, observation: HistoricalObservation) -> str:
    # Preserve sourced regulatory/market classifications when present. Historical
    # seed rows without those columns can use the governed make/model catalogue.
    if label := classification_from_record(observation).label:
        return label
    match = lookup_vehicle_category(
        session,
        make=observation.vehicle_make,
        model=observation.vehicle_model,
    )
    if match is None:
        return "Unclassified"
    return match.body_type or f"Insurance group {match.group_range} — {match.group_category}"


def _vehicle_dimension(
    session: Session, observation: HistoricalObservation, source_group: str | None
) -> str:
    """Use exact make/model for the in-house book; classifications elsewhere."""

    if source_group == "in_house":
        make = (observation.vehicle_make or "Unknown make").strip()
        model = (observation.vehicle_model or "Unknown model").strip()
        return f"{make} {model}".strip()
    return _vehicle_label(session, observation)


def _observation_invoice_reference(observation: HistoricalObservation) -> str:
    metadata = observation.comparability_metadata_json or {}
    return str(
        metadata.get("invoice_number")
        or observation.source_invoice_id
        or observation.source_record_id
        or observation.id
    )


def _observation_repairer(observation: HistoricalObservation) -> str:
    metadata = observation.comparability_metadata_json or {}
    return str(metadata.get("garage_name") or observation.workshop_category or "Unknown repairer")


def _repairer_group_key(value: str) -> str:
    """Return a conservative identity key without changing the display name."""

    return " ".join(value.split()).casefold()


def _build_repairer_trends(
    repairer_item_exceptions: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Aggregate graph nodes and edges from the same explainable P90 exceptions."""

    repairer_rows: dict[str, dict[str, Any]] = {}
    for (repairer_key, item_id, item_name), exceptions in repairer_item_exceptions.items():
        if not exceptions:
            continue
        display_name = str(exceptions[0]["repairer"]).strip() or "Unknown repairer"
        row = repairer_rows.setdefault(
            repairer_key,
            {
                "repairer": display_name,
                "challengeCount": 0,
                "invoices": set(),
                "totalDifference": Decimal("0"),
                "maximumDifference": Decimal("0"),
                "items": [],
            },
        )
        differences = [Decimal(str(item["difference"])) for item in exceptions]
        row["challengeCount"] += len(exceptions)
        row["invoices"].update(str(item["invoiceNumber"]) for item in exceptions)
        row["totalDifference"] += sum(differences, Decimal("0"))
        row["maximumDifference"] = max(row["maximumDifference"], *differences)
        row["items"].append(
            {
                "ontologyItemId": item_id,
                "item": item_name,
                "challengeCount": len(exceptions),
                "invoiceCount": len({str(item["invoiceNumber"]) for item in exceptions}),
                "totalDifference": _number(_money(sum(differences, Decimal("0")))),
                "maximumDifference": _number(_money(max(differences))),
                "maximumPercentageAboveP90": max(
                    float(item["percentageAboveP90"]) for item in exceptions
                ),
                "exceptions": exceptions,
            }
        )

    repairer_trends: list[dict[str, Any]] = []
    for row in repairer_rows.values():
        row["invoiceCount"] = len(row.pop("invoices"))
        row["itemCount"] = len(row["items"])
        row["totalDifference"] = _number(_money(row["totalDifference"]))
        row["maximumDifference"] = _number(_money(row["maximumDifference"]))
        row["items"].sort(
            key=lambda item: (-item["invoiceCount"], -item["challengeCount"], item["item"])
        )
        repairer_trends.append(row)
    repairer_trends.sort(
        key=lambda row: (-row["invoiceCount"], -row["challengeCount"], row["repairer"])
    )
    return repairer_trends


def _benchmark_exception(
    observation: HistoricalObservation,
    *,
    percentile_90: Decimal | None,
    threshold_percentage: Decimal,
    minimum_amount: Decimal = DEFAULT_COMPARISON_POLICY.minimum_challenge_amount,
) -> dict[str, Any] | None:
    """Return one explainable P90 exception, or ``None`` when it is within threshold."""

    cost = _observed_cost(observation)
    if cost is None or percentile_90 is None or percentile_90 <= 0:
        return None
    difference = cost - percentile_90
    percentage = (difference / percentile_90) * Decimal("100")
    if difference < minimum_amount or percentage <= threshold_percentage:
        return None
    return {
        "observationId": observation.id,
        "invoiceNumber": _observation_invoice_reference(observation),
        "repairer": _observation_repairer(observation),
        "description": observation.raw_description,
        "amount": _number(_money(cost)),
        "p90": _number(_money(percentile_90)),
        "difference": _number(_money(difference)),
        "percentageAboveP90": float(percentage.quantize(Decimal("0.1"))),
    }


def _rolling_benchmark_exceptions(
    observations: list[HistoricalObservation],
    *,
    threshold_percentage: Decimal,
    minimum_count: int = 3,
) -> list[dict[str, Any]]:
    """Evaluate each invoice against earlier invoices only.

    All lines from the same invoice are evaluated before that invoice enters the
    history. This mirrors the operational review rule: an invoice never helps
    calculate its own P90 and later invoices cannot alter an earlier decision.
    """

    ordered = sorted(
        observations,
        key=lambda observation: (
            observation.invoice_date or date.min,
            _observation_invoice_reference(observation),
            observation.id,
        ),
    )
    invoice_groups: dict[tuple[date | None, str], list[HistoricalObservation]] = {}
    for observation in ordered:
        key = (observation.invoice_date, _observation_invoice_reference(observation))
        invoice_groups.setdefault(key, []).append(observation)

    prior_costs: list[Decimal] = []
    exceptions: list[dict[str, Any]] = []
    for invoice_observations in invoice_groups.values():
        statistics = calculate_benchmark_statistics(prior_costs)
        if statistics.count >= minimum_count:
            for observation in invoice_observations:
                exception = _benchmark_exception(
                    observation,
                    percentile_90=statistics.percentile_90,
                    threshold_percentage=threshold_percentage,
                )
                if exception:
                    exception["historicalCount"] = statistics.count
                    exceptions.append(exception)
        prior_costs.extend(
            cost
            for observation in invoice_observations
            if (cost := _observed_cost(observation)) is not None and cost > 0
        )
    return exceptions


def build_benchmark_dashboard(
    session: Session,
    *,
    vehicle_class: str | None = None,
    ontology_item_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    minimum_count: int = 1,
    challenge_threshold_pct: Decimal | int | float = Decimal("10"),
    source_group: str | None = None,
) -> dict[str, Any]:
    """Return statistics grouped by canonical repair item and vehicle dimension."""

    all_rows = list(
        session.execute(
            select(HistoricalObservation, OntologyItem)
            .join(OntologyItem, OntologyItem.id == HistoricalObservation.ontology_item_id)
            .where(HistoricalObservation.observation_type == InvoiceDocumentRole.INVOICE)
            .order_by(OntologyItem.canonical_name, HistoricalObservation.invoice_date)
        ).all()
    )
    if source_group:
        all_rows = [row for row in all_rows if _observation_source_group(row[0]) == source_group]
    if source_group == "in_house":
        active_import_id = _active_in_house_import_id(session)
        # Fresh installations use the versioned synthetic-data import. Older
        # databases predate that provider record, so retain their existing
        # in-house observations until the next comparison creates v2 data.
        if active_import_id is not None:
            all_rows = [row for row in all_rows if row[0].source_import_id == active_import_id]
    available_vehicle_classes = sorted(
        {_vehicle_dimension(session, row, source_group) for row, _ in all_rows}
    )
    available_items = sorted(
        ({"id": item.id, "name": item.canonical_name} for _, item in all_rows),
        key=lambda item: str(item["name"]),
    )
    deduplicated_items = list({str(item["id"]): item for item in available_items}.values())
    rows = [
        (observation, item)
        for observation, item in all_rows
        if (
            vehicle_class is None
            or _vehicle_dimension(session, observation, source_group) == vehicle_class
        )
        and (ontology_item_id is None or item.id == ontology_item_id)
        and (
            date_from is None
            or (observation.invoice_date and observation.invoice_date >= date_from)
        )
        and (date_to is None or (observation.invoice_date and observation.invoice_date <= date_to))
    ]
    item_groups: dict[tuple[str, str, str], list[HistoricalObservation]] = defaultdict(list)
    category_values: dict[str, list[Decimal]] = defaultdict(list)
    all_costs: list[Decimal] = []
    labour_rates: list[Decimal] = []

    for observation, item in rows:
        cost = _observed_cost(observation)
        if cost is None or cost <= 0:
            continue
        category_label = _vehicle_dimension(session, observation, source_group)
        item_groups[(item.id, item.canonical_name, category_label)].append(observation)
        category_values[category_label].append(cost)
        all_costs.append(cost)
        explicit_rate = _decimal(observation.labour_rate)
        if explicit_rate is not None:
            labour_rates.append(explicit_rate)
        elif item.item_type == LineItemKind.LABOUR and observation.unit in {
            "hour",
            "hours",
            "hr",
            "hrs",
        }:
            unit_rate = _decimal(observation.unit_price_net)
            if unit_rate is not None:
                labour_rates.append(unit_rate)

    threshold_percentage = Decimal(str(challenge_threshold_pct))
    details: list[dict[str, Any]] = []
    category_totals: list[dict[str, Any]] = []
    repairer_item_exceptions: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for (item_id, item_name, vehicle_class), observations in item_groups.items():
        costs = [cost for item in observations if (cost := _observed_cost(item)) is not None]
        labour = [rate for item in observations if (rate := _decimal(item.labour_rate)) is not None]
        stats = calculate_benchmark_statistics(costs)
        if stats.count < max(1, minimum_count):
            continue
        exceptions = _rolling_benchmark_exceptions(
            observations,
            threshold_percentage=threshold_percentage,
        )
        for exception in exceptions:
            repairer = str(exception["repairer"])
            repairer_item_exceptions[(_repairer_group_key(repairer), item_id, item_name)].append(
                exception
            )
        details.append(
            {
                "ontologyItemId": item_id,
                "item": item_name,
                "vehicleClass": vehicle_class,
                "vehicleMake": observations[0].vehicle_make,
                "vehicleModel": observations[0].vehicle_model,
                "statistics": stats.payload(),
                "labourStatistics": calculate_benchmark_statistics(labour).payload(),
                "sourceCount": len(observations),
                "invoiceCount": len(
                    {_observation_invoice_reference(item) for item in observations}
                ),
                "exceptionCount": len(exceptions),
                "exceptionInvoiceCount": len(
                    {str(exception["invoiceNumber"]) for exception in exceptions}
                ),
                "exceptions": exceptions,
                "sampleStrength": (
                    "strong"
                    if stats.count >= 10
                    else "usable"
                    if stats.count >= 3
                    else "insufficient"
                ),
                "latestObservedAt": max(
                    (item.invoice_date for item in observations if item.invoice_date),
                    default=None,
                ),
            }
        )
    for vehicle_class, costs in category_values.items():
        stats = calculate_benchmark_statistics(costs)
        category_totals.append(
            {
                "vehicleClass": vehicle_class,
                "averageCost": _number(stats.mean),
                "count": stats.count,
            }
        )

    details.sort(key=lambda row: (-int(row["statistics"]["count"]), str(row["item"])))
    category_totals.sort(key=lambda row: (-int(row["count"]), str(row["vehicleClass"])))
    overall = calculate_benchmark_statistics(all_costs)
    labour = calculate_benchmark_statistics(labour_rates)
    highest_category = max(
        details,
        key=lambda row: row["statistics"]["mean"] or 0,
        default=None,
    )
    most_observed = details[0] if details else None
    invoice_rows = [
        observation
        for observation, _ in all_rows
        if observation.observation_type == InvoiceDocumentRole.INVOICE
    ]
    valid_rows = [
        observation
        for observation in invoice_rows
        if (cost := _observed_cost(observation)) is not None and cost > 0
    ]
    classified_rows = [
        observation
        for observation in valid_rows
        if _vehicle_label(session, observation) != "Unclassified"
    ]
    latest_observation = max(
        (observation.invoice_date for observation in valid_rows if observation.invoice_date),
        default=None,
    )
    repairer_trends = _build_repairer_trends(repairer_item_exceptions)
    return {
        "summary": {
            "averageRepairCost": _number(overall.mean),
            "averageLabourRate": _number(labour.mean),
            "mostObservedItem": most_observed["item"] if most_observed else None,
            "observationCount": overall.count,
            "mostExpensiveRepairCategory": highest_category["item"] if highest_category else None,
            "mostExpensiveRepairAverage": (
                highest_category["statistics"]["mean"] if highest_category else None
            ),
        },
        "vehicleCategories": category_totals,
        "benchmarks": details,
        "repairerTrends": repairer_trends,
        "filterOptions": {
            "vehicleClasses": available_vehicle_classes,
            "repairItems": deduplicated_items,
        },
        "appliedFilters": {
            "vehicleClass": vehicle_class,
            "ontologyItemId": ontology_item_id,
            "dateFrom": date_from,
            "dateTo": date_to,
            "minimumCount": max(1, minimum_count),
            "challengeThresholdPct": float(threshold_percentage),
            "sourceGroup": source_group,
            "minimumChallengeAmount": _number(DEFAULT_COMPARISON_POLICY.minimum_challenge_amount),
        },
        "dataQuality": {
            "invoiceObservationCount": len(invoice_rows),
            "validCostCount": len(valid_rows),
            "invalidOrMissingCostCount": len(invoice_rows) - len(valid_rows),
            "classifiedCount": len(classified_rows),
            "unclassifiedCount": len(valid_rows) - len(classified_rows),
            "classifiedCoveragePct": (
                round((len(classified_rows) / len(valid_rows)) * 100, 1) if valid_rows else 0
            ),
            "latestObservationDate": latest_observation,
        },
        "definitions": {
            "cost": "Invoice net line total, excluding estimates and credit notes.",
            "labour": "Explicit labour rate, or an hourly labour line where available.",
            "challengeGate": (
                "A P90 exception must exceed the selected percentage threshold and the "
                f"existing £{DEFAULT_COMPARISON_POLICY.minimum_challenge_amount:.2f} "
                "minimum positive variance."
            ),
            "officialClasses": OFFICIAL_CLASSIFICATION_REFERENCE,
            "coverageNote": (
                "Sourced regulatory/market classifications take priority; otherwise the "
                "client-approved make/model catalogue supplies the vehicle category. "
                "Unmatched rows remain visible as Unclassified."
            ),
        },
    }


def benchmark_observations(
    session: Session,
    ontology_item_id: str,
    *,
    vehicle_class: str | None = None,
    source_group: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return bounded source rows behind a dashboard benchmark."""

    rows = list(
        session.scalars(
            select(HistoricalObservation)
            .where(
                HistoricalObservation.ontology_item_id == ontology_item_id,
                HistoricalObservation.observation_type == InvoiceDocumentRole.INVOICE,
            )
            .order_by(HistoricalObservation.invoice_date.desc())
        ).all()
    )
    if source_group:
        rows = [row for row in rows if _observation_source_group(row) == source_group]
    if source_group == "in_house":
        active_import_id = _active_in_house_import_id(session)
        if active_import_id is not None:
            rows = [row for row in rows if row.source_import_id == active_import_id]
    if vehicle_class:
        rows = [
            row for row in rows if _vehicle_dimension(session, row, source_group) == vehicle_class
        ]
    rows = rows[: min(max(limit, 1), 250)]
    return [
        {
            "id": row.id,
            "invoiceDate": row.invoice_date,
            "amount": _number(_observed_cost(row)),
            "vehicleClass": _vehicle_dimension(session, row, source_group),
            "vehicleMake": row.vehicle_make,
            "vehicleModel": row.vehicle_model,
            "rawDescription": row.raw_description,
            "sourceRecordId": row.source_record_id,
            "repairer": _observation_repairer(row),
            "sourceGroup": _observation_source_group(row),
            "source": row.comparability_metadata_json or {},
        }
        for row in rows
        if (cost := _observed_cost(row)) is not None and cost > 0
    ]


def sync_finalised_case_to_benchmarks(session: Session, case: Case) -> int:
    """Append reviewed finalised invoice lines once, for future benchmark use.

    The current invoice is never benchmarked during its own review.  Only after
    finalisation and a human-reviewed mapping does it become a historical source.
    """

    if not case.current_processing_run_id:
        return 0
    rows = list(
        session.execute(
            select(InvoiceLineItem, Invoice, OntologyMapping)
            .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
            .join(OntologyMapping, OntologyMapping.invoice_line_item_id == InvoiceLineItem.id)
            .join(MappingRun, MappingRun.id == OntologyMapping.mapping_run_id)
            .where(
                Invoice.case_id == case.id,
                MappingRun.processing_run_id == case.current_processing_run_id,
                Invoice.document_role == InvoiceDocumentRole.INVOICE,
                OntologyMapping.selected_ontology_item_id.is_not(None),
                OntologyMapping.final_status.in_({MappingStatus.APPROVED, MappingStatus.EDITED}),
            )
        ).all()
    )
    created = 0
    for line, invoice, mapping in rows:
        if not line.line_total_net:
            continue
        already_present = session.scalar(
            select(HistoricalObservation.id).where(
                HistoricalObservation.source_line_item_id == line.id
            )
        )
        if already_present:
            continue
        session.add(
            HistoricalObservation(
                source_invoice_id=invoice.id,
                source_line_item_id=line.id,
                source_record_id=f"finalised:{case.id}:{line.id}",
                claim_reference=case.case_reference,
                observation_type=InvoiceDocumentRole.INVOICE,
                invoice_date=invoice.invoice_date,
                ontology_item_id=mapping.selected_ontology_item_id,
                part_number=line.part_number,
                raw_description=line.raw_description,
                vehicle_make=invoice.vehicle.make if invoice.vehicle else None,
                vehicle_model=invoice.vehicle.model if invoice.vehicle else None,
                vehicle_variant=invoice.vehicle.variant if invoice.vehicle else None,
                vehicle_year=invoice.vehicle.manufacture_year if invoice.vehicle else None,
                official_vehicle_class=(
                    invoice.vehicle.official_vehicle_class if invoice.vehicle else None
                ),
                bodywork_code=invoice.vehicle.bodywork_code if invoice.vehicle else None,
                market_segment=invoice.vehicle.market_segment if invoice.vehicle else None,
                classification_source=(
                    invoice.vehicle.classification_source if invoice.vehicle else None
                ),
                repair_operation=line.raw_description
                if line.item_kind == LineItemKind.LABOUR
                else None,
                workshop_category=invoice.supplier_name,
                region="UK",
                quantity=line.quantity,
                unit=line.unit,
                price_scope=line.price_scope,
                unit_price_net=line.unit_price_net,
                line_total_net=line.line_total_net,
                vat_basis=PriceVatBasis.NET,
                approval_status=ApprovalStatus.APPROVED,
                comparability_metadata_json={
                    "source": "ClaimGuard finalised invoice",
                    "source_group": "historical_claim",
                    "case_reference": case.case_reference,
                    "invoice_number": invoice.invoice_number,
                    "mapping_status": mapping.final_status.value,
                    "classification_status": (
                        "verified"
                        if invoice.vehicle and invoice.vehicle.classification_source
                        else "unclassified_pending_vehicle_data"
                    ),
                },
            )
        )
        created += 1
    session.flush()
    return created
