from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.enums import ReviewStatus
from app.services.benchmarking import (
    _benchmark_exception,
    _build_repairer_trends,
    _repairer_group_key,
    _rolling_benchmark_exceptions,
    calculate_benchmark_statistics,
    canonical_benchmark_category,
)
from app.services.case_result import (
    _historical_p90_evidence,
    _uploaded_batch_benchmark_dashboard,
    _uploaded_line_p90_benchmarks,
    _verified_external_observations,
    _verified_external_price,
)


def test_benchmark_statistics_include_requested_values_and_no_fake_mode() -> None:
    stats = calculate_benchmark_statistics(
        [Decimal("380"), Decimal("410"), Decimal("420"), Decimal("450"), Decimal("500")]
    )

    assert stats.minimum == Decimal("380.00")
    assert stats.maximum == Decimal("500.00")
    assert stats.mean == Decimal("432.00")
    assert stats.median == Decimal("420.00")
    assert stats.mode is None
    assert stats.percentile_25 == Decimal("410.00")
    assert stats.percentile_75 == Decimal("450.00")
    assert stats.percentile_90 == Decimal("480.00")
    assert stats.outlier_count == 0
    assert stats.count == 5


def test_in_house_p90_aggregates_mixed_synthetic_vehicle_samples() -> None:
    comparable = {
        "id": "history-1",
        "source_type": "historical",
        "price_net": "100.00",
        "vehicle": {"make": "BMW", "model": "3 Series"},
        "comparability_metadata": {"source_group": "in_house"},
        "provenance": {"claim_reference": "INV-1"},
    }

    evidence = _historical_p90_evidence(
        [comparable], SimpleNamespace(make="BMW", model=None), source_group="in_house"
    )

    assert evidence is not None
    assert evidence.value == Decimal("100.00")
    assert evidence.method == "In-house repair-book P90 (mixed synthetic vehicles)"


def test_external_price_uses_lowest_traceable_exact_vehicle_source() -> None:
    comparables = [
        {
            "source_type": "ontology_price",
            "approval_status": "approved",
            "price_net": price,
            "vehicle": {"make": make, "model": model},
            "provenance": {"source_reference": source},
        }
        for price, make, model, source in [
            ("140.00", "BMW", "3 Series", "https://example.com/a"),
            ("125.00", "BMW", "3 Series", "https://example.com/b"),
            ("90.00", "Audi", "A4", "https://example.com/c"),
            ("80.00", "BMW", "3 Series", None),
        ]
    ]
    vehicle = SimpleNamespace(make="BMW", model="3 Series")

    selected = _verified_external_observations(comparables, vehicle)
    assert [row["price_net"] for row in selected] == ["125.00", "140.00"]
    assert _verified_external_price(comparables, vehicle) == Decimal("125.00")
    assert _verified_external_price(comparables, SimpleNamespace(make="BMW", model=None)) is None


def test_benchmark_statistics_calculate_a_mode_only_when_repeated() -> None:
    stats = calculate_benchmark_statistics(
        [Decimal("380"), Decimal("410"), Decimal("410"), Decimal("500")]
    )

    assert stats.mode == Decimal("410.00")


def test_benchmark_statistics_exclude_zero_and_flag_iqr_outliers() -> None:
    stats = calculate_benchmark_statistics(
        [
            Decimal("0"),
            Decimal("100"),
            Decimal("101"),
            Decimal("102"),
            Decimal("103"),
            Decimal("1000"),
        ]
    )

    assert stats.count == 5
    assert stats.outlier_count == 1


def test_p90_uses_interpolated_percentile_requested_by_client() -> None:
    stats = calculate_benchmark_statistics(
        [
            Decimal("4.00"),
            Decimal("4.50"),
            Decimal("4.50"),
            Decimal("5.00"),
            Decimal("5.50"),
            Decimal("6.00"),
            Decimal("6.50"),
            Decimal("7.00"),
        ]
    )

    assert stats.percentile_90 == Decimal("6.65")


def test_oil_disposal_wording_uses_one_benchmark_category() -> None:
    variants = [
        "Oil Disposal",
        "Oil and Filter Disposal",
        "Waste Oil Disposal",
        "Environmental Oil Disposal",
    ]

    assert {canonical_benchmark_category(value) for value in variants} == {"Oil & Filter Disposal"}


def test_p90_exception_respects_percentage_and_minimum_amount_thresholds() -> None:
    observation = SimpleNamespace(
        id="observation-1",
        line_total_net="7.50",
        unit_price_net=None,
        comparability_metadata_json={
            "invoice_number": "INV-009",
            "garage_name": "Example Repairer",
        },
        source_invoice_id=None,
        source_record_id="line-9",
        workshop_category=None,
        raw_description="Oil Disposal Charge",
    )

    assert (
        _benchmark_exception(
            observation,
            percentile_90=Decimal("6.65"),
            threshold_percentage=Decimal("10"),
        )
        is None
    )

    observation.line_total_net = "12.50"
    exception = _benchmark_exception(
        observation,
        percentile_90=Decimal("6.65"),
        threshold_percentage=Decimal("10"),
    )

    assert exception is not None
    assert exception["invoiceNumber"] == "INV-009"
    assert exception["repairer"] == "Example Repairer"
    assert exception["p90"] == 6.65
    assert exception["difference"] == 5.85
    assert exception["percentageAboveP90"] == 88.0
    assert (
        _benchmark_exception(
            observation,
            percentile_90=Decimal("6.65"),
            threshold_percentage=Decimal("90"),
        )
        is None
    )


def test_repairer_graph_groups_names_and_retains_explainable_evidence() -> None:
    first = {
        "observationId": "obs-1",
        "invoiceNumber": "INV-008",
        "repairer": "Northfield Motor Repairs",
        "description": "Oil Filter",
        "amount": 28.0,
        "p90": 18.0,
        "difference": 10.0,
        "percentageAboveP90": 55.6,
        "historicalCount": 7,
    }
    second = {
        **first,
        "observationId": "obs-2",
        "invoiceNumber": "INV-009",
        "repairer": "  northfield   motor repairs ",
        "description": "Oil_Fil",
        "amount": 32.0,
        "difference": 14.0,
        "percentageAboveP90": 77.8,
    }
    repairer_key = _repairer_group_key(first["repairer"])

    trends = _build_repairer_trends(
        {(repairer_key, "PART-OIL-FILTER", "Oil filter"): [first, second]}
    )

    assert len(trends) == 1
    assert trends[0]["repairer"] == "Northfield Motor Repairs"
    assert trends[0]["invoiceCount"] == 2
    assert trends[0]["challengeCount"] == 2
    assert trends[0]["itemCount"] == 1
    assert trends[0]["totalDifference"] == 24.0
    assert trends[0]["maximumDifference"] == 14.0
    assert trends[0]["items"][0]["exceptions"] == [first, second]


def test_dashboard_exceptions_use_only_earlier_invoices() -> None:
    prices = ["4.00", "4.50", "4.50", "5.00", "5.50", "6.00", "6.50", "12.50"]
    start = date(2026, 1, 1)
    observations = [
        SimpleNamespace(
            id=f"observation-{index}",
            invoice_date=start + timedelta(days=index),
            line_total_net=price,
            unit_price_net=None,
            comparability_metadata_json={
                "invoice_number": f"INV-{index:03}",
                "garage_name": "Example Repairer",
            },
            source_invoice_id=None,
            source_record_id=f"line-{index}",
            workshop_category=None,
            raw_description="Oil Disposal Charge",
        )
        for index, price in enumerate(prices, start=1)
    ]

    exceptions = _rolling_benchmark_exceptions(
        observations,
        threshold_percentage=Decimal("10"),
    )

    assert len(exceptions) == 1
    assert exceptions[0]["invoiceNumber"] == "INV-008"
    assert exceptions[0]["historicalCount"] == 7
    assert exceptions[0]["p90"] == 6.2
    assert exceptions[0]["difference"] == 6.3


def test_uploaded_line_p90_excludes_the_current_invoice_and_explains_challenge() -> None:
    prices = ["4.00", "4.50", "4.50", "5.00", "5.50", "6.00", "6.50", "7.00"]
    invoices = []
    lines = []
    start = date(2026, 1, 1)
    for index, price in enumerate(prices, start=1):
        vehicle = SimpleNamespace(make="BMW", model="3 Series")
        invoice = SimpleNamespace(
            id=f"invoice-{index}",
            invoice_number=f"INV-{index:03}",
            invoice_date=start + timedelta(days=index),
            vehicle=vehicle,
        )
        invoices.append(invoice)
        lines.append(
            SimpleNamespace(
                id=f"line-{index}",
                invoice_id=invoice.id,
                status=ReviewStatus.PENDING,
                line_total_net=price,
                raw_description="Oil Disposal",
                normalised_description="oil disposal",
            )
        )
    current_invoice = SimpleNamespace(
        id="invoice-current",
        invoice_number="INV-009",
        invoice_date=start + timedelta(days=20),
        vehicle=SimpleNamespace(make="BMW", model="3 Series"),
    )
    invoices.append(current_invoice)
    lines.append(
        SimpleNamespace(
            id="line-current",
            invoice_id=current_invoice.id,
            status=ReviewStatus.PENDING,
            line_total_net="7.50",
            raw_description="Oil and Filter Waste Disposal",
            normalised_description="oil and filter waste disposal",
        )
    )

    result = _uploaded_line_p90_benchmarks(
        {"invoices": invoices, "lines": lines, "mappings": [], "ontology": {}},
        current_invoice=current_invoice,
    )["line-current"]

    assert result["p90"] == 6.65
    assert result["difference"] == 0.85
    assert result["percentageDifference"] == 12.8
    assert result["decision"] == "Challenge"
    assert result["currentInvoiceExcluded"] is True
    assert len(result["observations"]) == 8
    assert all(row["invoiceNumber"] != "INV-009" for row in result["observations"])


def test_uploaded_dashboard_and_graph_share_the_same_rolling_p90_exceptions() -> None:
    prices = ["4.00", "4.50", "5.00", "12.00", "15.00", "25.00"]
    repairers = [
        "Pilot Garage",
        "Pilot Garage",
        "Pilot Garage",
        "Northfield Motors",
        "Riverside Auto",
        "Metro Service",
    ]
    invoices = []
    lines = []
    start = date(2026, 2, 1)
    for index, (price, repairer) in enumerate(zip(prices, repairers, strict=True), start=1):
        vehicle = SimpleNamespace(make="BMW", model="3 Series")
        invoice = SimpleNamespace(
            id=f"batch-invoice-{index}",
            invoice_number=f"BATCH-{index:03}",
            invoice_date=start + timedelta(days=index),
            supplier_name=repairer,
            vehicle_id=None,
            vehicle=vehicle,
        )
        invoices.append(invoice)
        lines.append(
            SimpleNamespace(
                id=f"batch-line-{index}",
                invoice_id=invoice.id,
                sequence_no=1,
                status=ReviewStatus.PENDING,
                item_kind="part",
                line_total_net=price,
                unit_price_net=price,
                raw_description="Oil Disposal" if index < 4 else "Oil and Filter Disposal",
                normalised_description="oil disposal",
            )
        )

    dashboard = _uploaded_batch_benchmark_dashboard(
        {
            "invoices": invoices,
            "lines": lines,
            "mappings": [],
            "ontology": {},
            "vehicles": {},
        },
        challenge_threshold_pct=10,
    )

    assert dashboard is not None
    benchmark = dashboard["benchmarks"][0]
    assert benchmark["item"] == "Oil & Filter Disposal"
    assert benchmark["invoiceCount"] == 6
    assert benchmark["exceptionCount"] == 3
    assert benchmark["exceptionInvoiceCount"] == 3
    assert [row["invoiceNumber"] for row in benchmark["exceptions"]] == [
        "BATCH-004",
        "BATCH-005",
        "BATCH-006",
    ]
    assert len(benchmark["sourceObservations"]) == 6
    assert {row["repairer"] for row in dashboard["repairerTrends"]} == {
        "Northfield Motors",
        "Riverside Auto",
        "Metro Service",
    }
    graph_exceptions = {
        row["invoiceNumber"]
        for repairer in dashboard["repairerTrends"]
        for item in repairer["items"]
        for row in item["exceptions"]
    }
    assert graph_exceptions == {"BATCH-004", "BATCH-005", "BATCH-006"}
