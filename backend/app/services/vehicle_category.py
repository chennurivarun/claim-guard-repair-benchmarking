"""Vehicle category -- the benchmark dimension -- and where it came from.

Spec default D2, in order:

1. ``vehicle_category_lookup`` (the reference catalogue) -> ``lookup``;
2. the configured LLM, asked once per make+model and cached in
   ``vehicle_category_inferences`` -> ``ai``;
3. otherwise ``Unknown`` -> ``unknown``.  Unknown is its own category: it is
   benchmarked within itself and shown, never skipped.

The category is the catalogue's ``body_type`` column (City car, Hatchback,
SUV, ...) -- the body type the client talks about -- not ``group_category``,
which is the insurance-group *price band* (Cheapest ... Supercar) and says
nothing about the shape of the car being repaired.

The make+model passed in is whatever the invoice carries after gap-fill:
formats 1/5/6/7 print no vehicle on the invoice, and the pairing sweep fills
it from the engineer assessment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import benchmark_writing
from app.models import VehicleCategoryInference, VehicleCategoryLookup
from app.services.vehicle_category_lookup import lookup_vehicle_category, normalise_vehicle_name

UNKNOWN_CATEGORY = "Unknown"
SOURCE_LOOKUP = "lookup"
SOURCE_AI = "ai"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class VehicleCategory:
    category: str
    source: str
    #: What matched: the catalogue row, or the model that answered.
    detail: str | None = None


_UNKNOWN = VehicleCategory(UNKNOWN_CATEGORY, SOURCE_UNKNOWN)


def build_vehicle_category_classifier() -> Any:
    """The configured classifier, or ``None`` -- the normal state on a client machine."""

    return benchmark_writing.build_vehicle_category_classifier(get_settings())


def _vocabulary(session: Session) -> list[str]:
    return sorted(
        {
            body_type
            for body_type in session.scalars(select(VehicleCategoryLookup.body_type)).all()
            if body_type
        }
    )


def _cached(session: Session, make_key: str, model_key: str) -> VehicleCategoryInference | None:
    return session.scalar(
        select(VehicleCategoryInference).where(
            VehicleCategoryInference.normalised_make == make_key,
            VehicleCategoryInference.normalised_model == model_key,
        )
    )


def _from_inference(row: VehicleCategoryInference) -> VehicleCategory:
    if not row.category:
        return _UNKNOWN
    return VehicleCategory(row.category, SOURCE_AI, f"{row.provider}:{row.model_id}")


def resolve_vehicle_category(
    session: Session,
    *,
    make: str | None,
    model: str | None,
    allow_ai: bool = True,
) -> VehicleCategory:
    """Resolve one make+model.  Callers memoise per request; the AI answer is
    also persisted, so it is asked once per make+model, not once per invoice.

    ``allow_ai=False`` is for reads that never commit (reports, the older
    workspace): they use an answer already cached but never ask the model,
    whose answer they could not keep.  The benchmark screens ask and commit.
    """

    match = lookup_vehicle_category(session, make=make, model=model)
    if match is not None and match.body_type:
        return VehicleCategory(
            match.body_type,
            SOURCE_LOOKUP,
            f"{match.matched_make} {match.matched_model} ({match.match_status})",
        )

    make_key = normalise_vehicle_name(make)
    model_key = normalise_vehicle_name(model)
    if not make_key or not model_key:
        return _UNKNOWN
    cached = _cached(session, make_key, model_key)
    if cached is not None:
        return _from_inference(cached)

    if not allow_ai:
        return _UNKNOWN
    classifier = build_vehicle_category_classifier()
    if classifier is None:
        return _UNKNOWN
    vocabulary = _vocabulary(session)
    try:
        answer = classifier.classify(make=make, model=model, allowed=vocabulary)
    except Exception:  # noqa: BLE001 - LLMProviderError or any outage must not block benchmarking
        # Not cached: an outage says nothing about the vehicle, so it is
        # asked again next time rather than remembered as "Unknown".
        return _UNKNOWN
    # The model may only choose from the catalogue's own vocabulary: a
    # category it invents would be a benchmark population of one, forever.
    by_fold = {category.casefold(): category for category in vocabulary}
    category = by_fold.get((answer or "").strip().casefold())
    row = VehicleCategoryInference(
        make=(make or "").strip()[:120],
        model=(model or "").strip()[:160],
        normalised_make=make_key,
        normalised_model=model_key,
        category=category,
        provider=str(getattr(classifier, "provider", "unknown")),
        model_id=str(getattr(classifier, "model_id", "unknown")),
        prompt_version=benchmark_writing.VEHICLE_CATEGORY_PROMPT_VERSION,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        # A concurrent request cached the same make+model first; use theirs.
        existing = _cached(session, make_key, model_key)
        return _from_inference(existing) if existing is not None else _UNKNOWN
    return _from_inference(row)


class VehicleCategoryResolver:
    """Per-request memo so one make+model is resolved once per payload."""

    def __init__(self, session: Session, *, allow_ai: bool = True) -> None:
        self.session = session
        self.allow_ai = allow_ai
        self._memo: dict[tuple[str, str], VehicleCategory] = {}

    def __call__(self, make: str | None, model: str | None) -> VehicleCategory:
        key = (normalise_vehicle_name(make), normalise_vehicle_name(model))
        if key not in self._memo:
            self._memo[key] = resolve_vehicle_category(
                self.session, make=make, model=model, allow_ai=self.allow_ai
            )
        return self._memo[key]
