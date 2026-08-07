from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class PriceScope(StrEnum):
    EACH = "each"
    LITRE = "litre"
    HOUR = "hour"
    JOB = "job"
    TEST = "test"
    SET = "set"


class MatchKind(StrEnum):
    EXACT_PART_NUMBER = "exact_part_number"
    EXACT_SYNONYM = "exact_synonym"
    EXACT_CANONICAL_NAME = "exact_canonical_name"
    FUZZY = "fuzzy"


class BenchmarkSource(StrEnum):
    WEIGHTED_CONSENSUS = "weighted_consensus"
    ONTOLOGY = "ontology"
    HISTORY = "history"
    NONE = "none"


class ChallengeSeverity(StrEnum):
    NEUTRAL = "neutral"
    AMBER = "amber"
    RED = "red"


@dataclass(frozen=True)
class OntologyItem:
    item_id: str
    canonical_name: str
    item_type: str
    unit: str
    price_scope: str
    synonyms: tuple[str, ...] = ()
    part_numbers: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappingCandidate:
    item_id: str
    canonical_name: str
    match_kind: MatchKind
    mapping_confidence: Decimal
    matched_on: str
    normalised_invoice_text: str


@dataclass(frozen=True)
class OntologyPriceEvidence:
    item_id: str
    amount_net: Decimal
    price_scope: str
    unit: str
    approved: bool = True
    reliable: bool = True
    confidence: Decimal = Decimal("1")
    source_lineage_id: str | None = None
    observed_at: date | None = None


@dataclass(frozen=True)
class HistoryObservation:
    observation_id: str
    invoice_id: str
    observed_at: date
    document_type: str
    net_line_total: Decimal | None = None
    net_unit_price: Decimal | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    eligible: bool = True
    unit_compatible: bool = True
    quantity_scope_equivalent: bool = True
    comparability_score: Decimal = Decimal("1")
    source_lineage_id: str | None = None


@dataclass(frozen=True)
class CurrentInvoiceLine:
    line_id: str
    description: str
    invoice_line_net: Decimal
    invoice_date: date
    quantity: Decimal | None = None
    unit: str | None = None
    part_number: str | None = None
    vat_rate: Decimal = Decimal("20")
    vat_applicable: bool = True
    is_mot: bool = False


@dataclass(frozen=True)
class ComparisonPolicy:
    version: str = "claimguard-v1.4"
    ontology_weight: Decimal = Decimal("0.60")
    history_weight: Decimal = Decimal("0.40")
    minimum_history_count: int = 3
    strong_history_count: int = 10
    history_half_life_days: Decimal = Decimal("365.25")
    minimum_challenge_amount: Decimal = Decimal("5.00")
    minimum_challenge_percent: Decimal = Decimal("5.00")
    red_amount: Decimal = Decimal("25.00")
    red_percent: Decimal = Decimal("25.00")
    allow_history_without_ontology: bool = True
    benchmark_floor_net: Decimal | None = None


@dataclass(frozen=True)
class ExpectedLineAmount:
    expected_line_net: Decimal | None
    requires_review: bool
    review_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoricalStatistics:
    eligible_count: int
    excluded_count: int
    excluded_reasons: tuple[tuple[str, int], ...]
    weighted_median_line_net: Decimal | None
    weighted_median_unit_net: Decimal | None
    weak_sample: bool
    line_total_preferred_count: int
    derived_line_total_count: int
    observed_from: date | None
    observed_to: date | None
    source_lineage_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChallengeScore:
    score: Decimal
    label: str
    mapping_component: Decimal
    price_evidence_component: Decimal
    fit_component: Decimal
    history_component: Decimal
    recency_component: Decimal
    independent_agreement_component: Decimal
    penalty_points: Decimal


@dataclass(frozen=True)
class LineComparison:
    line_id: str
    policy_version: str
    invoice_price_net: Decimal
    ontology_expected_net: Decimal | None
    historical_expected_net: Decimal | None
    difference_from_ontology_net: Decimal | None
    difference_from_history_net: Decimal | None
    selected_benchmark_net: Decimal | None
    benchmark_source: BenchmarkSource
    benchmark_formula: str
    challenge_price_net: Decimal
    challenge_amount_net: Decimal
    challenge_percentage: Decimal
    vat_impact: Decimal
    challenge_gross: Decimal
    gate_passed: bool
    severity: ChallengeSeverity
    mapping_confidence: Decimal
    price_evidence_confidence: Decimal
    challenge_score: Decimal
    challenge_score_label: str
    ontology_reliable: bool
    history_reliable: bool
    sources_independent: bool
    source_lineage_independence_known: bool
    source_lineage_note: str
    source_lineage_ids: tuple[str, ...]
    history: HistoricalStatistics
    review_required: bool
    review_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class InvoiceChallengeSummary:
    invoice_price_net: Decimal
    challenge_price_net: Decimal
    challenge_amount_net: Decimal
    vat_impact: Decimal
    challenge_gross: Decimal
    challenged_line_count: int
    severity_counts: dict[str, int] = field(default_factory=dict)
