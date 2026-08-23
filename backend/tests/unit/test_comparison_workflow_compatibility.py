from app.services.comparison_workflow import _type_compatible


def test_labour_invoice_line_can_map_to_service_operation() -> None:
    assert _type_compatible("labour", "service") is True


def test_part_invoice_line_cannot_map_to_service_operation() -> None:
    assert _type_compatible("part", "service") is False


def test_matching_types_remain_compatible() -> None:
    assert _type_compatible("part", "part") is True


def test_unknown_kind_lines_never_match_any_ontology_type() -> None:
    # A2: removing the discard filter means non-benchmarkable lines (item_kind
    # "unknown", no part_number) now reach the comparison workflow inside
    # otherwise-retained invoices. They must never be treated as type-compatible
    # with a governed ontology item, so they cannot pollute price comparisons or
    # (via the mapping -> HistoricalObservation sync) any P90 population.
    assert _type_compatible("unknown", "part") is False
    assert _type_compatible("unknown", "labour") is False
    assert _type_compatible("unknown", "service") is False
    assert _type_compatible("unknown", "unknown") is True  # only if governed data were malformed
