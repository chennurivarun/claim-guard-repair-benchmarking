from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from app.domain.money import as_decimal, money

from .models import HistoricalStatistics, HistoryObservation


@dataclass(frozen=True)
class _WeightedValue:
    value: Decimal
    weight: Decimal
    observation_id: str


def recency_weight(*, age_days: int, half_life_days: Decimal = Decimal("365.25")) -> Decimal:
    if age_days < 0:
        raise ValueError("age_days cannot be negative")
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    with localcontext() as context:
        context.prec = 28
        return Decimal("0.5") ** (Decimal(age_days) / half_life_days)


def weighted_median(values: Iterable[tuple[Decimal, Decimal, str]]) -> Decimal | None:
    """Return a deterministic weighted median, averaging an exact midpoint tie."""

    ordered = sorted(
        (
            _WeightedValue(as_decimal(value) or Decimal("0"), weight, identity)
            for value, weight, identity in values
            if weight > 0
        ),
        key=lambda value: (value.value, value.observation_id),
    )
    if not ordered:
        return None
    total_weight = sum((value.weight for value in ordered), Decimal("0"))
    halfway = total_weight / Decimal("2")
    running = Decimal("0")
    for index, candidate in enumerate(ordered):
        running += candidate.weight
        if running == halfway and index + 1 < len(ordered):
            return money((candidate.value + ordered[index + 1].value) / Decimal("2"))
        if running >= halfway:
            return money(candidate.value)
    return money(ordered[-1].value)


def _is_invoice(document_type: str) -> bool:
    value = document_type.strip().lower().replace("-", "_").replace(" ", "_")
    if any(marker in value for marker in ("estimate", "quote", "quotation")):
        return False
    return "invoice" in value


def historical_statistics(
    observations: Iterable[HistoryObservation],
    *,
    as_of_date: date,
    minimum_count: int = 3,
    half_life_days: Decimal = Decimal("365.25"),
) -> HistoricalStatistics:
    """Build eligible, past-invoice-only statistics with explicit exclusions."""

    exclusions: Counter[str] = Counter()
    line_values: list[tuple[Decimal, Decimal, str]] = []
    unit_values: list[tuple[Decimal, Decimal, str]] = []
    eligible_dates: list[date] = []
    lineage_ids: set[str] = set()
    line_total_preferred_count = 0
    derived_line_total_count = 0

    for observation in sorted(observations, key=lambda item: item.observation_id):
        if not observation.eligible:
            exclusions["not_eligible"] += 1
            continue
        if not _is_invoice(observation.document_type):
            exclusions["estimate_or_non_invoice"] += 1
            continue
        if observation.observed_at >= as_of_date:
            exclusions["not_past_observation"] += 1
            continue
        if not observation.unit_compatible:
            exclusions["unit_incompatible"] += 1
            continue
        if not observation.quantity_scope_equivalent:
            exclusions["quantity_scope_not_equivalent"] += 1
            continue

        comparability = as_decimal(observation.comparability_score) or Decimal("0")
        comparability = min(max(comparability, Decimal("0")), Decimal("1"))
        if comparability == 0:
            exclusions["zero_comparability"] += 1
            continue

        line_total = money(observation.net_line_total)
        unit_price = money(observation.net_unit_price)
        quantity = as_decimal(observation.quantity)

        used_explicit_line_total = line_total is not None
        derived_line_total = False
        if line_total is None and unit_price is not None and quantity is not None and quantity > 0:
            line_total = money(unit_price * quantity)
            derived_line_total = True

        if line_total is None or line_total <= 0:
            exclusions["missing_comparable_line_total"] += 1
            continue

        if used_explicit_line_total:
            line_total_preferred_count += 1
        elif derived_line_total:
            derived_line_total_count += 1

        if unit_price is None and quantity is not None and quantity > 0:
            unit_price = money(line_total / quantity)

        age_days = (as_of_date - observation.observed_at).days
        weight = recency_weight(age_days=age_days, half_life_days=half_life_days) * comparability
        line_values.append((line_total, weight, observation.observation_id))
        if unit_price is not None and unit_price > 0:
            unit_values.append((unit_price, weight, observation.observation_id))
        eligible_dates.append(observation.observed_at)
        if observation.source_lineage_id:
            lineage_ids.add(observation.source_lineage_id)

    eligible_count = len(line_values)
    return HistoricalStatistics(
        eligible_count=eligible_count,
        excluded_count=sum(exclusions.values()),
        excluded_reasons=tuple(sorted(exclusions.items())),
        weighted_median_line_net=weighted_median(line_values),
        weighted_median_unit_net=weighted_median(unit_values),
        weak_sample=eligible_count < minimum_count,
        line_total_preferred_count=line_total_preferred_count,
        derived_line_total_count=derived_line_total_count,
        observed_from=min(eligible_dates) if eligible_dates else None,
        observed_to=max(eligible_dates) if eligible_dates else None,
        source_lineage_ids=tuple(sorted(lineage_ids)),
    )
