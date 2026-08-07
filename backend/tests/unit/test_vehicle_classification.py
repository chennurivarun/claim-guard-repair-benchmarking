from dataclasses import dataclass

import pytest

from app.services.vehicle_classification import (
    select_vehicle_category_history,
    validate_vehicle_classification,
)


@dataclass
class VehicleRecord:
    official_vehicle_class: str | None = None
    bodywork_code: str | None = None
    market_segment: str | None = None
    classification_source: str | None = None


def test_valid_m1_bodywork_classification_has_business_label() -> None:
    classification = validate_vehicle_classification(
        official_vehicle_class="m1",
        bodywork_code="ab",
        market_segment=None,
        classification_source="V5C",
    )

    assert classification.label == "M1 / AB Hatchback"


def test_classification_requires_a_source_and_valid_parent_class() -> None:
    with pytest.raises(ValueError, match="require official vehicle class M1"):
        validate_vehicle_classification(
            official_vehicle_class="N1",
            bodywork_code="AB",
            market_segment=None,
            classification_source="V5C",
        )
    with pytest.raises(ValueError, match="source is required"):
        validate_vehicle_classification(
            official_vehicle_class="M1",
            bodywork_code="AB",
            market_segment=None,
            classification_source=None,
        )


def test_category_selection_uses_exact_class_with_enough_history() -> None:
    current = VehicleRecord("M1", "AB", None, "V5C")
    matching = [VehicleRecord("M1", "AB", None, "V5C") for _ in range(3)]
    other = VehicleRecord("N1", None, None, "V5C")

    selected, metadata = select_vehicle_category_history(
        [*matching, other],
        current_vehicle=current,
    )

    assert selected == matching
    assert metadata["category_specific"] is True
    assert metadata["vehicle_class_used"] == "M1 / AB Hatchback"


def test_category_selection_falls_back_when_sample_is_too_small() -> None:
    current = VehicleRecord("M1", "AB", None, "V5C")
    rows = [
        VehicleRecord("M1", "AB", None, "V5C"),
        VehicleRecord("N1", None, None, "V5C"),
    ]

    selected, metadata = select_vehicle_category_history(rows, current_vehicle=current)

    assert selected == rows
    assert metadata["category_specific"] is False
    assert metadata["category_fallback_reason"] == ("Only 1 matching observation(s); minimum is 3.")
