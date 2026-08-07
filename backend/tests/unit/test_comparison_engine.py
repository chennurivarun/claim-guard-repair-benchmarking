from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.comparison import (
    BenchmarkSource,
    ChallengeSeverity,
    CurrentInvoiceLine,
    HistoryObservation,
    MatchKind,
    OntologyItem,
    OntologyPriceEvidence,
    aggregate_challenges,
    compare_line,
    expected_line_amount,
    historical_statistics,
    recency_weight,
    retrieve_candidates,
)

TODAY = date(2026, 7, 17)


def _line(
    line_id: str,
    invoice_net: str,
    *,
    description: str = "Labour operation",
    quantity: str | None = "1",
    unit: str | None = "job",
    is_mot: bool = False,
) -> CurrentInvoiceLine:
    return CurrentInvoiceLine(
        line_id=line_id,
        description=description,
        invoice_line_net=Decimal(invoice_net),
        invoice_date=TODAY,
        quantity=Decimal(quantity) if quantity is not None else None,
        unit=unit,
        is_mot=is_mot,
    )


def _ontology(
    amount: str,
    *,
    scope: str = "job",
    lineage: str = "ontology-provider",
) -> OntologyPriceEvidence:
    return OntologyPriceEvidence(
        item_id="LAB-001",
        amount_net=Decimal(amount),
        price_scope=scope,
        unit=scope,
        source_lineage_id=lineage,
    )


def _history(
    amount: str,
    index: int,
    *,
    days_ago: int | None = None,
    document_type: str = "repair_invoice_observation",
    lineage: str | None = None,
) -> HistoryObservation:
    return HistoryObservation(
        observation_id=f"OBS-{index}",
        invoice_id=f"INV-{index}",
        observed_at=TODAY - timedelta(days=days_ago or (30 + index)),
        document_type=document_type,
        net_line_total=Decimal(amount),
        net_unit_price=Decimal(amount),
        quantity=Decimal("1"),
        unit="job",
        source_lineage_id=lineage or f"history-{index}",
    )


def test_weighted_consensus_is_sixty_forty() -> None:
    result = compare_line(
        line=_line("1", "15000"),
        ontology=_ontology("14000"),
        history_observations=tuple(_history("13500", i) for i in range(3)),
        mapping_confidence=Decimal("0.95"),
        price_evidence_confidence=Decimal("0.90"),
    )

    assert result.ontology_expected_net == Decimal("14000.00")
    assert result.historical_expected_net == Decimal("13500.00")
    assert result.selected_benchmark_net == Decimal("13800.00")
    assert result.benchmark_source == BenchmarkSource.WEIGHTED_CONSENSUS
    assert result.difference_from_ontology_net == Decimal("1000.00")
    assert result.difference_from_history_net == Decimal("1500.00")


def test_job_test_and_set_prices_apply_once() -> None:
    for scope in ("job", "test", "set"):
        expected = expected_line_amount(
            price_net=Decimal("125"),
            price_scope=scope,
            invoice_quantity=Decimal("9"),
            invoice_unit="hour",
        )
        assert expected.expected_line_net == Decimal("125.00")
        assert expected.requires_review is False


def test_each_litre_and_hour_require_known_compatible_quantity() -> None:
    multiplied = expected_line_amount(
        price_net=Decimal("12.50"),
        price_scope="hour",
        invoice_quantity=Decimal("2.5"),
        invoice_unit="hrs",
    )
    assert multiplied.expected_line_net == Decimal("31.25")

    unknown = expected_line_amount(
        price_net=Decimal("12.50"),
        price_scope="each",
        invoice_quantity=None,
        invoice_unit="each",
    )
    assert unknown.expected_line_net is None
    assert unknown.requires_review is True
    assert "EXPECTED_QUANTITY_UNKNOWN" in unknown.review_flags

    incompatible = expected_line_amount(
        price_net=Decimal("12.50"),
        price_scope="litre",
        invoice_quantity=Decimal("2"),
        invoice_unit="each",
    )
    assert incompatible.expected_line_net is None
    assert incompatible.requires_review is True


def test_unknown_expected_quantity_is_review_not_a_guess() -> None:
    result = compare_line(
        line=_line("1", "40", quantity=None, unit="each"),
        ontology=_ontology("10", scope="each"),
    )
    assert result.selected_benchmark_net is None
    assert result.challenge_amount_net == Decimal("0.00")
    assert result.review_required is True
    assert "EXPECTED_QUANTITY_UNKNOWN" in result.review_flags


def test_history_uses_only_past_invoice_observations_and_line_total() -> None:
    observations = (
        _history("100", 1, days_ago=1),
        _history("10", 2, days_ago=730),
        _history("20", 3, days_ago=731),
        _history("1", 4, days_ago=2, document_type="estimate"),
        HistoryObservation(
            observation_id="OBS-FUTURE",
            invoice_id="INV-FUTURE",
            observed_at=TODAY,
            document_type="invoice",
            net_line_total=Decimal("2"),
        ),
        HistoryObservation(
            observation_id="OBS-LINE-PREFERRED",
            invoice_id="INV-LINE-PREFERRED",
            observed_at=TODAY - timedelta(days=3),
            document_type="invoice",
            net_line_total=Decimal("100"),
            net_unit_price=Decimal("2"),
            quantity=Decimal("50"),
        ),
    )
    stats = historical_statistics(observations, as_of_date=TODAY)

    assert stats.eligible_count == 4
    assert stats.excluded_count == 2
    assert dict(stats.excluded_reasons) == {
        "estimate_or_non_invoice": 1,
        "not_past_observation": 1,
    }
    assert stats.weighted_median_line_net == Decimal("100.00")
    assert stats.line_total_preferred_count == 4


def test_history_exposes_line_and_unit_weighted_medians() -> None:
    observations = tuple(
        HistoryObservation(
            observation_id=f"OBS-{index}",
            invoice_id=f"INV-{index}",
            observed_at=TODAY - timedelta(days=30),
            document_type="invoice",
            net_line_total=Decimal(line_total),
            net_unit_price=Decimal(unit_price),
            quantity=Decimal("10"),
            unit="each",
        )
        for index, (line_total, unit_price) in enumerate(
            (("40", "4"), ("50", "5"), ("60", "6")), start=1
        )
    )
    stats = historical_statistics(observations, as_of_date=TODAY)
    assert stats.weighted_median_line_net == Decimal("50.00")
    assert stats.weighted_median_unit_net == Decimal("5.00")
    assert stats.line_total_preferred_count == 3


def test_history_is_weak_below_three_and_ontology_takes_over() -> None:
    result = compare_line(
        line=_line("weak", "150"),
        ontology=_ontology("100"),
        history_observations=(_history("50", 1), _history("60", 2)),
    )
    assert result.historical_expected_net is not None
    assert result.history_reliable is False
    assert result.selected_benchmark_net == Decimal("100.00")
    assert result.benchmark_source == BenchmarkSource.ONTOLOGY
    assert "HISTORY_SAMPLE_WEAK" in result.review_flags
    assert result.review_required is False


def test_half_life_is_365_point_25_days() -> None:
    one_year = recency_weight(age_days=365)
    assert Decimal("0.49") < one_year < Decimal("0.51")


def test_minimum_gate_requires_both_five_pounds_and_five_percent() -> None:
    amount_only = compare_line(line=_line("amount", "200"), ontology=_ontology("195"))
    percent_only = compare_line(line=_line("percent", "80"), ontology=_ontology("76"))
    exact_gate = compare_line(line=_line("exact", "100"), ontology=_ontology("95"))

    assert amount_only.challenge_amount_net == Decimal("0.00")
    assert amount_only.gate_passed is False
    assert percent_only.challenge_amount_net == Decimal("0.00")
    assert percent_only.gate_passed is False
    assert exact_gate.challenge_amount_net == Decimal("5.00")
    assert exact_gate.gate_passed is True
    assert exact_gate.severity == ChallengeSeverity.AMBER


def test_positive_only_invoice_aggregation_is_exactly_seventy_five() -> None:
    rows = (
        compare_line(line=_line("a", "100"), ontology=_ontology("75")),
        compare_line(line=_line("b", "100"), ontology=_ontology("90")),
        compare_line(line=_line("c", "100"), ontology=_ontology("100")),
        compare_line(line=_line("d", "100"), ontology=_ontology("60")),
        compare_line(line=_line("under", "80"), ontology=_ontology("95")),
    )

    summary = aggregate_challenges(rows)
    assert [row.challenge_amount_net for row in rows] == [
        Decimal("25.00"),
        Decimal("10.00"),
        Decimal("0.00"),
        Decimal("40.00"),
        Decimal("0.00"),
    ]
    assert summary.challenge_amount_net == Decimal("75.00")
    assert summary.challenge_price_net == Decimal("405.00")


def test_red_is_amount_or_percentage_after_gate() -> None:
    amount_red = compare_line(line=_line("amount-red", "200"), ontology=_ontology("175"))
    percentage_red = compare_line(line=_line("pct-red", "20"), ontology=_ontology("14"))
    assert amount_red.severity == ChallengeSeverity.RED
    assert percentage_red.challenge_amount_net == Decimal("6.00")
    assert percentage_red.severity == ChallengeSeverity.RED


def test_mot_has_zero_vat_impact() -> None:
    result = compare_line(
        line=_line(
            "mot",
            "60.00",
            description="Class 4 MOT test",
            quantity="1",
            unit="test",
            is_mot=True,
        ),
        ontology=_ontology("54.85", scope="test"),
    )
    assert result.challenge_amount_net == Decimal("5.15")
    assert result.vat_impact == Decimal("0.00")
    assert result.challenge_gross == Decimal("5.15")


def test_lineage_independence_is_explicit() -> None:
    shared = compare_line(
        line=_line("1", "150"),
        ontology=_ontology("100", lineage="same-source"),
        history_observations=tuple(_history("100", i, lineage="same-source") for i in range(3)),
        mapping_confidence=Decimal("1"),
        price_evidence_confidence=Decimal("1"),
    )
    assert shared.source_lineage_independence_known is True
    assert shared.sources_independent is False
    assert "SOURCE_LINEAGE_NOT_INDEPENDENT" in shared.review_flags


def test_challenge_score_is_separate_and_scale_invariant() -> None:
    small = compare_line(
        line=_line("small", "150"),
        ontology=_ontology("100", lineage="ontology"),
        history_observations=tuple(_history("90", i, lineage=f"history-{i}") for i in range(3)),
        mapping_confidence=Decimal("0.82"),
        price_evidence_confidence=Decimal("0.91"),
        fit_confidence=Decimal("0.75"),
    )
    large = compare_line(
        line=_line("large", "1500"),
        ontology=_ontology("1000", lineage="ontology"),
        history_observations=tuple(_history("900", i, lineage=f"history-{i}") for i in range(3)),
        mapping_confidence=Decimal("0.82"),
        price_evidence_confidence=Decimal("0.91"),
        fit_confidence=Decimal("0.75"),
    )
    assert small.mapping_confidence == Decimal("0.82")
    assert small.price_evidence_confidence == Decimal("0.91")
    assert small.challenge_score == large.challenge_score
    assert small.challenge_amount_net != large.challenge_amount_net


def test_mapping_prefers_part_number_then_synonym_then_fuzzy() -> None:
    items = (
        OntologyItem(
            item_id="PART-1",
            canonical_name="Front brake disc set",
            item_type="part",
            unit="set",
            price_scope="set",
            synonyms=("FRT DISC SET",),
            part_numbers=("ABC-123",),
        ),
        OntologyItem(
            item_id="PART-2",
            canonical_name="Rear brake pad set",
            item_type="part",
            unit="set",
            price_scope="set",
        ),
    )

    by_part = retrieve_candidates(
        description="anything", part_number="abc123", ontology_items=items
    )
    by_synonym = retrieve_candidates(description="frt disc set", ontology_items=items)
    fuzzy = retrieve_candidates(
        description="rear brake pads", ontology_items=items, fuzzy_min=Decimal("0.40")
    )

    assert by_part[0].item_id == "PART-1"
    assert by_part[0].match_kind == MatchKind.EXACT_PART_NUMBER
    assert by_synonym[0].match_kind == MatchKind.EXACT_SYNONYM
    assert fuzzy[0].item_id == "PART-2"
    assert fuzzy[0].match_kind == MatchKind.FUZZY


def test_mapping_normalises_common_oil_filter_and_disposal_variants() -> None:
    items = (
        OntologyItem(
            item_id="PART-OIL-FILTER",
            canonical_name="Oil filter",
            item_type="part",
            unit="each",
            price_scope="each",
        ),
        OntologyItem(
            item_id="PART-ENGINE-OIL",
            canonical_name="Engine oil (per litre)",
            item_type="part",
            unit="litre",
            price_scope="litre",
        ),
        OntologyItem(
            item_id="PART-OIL-DISPOSAL",
            canonical_name="Oil & filter / environmental disposal charge",
            item_type="part",
            unit="job",
            price_scope="job",
        ),
    )

    filter_aliases = (
        "Oil Filter",
        "OL Filter",
        "Oil_Fil",
        "Engine Oil Filter",
        "Oil Filter Element",
        "Filter - Oil",
        "OIL-FLTR",
        "Oilfilter",
    )
    disposal_aliases = (
        "Oil Disposal",
        "Oil and Filter Disposal",
        "Waste Oil Disposal",
        "Environmental Oil Disposal",
        "Oil/Filter Disposal Charge",
        "Oil Disposal Fee",
        "Waste Oil and Filter",
        "Oil & Filter Disposal",
    )

    assert {
        retrieve_candidates(description=alias, ontology_items=items)[0].item_id
        for alias in filter_aliases
    } == {"PART-OIL-FILTER"}
    assert {
        retrieve_candidates(description=alias, ontology_items=items)[0].item_id
        for alias in disposal_aliases
    } == {"PART-OIL-DISPOSAL"}
