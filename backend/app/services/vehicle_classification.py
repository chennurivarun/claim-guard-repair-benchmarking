"""Governed UK vehicle classification helpers used by benchmarking.

Regulatory/type-approval classes are kept separate from market segments.  The
module never guesses a class from make/model or an invoice repair description.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.services.vehicle_category_lookup import lookup_vehicle_category

OFFICIAL_VEHICLE_CLASSES = {
    "M1": "Passenger vehicle (up to eight passenger seats)",
    "M2": "Passenger vehicle over eight seats, maximum mass up to 5,000 kg",
    "M3": "Passenger vehicle over eight seats, maximum mass over 5,000 kg",
    "N1": "Light goods vehicle, maximum mass up to 3,500 kg",
    "N2": "Goods vehicle, maximum mass over 3,500 kg and up to 12,000 kg",
    "N3": "Goods vehicle, maximum mass over 12,000 kg",
}

M1_BODYWORK_CODES = {
    "AA": "Saloon",
    "AB": "Hatchback",
    "AC": "Estate",
    "AD": "Coupe",
    "AE": "Convertible",
    "AF": "Multipurpose vehicle",
}


@dataclass(frozen=True, slots=True)
class VehicleClassification:
    official_vehicle_class: str | None
    bodywork_code: str | None
    market_segment: str | None
    classification_source: str | None

    @property
    def label(self) -> str | None:
        if self.official_vehicle_class == "M1" and self.bodywork_code:
            return f"M1 / {self.bodywork_code} {M1_BODYWORK_CODES[self.bodywork_code]}"
        if self.official_vehicle_class == "M1":
            return "M1 Passenger Vehicle"
        if self.official_vehicle_class == "N1":
            return "N1 Light Commercial Vehicle (LCV)"
        if self.official_vehicle_class:
            return self.official_vehicle_class
        if self.market_segment:
            return f"Segment: {self.market_segment}"
        return None


def validate_vehicle_classification(
    *,
    official_vehicle_class: str | None,
    bodywork_code: str | None,
    market_segment: str | None,
    classification_source: str | None,
) -> VehicleClassification:
    official = (official_vehicle_class or "").strip().upper() or None
    bodywork = (bodywork_code or "").strip().upper() or None
    segment = (market_segment or "").strip() or None
    source = (classification_source or "").strip() or None

    if official and official not in OFFICIAL_VEHICLE_CLASSES:
        raise ValueError(f"Unsupported UK type-approval category: {official}")
    if bodywork and bodywork not in M1_BODYWORK_CODES:
        raise ValueError(f"Unsupported M1 bodywork code: {bodywork}")
    if bodywork and official != "M1":
        raise ValueError("AA-AF bodywork codes require official vehicle class M1")
    if (official or bodywork or segment) and not source:
        raise ValueError("A vehicle classification source is required")
    return VehicleClassification(official, bodywork, segment, source)


def classification_from_record(record: Any) -> VehicleClassification:
    return validate_vehicle_classification(
        official_vehicle_class=getattr(record, "official_vehicle_class", None),
        bodywork_code=getattr(record, "bodywork_code", None),
        market_segment=getattr(record, "market_segment", None),
        classification_source=getattr(record, "classification_source", None),
    )


def apply_vehicle_classification(record: Any, classification: VehicleClassification) -> None:
    record.official_vehicle_class = classification.official_vehicle_class
    record.bodywork_code = classification.bodywork_code
    record.market_segment = classification.market_segment
    record.classification_source = classification.classification_source


def normalise_registration(value: str | None) -> str | None:
    normalised = "".join(character for character in (value or "").upper() if character.isalnum())
    return normalised or None


def select_vehicle_category_history(
    rows: list[Any],
    *,
    current_vehicle: Any,
    session: Session | None = None,
    minimum_count: int = 3,
) -> tuple[list[Any], dict[str, Any]]:
    """Prefer an exact verified vehicle category when enough evidence exists."""

    insurance_match = (
        lookup_vehicle_category(
            session,
            make=getattr(current_vehicle, "make", None),
            model=getattr(current_vehicle, "model", None),
        )
        if session is not None and current_vehicle is not None
        else None
    )
    if insurance_match:
        matching = []
        for row in rows:
            row_match = lookup_vehicle_category(
                session,
                make=getattr(row, "vehicle_make", None),
                model=getattr(row, "vehicle_model", None),
            )
            if row_match and row_match.group_range == insurance_match.group_range:
                matching.append(row)
        if len(matching) >= minimum_count:
            label = (
                f"Insurance group {insurance_match.group_range} "
                f"— {insurance_match.group_category}"
            )
            return matching, {
                "vehicle_class_requested": label,
                "vehicle_class_used": label,
                "category_specific": True,
                "category_fallback_reason": None,
                "classification_source": insurance_match.source,
            }

    current = classification_from_record(current_vehicle) if current_vehicle else None
    requested_label = current.label if current else None
    if not requested_label:
        return rows, {
            "vehicle_class_requested": None,
            "vehicle_class_used": "All vehicle categories",
            "category_specific": False,
            "category_fallback_reason": "Current vehicle has no verified classification.",
            "classification_source": (
                insurance_match.source if insurance_match else None
            ),
        }
    matching = [row for row in rows if classification_from_record(row).label == requested_label]
    if len(matching) >= minimum_count:
        return matching, {
            "vehicle_class_requested": requested_label,
            "vehicle_class_used": requested_label,
            "category_specific": True,
            "category_fallback_reason": None,
            "classification_source": current.classification_source,
        }
    return rows, {
        "vehicle_class_requested": requested_label,
        "vehicle_class_used": "All vehicle categories",
        "category_specific": False,
        "category_fallback_reason": (
            f"Only {len(matching)} matching observation(s); minimum is {minimum_count}."
        ),
        "classification_source": current.classification_source,
    }
