from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domain.normalisation import normalise_description
from app.enums import (
    DocumentRole,
    ExtractionMethod,
    InvoiceDocumentRole,
    LineItemKind,
    PriceScope,
    ReviewStatus,
    UploadStatus,
)
from app.init_db import initialize_database
from app.models import (
    AssessmentOperation,
    Case,
    Document,
    EngineerAssessment,
    Invoice,
    InvoiceLineItem,
    Vehicle,
)
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
    build_case_result,
)
from app.services.engineer_assessment import normalise_operation


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
#
# Every fixture below normalises its two sides the way production does: an
# invoice line's ``normalised_description`` comes from ``normalise_description``
# and an assessment operation's from ``normalise_operation``.  They are
# deliberately different functions -- the alias-collapsing one belongs to
# operation matching -- so a fixture that used one function on both sides would
# hide exactly the bug this benchmark has to avoid.

#: Sentinel: pair the assessment to the invoice built alongside it.
_OWN_INVOICE = "__own_invoice__"


def _bmw_3_series() -> SimpleNamespace:
    return SimpleNamespace(make="BMW", model="3 Series")


def _operation(
    *, op_id: str, category: str, description: str, total_net: str | None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=op_id,
        category=category,
        raw_description=description,
        normalised_description=normalise_operation(description),
        total_net=total_net,
    )


def _invoice_line(
    *,
    line_id: str,
    invoice_id: str,
    description: str,
    price: str,
    is_section_total: bool = False,
    line_item_type: str = "parts",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=line_id,
        invoice_id=invoice_id,
        status=ReviewStatus.PENDING,
        line_total_net=price,
        raw_description=description,
        normalised_description=normalise_description(description),
        is_section_total=is_section_total,
        line_item_type=line_item_type,
        raw_category=description if is_section_total else line_item_type.title(),
    )


def _current_invoice() -> SimpleNamespace:
    return SimpleNamespace(
        id="invoice-current",
        invoice_number="INV-CUR",
        invoice_date=None,
        vehicle=_bmw_3_series(),
        parts_net=None,
        labour_net=None,
        paint_net=None,
        other_net=None,
    )


def _prior_pair(
    *,
    index: int,
    operations: list[SimpleNamespace],
    invoice_totals: dict[str, str] | None = None,
    assessment_totals: dict[str, str] | None = None,
    vehicle: SimpleNamespace | None = None,
    paired_invoice_id: str | None = _OWN_INVOICE,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """One prior invoice and the engineer assessment paired to it.

    The section totals live on the invoice and assessment rows themselves --
    ``Invoice.parts_net`` / ``labour_net`` / ``paint_net`` / ``other_net``
    against the assessment's ``parts_net`` / ``labour_net`` / ``paint_net`` /
    ``extras_net`` -- because that is what the benchmark reads, for an
    itemised prior exactly as for a rolled-up one.
    """

    invoice_totals = invoice_totals or {}
    assessment_totals = assessment_totals or {}
    invoice = SimpleNamespace(
        id=f"invoice-a{index}",
        invoice_number=f"INV-A{index}",
        invoice_date=None,
        vehicle=vehicle or _bmw_3_series(),
        parts_net=invoice_totals.get("parts_net"),
        labour_net=invoice_totals.get("labour_net"),
        paint_net=invoice_totals.get("paint_net"),
        other_net=invoice_totals.get("other_net"),
    )
    assessment = SimpleNamespace(
        id=f"assessment-a{index}",
        assessment_number=f"ASSESS-{index}",
        paired_invoice_id=(
            invoice.id if paired_invoice_id == _OWN_INVOICE else paired_invoice_id
        ),
        parts_net=assessment_totals.get("parts_net"),
        labour_net=assessment_totals.get("labour_net"),
        paint_net=assessment_totals.get("paint_net"),
        extras_net=assessment_totals.get("extras_net"),
        operations=operations,
    )
    return invoice, assessment


def _matched_parts_pair(
    *, index: int, total_net: str, description: str = "O/S Front Door Skin"
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """A prior pair whose parts section agrees, carrying one parts operation."""

    return _prior_pair(
        index=index,
        operations=[
            _operation(
                op_id=f"op-a{index}",
                category="parts",
                description=description,
                total_net=total_net,
            )
        ],
        invoice_totals={"parts_net": "1000.00"},
        assessment_totals={"parts_net": "1000.00"},
    )


def _assessment_graph(
    *,
    current_invoice: SimpleNamespace,
    current_lines: list[SimpleNamespace],
    pairs: list[tuple[SimpleNamespace, SimpleNamespace]],
    prior_lines: list[SimpleNamespace] | None = None,
    extra_invoices: list[SimpleNamespace] | None = None,
) -> dict:
    return {
        "invoices": [
            current_invoice,
            *(pair[0] for pair in pairs),
            *(extra_invoices or []),
        ],
        "lines": [*current_lines, *(prior_lines or [])],
        "mappings": [],
        "ontology": {},
        "assessments": [pair[1] for pair in pairs],
    }


def test_assessment_benchmark_matches_an_identically_printed_description() -> None:
    # The same printed wording reads two ways: "offside front door skin" as an
    # invoice line, "o s front door skin" as an operation. Keying assessment
    # rows in the operation space would never match the invoice at all.
    description = "O/S Front Door Skin"
    assert normalise_description(description) != normalise_operation(description)

    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description=description,
        price="500.00",
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)["line-current"]

    assert result["sampleCount"] == 3
    assert result["value"] == 310.0
    assert result["category"] == normalise_description(description)
    assert {row["sectionCategory"] for row in result["observations"]} == {"parts"}


def test_assessment_benchmark_does_not_average_labour_and_paint_for_one_part() -> None:
    # Both descriptions collapse to the single alias "front bumper remove
    # refit", which is why the operation space cannot be the benchmark key.
    assert normalise_operation("R/R Front Bumper") == normalise_operation("Paint Front Bumper")
    assert normalise_description("R/R Front Bumper") != normalise_description(
        "Paint Front Bumper"
    )

    current = _current_invoice()
    labour_line = _invoice_line(
        line_id="line-labour",
        invoice_id=current.id,
        description="R/R Front Bumper",
        price="150.00",
        line_item_type="labour",
    )
    paint_line = _invoice_line(
        line_id="line-paint",
        invoice_id=current.id,
        description="Paint Front Bumper",
        price="60.00",
        line_item_type="paint",
    )
    pairs = [
        _prior_pair(
            index=index,
            operations=[
                _operation(
                    op_id=f"op-labour-{index}",
                    category="labour",
                    description="R/R Front Bumper",
                    total_net=labour_total,
                ),
                _operation(
                    op_id=f"op-paint-{index}",
                    category="paint",
                    description="Paint Front Bumper",
                    total_net=paint_total,
                ),
            ],
            invoice_totals={"labour_net": "900.00"},
            assessment_totals={"labour_net": "900.00"},
        )
        for index, (labour_total, paint_total) in enumerate(
            [("100.00", "40.00"), ("110.00", "44.00"), ("120.00", "48.00")], start=1
        )
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[labour_line, paint_line], pairs=pairs
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)

    labour = result["line-labour"]
    paint = result["line-paint"]
    assert labour["sampleCount"] == 3
    assert labour["value"] == 110.0
    assert {row["description"] for row in labour["observations"]} == {"R/R Front Bumper"}
    assert paint["sampleCount"] == 3
    assert paint["value"] == 44.0
    assert {row["description"] for row in paint["observations"]} == {"Paint Front Bumper"}
    # Averaged together, all six rows would have produced one 77.00 benchmark.
    assert labour["value"] != 77.0
    assert paint["value"] != 77.0


def test_assessment_benchmark_drops_paint_when_paint_materials_disagrees() -> None:
    current = _current_invoice()
    labour_line = _invoice_line(
        line_id="line-labour",
        invoice_id=current.id,
        description="R/R Front Bumper",
        price="150.00",
        line_item_type="labour",
    )
    paint_line = _invoice_line(
        line_id="line-paint",
        invoice_id=current.id,
        description="Paint Front Bumper",
        price="60.00",
        line_item_type="paint",
    )
    pairs = [
        _prior_pair(
            index=index,
            operations=[
                _operation(
                    op_id=f"op-labour-{index}",
                    category="labour",
                    description="R/R Front Bumper",
                    total_net=labour_total,
                ),
                _operation(
                    op_id=f"op-paint-{index}",
                    category="paint",
                    description="Paint Front Bumper",
                    total_net=paint_total,
                ),
            ],
            # "Total Labour" agrees, but the invoice's own paint & materials
            # total contradicts the assessment: paintwork is not comparable.
            invoice_totals={"labour_net": "900.00", "paint_net": "200.00"},
            assessment_totals={"labour_net": "900.00", "paint_net": "250.00"},
        )
        for index, (labour_total, paint_total) in enumerate(
            [("100.00", "40.00"), ("110.00", "44.00"), ("120.00", "48.00")], start=1
        )
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[labour_line, paint_line], pairs=pairs
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)

    assert result["line-labour"]["sampleCount"] == 3
    assert "line-paint" not in result


def test_assessment_benchmark_excludes_an_operation_headed_total() -> None:
    lookalike = "Total Parts Amount"
    current = _current_invoice()
    legit_line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    # A misread "Total ..." heading on the current invoice as well, so the
    # exclusion is visible as a missing benchmark rather than only a missing row.
    lookalike_line = _invoice_line(
        line_id="line-lookalike",
        invoice_id=current.id,
        description=lookalike,
        price="900.00",
    )
    pairs = []
    for index, (legit_total, total_row) in enumerate(
        [("300.00", "900.00"), ("310.00", "910.00"), ("320.00", "920.00")], start=1
    ):
        pairs.append(
            _prior_pair(
                index=index,
                operations=[
                    _operation(
                        op_id=f"op-a{index}",
                        category="parts",
                        description="O/S Front Door Skin",
                        total_net=legit_total,
                    ),
                    # Not equal to the printed parts_net, so only the "Total "
                    # wording can catch it.
                    _operation(
                        op_id=f"op-total-{index}",
                        category="parts",
                        description=lookalike,
                        total_net=total_row,
                    ),
                ],
                invoice_totals={"parts_net": "1000.00"},
                assessment_totals={"parts_net": "1000.00"},
            )
        )
    graph = _assessment_graph(
        current_invoice=current, current_lines=[legit_line, lookalike_line], pairs=pairs
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)

    assert result["line-current"]["sampleCount"] == 3
    assert "line-lookalike" not in result


def test_assessment_benchmark_excludes_an_operation_repeating_its_section_total() -> None:
    lookalike = "Parts Amount"
    current = _current_invoice()
    legit_line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    lookalike_line = _invoice_line(
        line_id="line-lookalike",
        invoice_id=current.id,
        description=lookalike,
        price="1000.00",
    )
    # The wording gives nothing away; the row is a total only because it
    # repeats the assessment's own printed parts_net.
    assert not normalise_description(lookalike).startswith("total ")
    pairs = [
        _prior_pair(
            index=index,
            operations=[
                _operation(
                    op_id=f"op-a{index}",
                    category="parts",
                    description="O/S Front Door Skin",
                    total_net=legit_total,
                ),
                _operation(
                    op_id=f"op-total-{index}",
                    category="parts",
                    description=lookalike,
                    total_net="1000.00",
                ),
            ],
            invoice_totals={"parts_net": "1000.00"},
            assessment_totals={"parts_net": "1000.00"},
        )
        for index, legit_total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[legit_line, lookalike_line], pairs=pairs
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)

    assert result["line-current"]["sampleCount"] == 3
    assert "line-lookalike" not in result


def test_assessment_benchmark_admits_fully_itemised_priors_from_stored_totals() -> None:
    """Three itemised priors, no ``is_section_total`` row anywhere, n=3."""

    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    # Each prior itemises its parts: 600 + 400 = the 1000.00 stored parts_net.
    prior_lines = [
        row
        for index, (invoice, _assessment) in enumerate(pairs, start=1)
        for row in (
            _invoice_line(
                line_id=f"line-a{index}-1",
                invoice_id=invoice.id,
                description="O/S Front Door Skin",
                price="600.00",
            ),
            _invoice_line(
                line_id=f"line-a{index}-2",
                invoice_id=invoice.id,
                description="Front Wing",
                price="400.00",
            ),
        )
    ]
    graph = _assessment_graph(
        current_invoice=current,
        current_lines=[line],
        pairs=pairs,
        prior_lines=prior_lines,
    )
    assert not any(row.is_section_total for row in graph["lines"])

    result = _assessment_line_benchmarks(graph, current_invoice=current)["line-current"]

    assert result["sampleCount"] == 3
    assert result["value"] == 310.0


def test_assessment_benchmark_excludes_a_prior_whose_stored_total_disagrees() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    # A fourth prior billed 1500.00 of parts against an assessed 1000.00.
    pairs.append(
        _prior_pair(
            index=4,
            operations=[
                _operation(
                    op_id="op-a4",
                    category="parts",
                    description="O/S Front Door Skin",
                    total_net="999.00",
                )
            ],
            invoice_totals={"parts_net": "1500.00"},
            assessment_totals={"parts_net": "1000.00"},
        )
    )
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)["line-current"]

    assert result["sampleCount"] == 3
    assert all(row["assessmentId"] != "assessment-a4" for row in result["observations"])


def test_assessment_benchmark_requires_the_same_make_and_model() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _prior_pair(
            index=index,
            operations=[
                _operation(
                    op_id=f"op-a{index}",
                    category="parts",
                    description="O/S Front Door Skin",
                    total_net=total,
                )
            ],
            invoice_totals={"parts_net": "1000.00"},
            assessment_totals={"parts_net": "1000.00"},
            vehicle=SimpleNamespace(make="Audi", model="A4"),
        )
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    assert _assessment_line_benchmarks(graph, current_invoice=current) == {}


def test_assessment_benchmark_ignores_an_unpaired_assessment() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _prior_pair(
            index=index,
            operations=[
                _operation(
                    op_id=f"op-a{index}",
                    category="parts",
                    description="O/S Front Door Skin",
                    total_net=total,
                )
            ],
            invoice_totals={"parts_net": "1000.00"},
            assessment_totals={"parts_net": "1000.00"},
            paired_invoice_id=None,
        )
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    assert _assessment_line_benchmarks(graph, current_invoice=current) == {}


def test_assessment_benchmark_excludes_the_current_invoice_own_paired_assessment() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    # Structurally eligible -- same vehicle, matched section -- and excluded
    # solely because it is this invoice's own assessment.
    own_invoice, own_assessment = _prior_pair(
        index=5,
        operations=[
            _operation(
                op_id="op-a5",
                category="parts",
                description="O/S Front Door Skin",
                total_net="999.00",
            )
        ],
        invoice_totals={"parts_net": "1000.00"},
        assessment_totals={"parts_net": "1000.00"},
        paired_invoice_id=current.id,
    )
    graph = _assessment_graph(
        current_invoice=current,
        current_lines=[line],
        pairs=[*pairs, (own_invoice, own_assessment)],
    )

    result = _assessment_line_benchmarks(graph, current_invoice=current)["line-current"]

    assert result["sampleCount"] == 3
    assert all(row["total"] != 999.0 for row in result["observations"])


def test_assessment_benchmark_excludes_an_operation_without_a_total() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00"], start=1)
    ]
    pairs.append(
        _prior_pair(
            index=3,
            operations=[
                _operation(
                    op_id="op-a3",
                    category="parts",
                    description="O/S Front Door Skin",
                    total_net=None,
                )
            ],
            invoice_totals={"parts_net": "1000.00"},
            assessment_totals={"parts_net": "1000.00"},
        )
    )
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    # Two priced rows survive, which is below the minimum of three.
    assert "line-current" not in _assessment_line_benchmarks(graph, current_invoice=current)


def test_assessment_benchmark_unavailable_below_minimum_count() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00"], start=1)
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    assert "line-current" not in _assessment_line_benchmarks(graph, current_invoice=current)


def test_assessment_benchmark_never_computed_for_a_section_total_row() -> None:
    current = _current_invoice()
    line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
        is_section_total=True,
    )
    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    graph = _assessment_graph(
        current_invoice=current, current_lines=[line], pairs=pairs
    )

    assert "line-current" not in _assessment_line_benchmarks(graph, current_invoice=current)


def test_assessment_benchmark_is_a_distinct_mean_from_the_p90_benchmark() -> None:
    current = _current_invoice()
    current_line = _invoice_line(
        line_id="line-current",
        invoice_id=current.id,
        description="O/S Front Door Skin",
        price="500.00",
    )

    # The P90 helper reads list order as invoice-date order and truncates at
    # the current invoice, so its priors must sort before it.
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
            _invoice_line(
                line_id=f"line-p{index}",
                invoice_id=invoice.id,
                description="O/S Front Door Skin",
                price=price,
            )
        )

    pairs = [
        _matched_parts_pair(index=index, total_net=total)
        for index, total in enumerate(["300.00", "310.00", "320.00"], start=1)
    ]
    graph = {
        "invoices": [*p90_invoices, current, *(pair[0] for pair in pairs)],
        "lines": [current_line, *p90_lines],
        "mappings": [],
        "ontology": {},
        "assessments": [pair[1] for pair in pairs],
    }

    p90_result = _uploaded_line_p90_benchmarks(graph, current_invoice=current)["line-current"]
    assessment_result = _assessment_line_benchmarks(graph, current_invoice=current)[
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


# --- Payload: informational only, and it must not move the price decision ---

PAST_ASSESSMENT_CASE = "CG-PAST-ASSESSMENTS"
PAST_ASSESSMENT_DESCRIPTION = "O/S Front Door Skin"


def _past_assessment_case(session: Session) -> list[Invoice]:
    """Three priors (invoice + paired assessment) and one current invoice."""

    case = Case(case_reference=PAST_ASSESSMENT_CASE, created_by="pytest.handler")
    session.add(case)
    session.flush()

    invoices: list[Invoice] = []
    for index in range(1, 5):
        document = Document(
            case_id=case.id,
            document_role=DocumentRole.CURRENT,
            original_filename=f"invoice-{index}.pdf",
            storage_path=f"/tmp/invoice-{index}.pdf",
            sha256=f"invoice{index}".ljust(64, "0")[:64],
            mime_type="application/pdf",
            file_size=100,
            upload_status=UploadStatus.READY,
        )
        vehicle = Vehicle(
            case_id=case.id,
            make="BMW",
            model="3 Series",
            source="pytest",
            verification_status=ReviewStatus.APPROVED,
        )
        session.add_all([document, vehicle])
        session.flush()
        invoice = Invoice(
            case_id=case.id,
            document_id=document.id,
            document_group_id=f"invoice-{index}",
            document_role=InvoiceDocumentRole.INVOICE,
            invoice_number=f"INV-{index}",
            invoice_date=date(2026, 1, index),
            vehicle_id=vehicle.id,
            parts_net="1000.00",
            extraction_method=ExtractionMethod.NATIVE_TEXT,
            review_status=ReviewStatus.APPROVED,
        )
        session.add(invoice)
        session.flush()
        invoices.append(invoice)

    for invoice, price in zip(
        invoices, ["300.00", "310.00", "320.00", "500.00"], strict=True
    ):
        session.add(
            InvoiceLineItem(
                invoice_id=invoice.id,
                sequence_no=1,
                raw_description=PAST_ASSESSMENT_DESCRIPTION,
                normalised_description=normalise_description(PAST_ASSESSMENT_DESCRIPTION),
                item_kind=LineItemKind.PART,
                quantity="1",
                unit="each",
                price_scope=PriceScope.LINE_TOTAL,
                unit_price_net=price,
                line_total_net=price,
                vat_rate="20.00",
                extraction_method=ExtractionMethod.NATIVE_TABLE,
                status=ReviewStatus.APPROVED,
            )
        )
    session.flush()

    for index, (invoice, total) in enumerate(
        zip(invoices[:3], ["200.00", "210.00", "220.00"], strict=True), start=1
    ):
        document = Document(
            case_id=case.id,
            document_role=DocumentRole.CURRENT,
            original_filename=f"assessment-{index}.pdf",
            storage_path=f"/tmp/assessment-{index}.pdf",
            sha256=f"assessment{index}".ljust(64, "1")[:64],
            mime_type="application/pdf",
            file_size=100,
            upload_status=UploadStatus.READY,
        )
        session.add(document)
        session.flush()
        assessment = EngineerAssessment(
            case_id=case.id,
            document_id=document.id,
            paired_invoice_id=invoice.id,
            pair_status="paired",
            assessment_number=f"ASSESS-{index}",
            parts_net="1000.00",
        )
        session.add(assessment)
        session.flush()
        session.add(
            AssessmentOperation(
                assessment_id=assessment.id,
                sequence_no=1,
                category="parts",
                raw_description=PAST_ASSESSMENT_DESCRIPTION,
                normalised_description=normalise_operation(PAST_ASSESSMENT_DESCRIPTION),
                total_net=total,
            )
        )
    session.commit()
    return invoices


def test_past_assessments_block_is_informational_and_leaves_the_decision_alone() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    initialize_database(engine, seed_defaults=False)
    try:
        with Session(engine, expire_on_commit=False) as session:
            invoices = _past_assessment_case(session)
            current_invoice_id = invoices[3].id

            with_source = build_case_result(session, PAST_ASSESSMENT_CASE)
            line = next(
                row
                for row in with_source["lines"]
                if row["invoice_id"] == current_invoice_id
            )
            block = line["price_evidence"]["sources"]["pastAssessments"]

            assert block["available"] is True
            assert block["sampleCount"] == 3
            assert block["valueNet"] == 210.0
            assert block["method"] == "Past assessments mean (same make and model)"
            assert block["configuredWeight"] == block["effectiveWeight"] == 0.0
            assert {row["sectionCategory"] for row in block["observations"]} == {"parts"}
            # A genuinely second benchmark: not the P90 the decision ran on.
            assert block["valueNet"] != float(line["price_decision"]["supported_price_net"])

            for assessment in session.scalars(select(EngineerAssessment)).all():
                session.delete(assessment)
            session.commit()

            without_source = build_case_result(session, PAST_ASSESSMENT_CASE)
            line_without = next(
                row
                for row in without_source["lines"]
                if row["invoice_id"] == current_invoice_id
            )

            assert line_without["price_evidence"]["sources"]["pastAssessments"] == {
                "available": False,
                "eligible": False,
                "valueNet": None,
                "configuredWeight": 0.0,
                "effectiveWeight": 0.0,
                "method": None,
                "scope": None,
                "sampleCount": 0,
                "currentInvoiceExcluded": True,
                "observations": [],
            }
            assert line_without["price_decision"] == line["price_decision"]
            assert [row["price_decision"] for row in without_source["lines"]] == [
                row["price_decision"] for row in with_source["lines"]
            ]
    finally:
        engine.dispose()


def _category_graph(
    prior: list[tuple[str, str, str, bool]],
    current: tuple[str, str, str, bool],
    categories: dict[str, str],
) -> tuple[dict, SimpleNamespace]:
    """``(model, description, price, is_section_total)`` per invoice."""

    rows = [*prior, current]
    invoices, lines = [], []
    for index, (model, description, price, is_total) in enumerate(rows, 1):
        invoice = SimpleNamespace(
            id=f"invoice-{index}",
            invoice_number=f"INV-{index:03}",
            invoice_date=date(2026, 3, index),
            vehicle=SimpleNamespace(make="HYUNDAI", model=model),
        )
        invoices.append(invoice)
        lines.append(
            SimpleNamespace(
                id=f"line-{index}",
                invoice_id=invoice.id,
                status=ReviewStatus.PENDING,
                line_total_net=price,
                raw_description=description,
                normalised_description=normalise_description(description),
                is_section_total=is_total,
            )
        )
    graph = {
        "invoices": invoices,
        "lines": lines,
        "mappings": [],
        "ontology": {},
        "vehicle_categories": {
            invoice.id: categories[row[0]] for invoice, row in zip(invoices, rows, strict=True)
        },
    }
    return graph, invoices[-1]


def test_uploaded_line_p90_scopes_by_vehicle_category_not_exact_model() -> None:
    """The client benchmarks by vehicle category, so "140 SE Nav" and "i30 SE
    Nav" -- one car printed two ways -- share a population, and an SUV does
    not join it."""

    categories = {"140 SE Nav": "Hatchback", "i30 SE Nav": "Hatchback", "Karoq": "SUV"}
    graph, current = _category_graph(
        [
            ("140 SE Nav", "L/R DOOR", "800.00", False),
            ("i30 SE Nav", "L/R DOOR", "820.00", False),
            ("140 SE Nav", "L/R DOOR", "840.00", False),
            ("Karoq", "L/R DOOR", "2000.00", False),
        ],
        ("i30 SE Nav", "L/R DOOR", "900.00", False),
        categories,
    )

    result = _uploaded_line_p90_benchmarks(graph, current_invoice=current)["line-5"]

    assert result["vehicleScope"] == "same vehicle category"
    assert result["historicalCount"] == 3
    assert {row["invoiceNumber"] for row in result["observations"]} == {
        "INV-001",
        "INV-002",
        "INV-003",
    }
    assert result["p90"] == 836.0


def test_uploaded_line_p90_never_benchmarks_a_rolled_up_section_total() -> None:
    categories = {"140 SE Nav": "Hatchback"}
    graph, current = _category_graph(
        [
            ("140 SE Nav", "Total Labour", "2509.20", True),
            ("140 SE Nav", "Total Labour", "2611.41", True),
            ("140 SE Nav", "Total Labour", "2653.01", True),
        ],
        ("140 SE Nav", "Total Labour", "4000.00", True),
        categories,
    )

    assert _uploaded_line_p90_benchmarks(graph, current_invoice=current) == {}
