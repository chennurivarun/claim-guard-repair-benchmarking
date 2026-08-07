from app.services.comparison_workflow import _type_compatible


def test_labour_invoice_line_can_map_to_service_operation() -> None:
    assert _type_compatible("labour", "service") is True


def test_part_invoice_line_cannot_map_to_service_operation() -> None:
    assert _type_compatible("part", "service") is False


def test_matching_types_remain_compatible() -> None:
    assert _type_compatible("part", "part") is True
