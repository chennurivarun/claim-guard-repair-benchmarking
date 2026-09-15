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
    _assessment_line_benchmarks,
    _historical_p90_evidence,
    _is_invoice_header_description,
    _mapped_external_reference,
    _mapped_external_reference_candidate,
    _uploaded_batch_benchmark_dashboard,
    _uploaded_line_p90_benchmarks,
    _verified_external_observations,
    _verified_external_price,
)


def test_invoice_table_heading_is_not_a_repair_description() -> None:
    assert _is_invoice_header_description("Invoice Number Date / / ) : Mileage : Job Value")
    assert not _is_invoice_header_description("MOT Test class IV")


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


def test_historical_p90_falls_back_to_same_item_when_vehicle_is_missing() -> None:
    comparables = [
        {
            "id": f"history-{index}",
            "source_type": "historical",
            "price_net": price,
            "vehicle": {"make": make, "model": model},
            "comparability_metadata": {"source_group": "historical_claim"},
            "provenance": {"claim_reference": f"INV-{index}"},
        }
        for index, (price, make, model) in enumerate(
            [
                ("100.00", "BMW", "3 Series"),
                ("120.00", "Audi", "A4"),
                ("140.00", "Ford", "Focus"),
            ],
            start=1,
        )
    ]

    evidence = _historical_p90_evidence(
        comparables,
        SimpleNamespace(make=None, model=None),
        source_group="historical_claim",
    )

    assert evidence is not None
    assert evidence.value == Decimal("136.00")
    assert evidence.historical_count == 3
    assert evidence.method == "Historical claims P90 (all vehicle categories fallback)"


def test_workbook_reference_remains_visible_and_eligible_under_current_policy() -> None:
    item = SimpleNamespace(
        reference_price_net=Decimal("138.00"),
        source_url_or_ref="ontology_seed.xlsx#full-service",
        price_source="Reference price bank",
    )
    candidate = _mapped_external_reference_candidate(item)

    assert candidate is not None
    assert candidate["price_net"] == Decimal("138.00")
    assert candidate["source_reference"] == "ontology_seed.xlsx#full-service"
    assert candidate["source_title"] == "Reference price bank"
    assert _mapped_external_reference(item) == candidate


def test_invoice_line_seed_is_not_reused_as_external_price_evidence() -> None:
    evidence = _mapped_external_reference(
        SimpleNamespace(
            reference_price_net=Decimal("475.00"),
            source_url_or_ref="invoice-line:line-123",
            price_source="auto_unmatched_invoice_line",
        )
    )

    assert evidence is None


def test_mapped_external_reference_scales_unit_price_to_line_quantity() -> None:
    evidence = _mapped_external_reference(
        SimpleNamespace(
            reference_price_net=Decimal("9.75"),
            source_url_or_ref="https://example.com/engine-oil",
            price_source="Reference price bank",
        ),
        Decimal("4"),
    )

    assert evidence is not None
    assert evidence["unit_price_net"] == Decimal("9.75")
    assert evidence["quantity"] == Decimal("4")
    assert evidence["price_net"] == Decimal("39.00")


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


def test_uploaded_line_p90_uses_same_item_history_when_current_vehicle_is_missing() -> None:
    invoices = []
    lines = []
    for index, price in enumerate(["100.00", "120.00", "140.00"], start=1):
        invoice = SimpleNamespace(
            id=f"invoice-{index}",
            invoice_number=f"INV-{index:03}",
            invoice_date=date(2026, 1, index),
            vehicle=SimpleNamespace(make="BMW", model="3 Series"),
        )
        invoices.append(invoice)
        lines.append(
            SimpleNamespace(
                id=f"line-{index}",
                invoice_id=invoice.id,
                status=ReviewStatus.PENDING,
                line_total_net=price,
                raw_description="Carried Out Full Service",
                normalised_description="carried out full service",
            )
        )
    current_invoice = SimpleNamespace(
        id="invoice-current",
        invoice_number="INV-004",
        invoice_date=date(2026, 1, 4),
        vehicle=SimpleNamespace(make=None, model=None),
    )
    invoices.append(current_invoice)
    lines.append(
        SimpleNamespace(
            id="line-current",
            invoice_id=current_invoice.id,
            status=ReviewStatus.PENDING,
            line_total_net="475.00",
            raw_description="Carried Out Full Service",
            normalised_description="carried out full service",
        )
    )

    result = _uploaded_line_p90_benchmarks(
        {"invoices": invoices, "lines": lines, "mappings": [], "ontology": {}},
        current_invoice=current_invoice,
    )["line-current"]

    assert result["p90"] == 136.0
    assert result["historicalCount"] == 3
    assert result["vehicleScope"] == "all vehicle categories fallback"


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


# --- Task 11: second benchmark from past assessments -----------------------


def _bmw_3_series() -> SimpleNamespace:
    return SimpleNamespace(make="BMW", model="3 Series")


def _assessment_line(
    *, op_id: str, category: str, total_net: str, description: str = "Front Bumper Cover"
) -> SimpleNamespace:
    return SimpleNamespace(
        id=op_id,
        category=category,
        raw_description=description,
        normalised_description=description.casefold(),
        total_net=total_net,
    )


def _section_total_line(
    *, line_id: str, invoice_id: str, line_item_type: str, line_total_net: str
) -> SimpleNamespace:
    return SimpleNamespace(
        id=line_id,
        invoice_id=invoice_id,
        status=ReviewStatus.PENDING,
        line_total_net=line_total_net,
        raw_description=f"Total {line_item_type.title()} Amount",
        normalised_description=f"total {line_item_type} amount",
        is_section_total=True,
        line_item_type=line_item_type,
        raw_category=f"Total {line_item_type.title()} Amount",
    )


def _current_invoice_and_line(
    *, price: str = "500.00", description: str = "Front Bumper Cover", is_section_total: bool = False
) -> tuple[SimpleNamespace, SimpleNamespace]:
    invoice = SimpleNamespace(id="invoice-current", invoice_number="INV-CUR", vehicle=_bmw_3_series())
    line = SimpleNamespace(
        id="line-current",
        invoice_id=invoice.id,
        status=ReviewStatus.PENDING,
        line_total_net=price,
        raw_description=description,
        normalised_description=description.casefold(),
        is_section_total=is_section_total,
        line_item_type="parts",
        raw_category="Parts",
    )
    return invoice, line


def _matching_prior_assessment(
    *, index: int, parts_net: str, op_total_net: str, paired_invoice_id: str | None = None
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """One prior invoice, its matched Total Parts section total, and its assessment."""

    invoice_id = f"invoice-a{index}"
    invoice = SimpleNamespace(id=invoice_id, invoice_number=f"INV-A{index}", vehicle=_bmw_3_series())
    total_line = _section_total_line(
        line_id=f"total-a{index}",
        invoice_id=invoice_id,
        line_item_type="parts",
        line_total_net=parts_net,
    )
    assessment = SimpleNamespace(
        id=f"assessment-a{index}",
        paired_invoice_id=paired_invoice_id or invoice_id,
        assessment_number=f"ASSESS-{index}",
        parts_net=parts_net,
        paint_net=None,
        extras_net=None,
        labour_net=None,
        operations=[
            _assessment_line(op_id=f"op-a{index}", category="parts", total_net=op_total_net)
        ],
    )
    return invoice, total_line, assessment


def test_assessment_benchmark_is_a_distinct_mean_from_the_p90_benchmark() -> None:
    current_invoice, current_line = _current_invoice_and_line()

    p90_invoices = []
    p90_lines = []
    for index, price in enumerate(["400.00", "410.00", "420.00"], start=1):
        invoice = SimpleNamespace(
            id=f"invoice-p{index}",
            invoice_number=f"INV-P{index}",
            invoice_date=None,
            vehicle=_bmw_3_series(),
        )
        p90_invoices.append(invoice)
        p90_lines.append(
            SimpleNamespace(
                id=f"line-p{index}",
                invoice_id=invoice.id,
                status=ReviewStatus.PENDING,
                line_total_net=price,
                raw_description="Front Bumper Cover",
                normalised_description="front bumper cover",
                is_section_total=False,
            )
        )

    assessment_rows = [
        _matching_prior_assessment(index=index, parts_net="1000.00", op_total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    assessment_invoices = [row[0] for row in assessment_rows]
    assessment_total_lines = [row[1] for row in assessment_rows]
    assessments = [row[2] for row in assessment_rows]

    graph = {
        # The P90 helper treats list order as invoice-date order and truncates
        # at the current invoice's index, so it must sort after its own priors.
        "invoices": [*p90_invoices, current_invoice, *assessment_invoices],
        "lines": [current_line, *p90_lines, *assessment_total_lines],
        "mappings": [],
        "ontology": {},
        "assessments": assessments,
    }

    p90_result = _uploaded_line_p90_benchmarks(graph, current_invoice=current_invoice)["line-current"]
    assessment_result = _assessment_line_benchmarks(graph, current_invoice=current_invoice)[
        "line-current"
    ]

    assert p90_result["method"] == "Interpolated percentile (PERCENTILE.INC)"
    assert assessment_result["method"] == "Past assessments mean (same make and model)"
    assert assessment_result["value"] == 310.0
    assert assessment_result["sampleCount"] == 3
    assert assessment_result["value"] != p90_result["p90"]

    # Assessment rows never leak into the invoice-based P90 population.
    assert all("assessmentOperationId" not in row for row in p90_result["observations"])
    assert {row["lineId"] for row in p90_result["observations"]} == {
        "line-p1",
        "line-p2",
        "line-p3",
    }


def test_assessment_benchmark_excludes_rows_whose_section_total_does_not_match() -> None:
    current_invoice, current_line = _current_invoice_and_line()

    matching = [
        _matching_prior_assessment(index=index, parts_net="1000.00", op_total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    # A fourth prior claim whose invoice total does not match its assessment's
    # parts total -- its row must never enter the population.
    mismatched_invoice, mismatched_total_line, mismatched_assessment = _matching_prior_assessment(
        index=4, parts_net="1000.00", op_total_net="999.00"
    )
    mismatched_total_line = SimpleNamespace(
        **{**mismatched_total_line.__dict__, "line_total_net": "1500.00"}
    )

    invoices = [current_invoice, *(row[0] for row in matching), mismatched_invoice]
    lines = [current_line, *(row[1] for row in matching), mismatched_total_line]
    assessments = [*(row[2] for row in matching), mismatched_assessment]

    graph = {
        "invoices": invoices,
        "lines": lines,
        "mappings": [],
        "ontology": {},
        "assessments": assessments,
    }

    result = _assessment_line_benchmarks(graph, current_invoice=current_invoice)["line-current"]

    assert result["sampleCount"] == 3
    assert all(row["total"] != 999.0 for row in result["observations"])
    assert all(row["assessmentId"] != "assessment-a4" for row in result["observations"])


def test_assessment_benchmark_excludes_the_current_invoice_own_paired_assessment() -> None:
    current_invoice, current_line = _current_invoice_and_line()

    matching = [
        _matching_prior_assessment(index=index, parts_net="1000.00", op_total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    # A fourth assessment paired to the CURRENT invoice -- structurally
    # eligible (same section match, same vehicle) but must be excluded solely
    # because it is this invoice's own assessment.
    own_invoice, own_total_line, own_assessment = _matching_prior_assessment(
        index=5,
        parts_net="1000.00",
        op_total_net="999.00",
        paired_invoice_id=current_invoice.id,
    )

    invoices = [current_invoice, *(row[0] for row in matching)]
    lines = [current_line, *(row[1] for row in matching), own_total_line]
    assessments = [*(row[2] for row in matching), own_assessment]

    graph = {
        "invoices": invoices,
        "lines": lines,
        "mappings": [],
        "ontology": {},
        "assessments": assessments,
    }

    result = _assessment_line_benchmarks(graph, current_invoice=current_invoice)["line-current"]

    assert result["sampleCount"] == 3
    assert all(row["total"] != 999.0 for row in result["observations"])
    assert all(row["assessmentId"] != "assessment-a5" for row in result["observations"])


def test_assessment_benchmark_unavailable_below_minimum_count() -> None:
    current_invoice, current_line = _current_invoice_and_line()

    matching = [
        _matching_prior_assessment(index=index, parts_net="1000.00", op_total_net=total)
        for index, total in enumerate(["300.00", "310.00"], start=1)
    ]

    graph = {
        "invoices": [current_invoice, *(row[0] for row in matching)],
        "lines": [current_line, *(row[1] for row in matching)],
        "mappings": [],
        "ontology": {},
        "assessments": [row[2] for row in matching],
    }

    result = _assessment_line_benchmarks(graph, current_invoice=current_invoice)

    assert "line-current" not in result


def test_assessment_benchmark_never_computed_for_a_section_total_row() -> None:
    current_invoice, current_line = _current_invoice_and_line(is_section_total=True)

    matching = [
        _matching_prior_assessment(index=index, parts_net="1000.00", op_total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]

    graph = {
        "invoices": [current_invoice, *(row[0] for row in matching)],
        "lines": [current_line, *(row[1] for row in matching)],
        "mappings": [],
        "ontology": {},
        "assessments": [row[2] for row in matching],
    }

    result = _assessment_line_benchmarks(graph, current_invoice=current_invoice)

    assert "line-current" not in result
