"""Vehicle category for benchmarking: lookup, then AI (cached), then Unknown.

Spec default D2.  The category is the body type the client talks about
(hatchback, SUV, ...), read from the ``body_type`` column of the catalogue.
The make+model is exactly what the invoice carries after gap-fill, so the
corpus vehicles are tested with the strings the client's documents print.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.init_db import initialize_database
from app.models import VehicleCategoryInference
from app.services import vehicle_category
from app.services.vehicle_category import (
    SOURCE_AI,
    SOURCE_LOOKUP,
    SOURCE_UNKNOWN,
    UNKNOWN_CATEGORY,
    resolve_vehicle_category,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    return Session(engine)


class _FakeClassifier:
    provider = "fake"
    model_id = "fake-1"

    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.calls: list[tuple[str | None, str | None]] = []

    def classify(self, *, make, model, allowed):
        self.calls.append((make, model))
        return self.answer


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(vehicle_category, "build_vehicle_category_classifier", lambda: None)


@pytest.mark.parametrize(
    ("make", "model", "category"),
    [
        # Formats 1/5/6/7: printed on the assessment, gap-filled onto the invoice.
        ("HYUNDAI", "140 SE Nav", "Hatchback"),
        ("HYUNDAI", "i30 SE Nav", "Hatchback"),
        ("SKODA", "KAROQ SE TSI 115]", "SUV"),
        ("SEAT", "IBIZA", "Supermini"),
        ("FORD", "Puma", "SUV"),
        ("VOLVO", "XC40(XZ)(18-)", "SUV"),
    ],
)
def test_client_corpus_vehicles_resolve_by_lookup(no_llm, make, model, category) -> None:
    with _session() as session:
        resolved = resolve_vehicle_category(session, make=make, model=model)

    assert resolved.category == category
    assert resolved.source == SOURCE_LOOKUP


def test_unrecognised_vehicle_without_an_llm_is_unknown(no_llm) -> None:
    with _session() as session:
        resolved = resolve_vehicle_category(session, make="Zastava", model="Yugo 45")
        missing = resolve_vehicle_category(session, make=None, model=None)

    assert (resolved.category, resolved.source) == (UNKNOWN_CATEGORY, SOURCE_UNKNOWN)
    assert (missing.category, missing.source) == (UNKNOWN_CATEGORY, SOURCE_UNKNOWN)


def test_ai_category_is_asked_once_per_make_and_model_and_cached(monkeypatch) -> None:
    classifier = _FakeClassifier("SUV")
    monkeypatch.setattr(
        vehicle_category, "build_vehicle_category_classifier", lambda: classifier
    )
    with _session() as session:
        first = resolve_vehicle_category(session, make="Dacia", model="Duster Comfort")
        # A later request, not the same in-memory memo: the database cache answers.
        second = resolve_vehicle_category(session, make="DACIA", model="duster comfort")
        cached = session.scalars(select(VehicleCategoryInference)).all()

    assert (first.category, first.source) == ("SUV", SOURCE_AI)
    assert (second.category, second.source) == ("SUV", SOURCE_AI)
    assert classifier.calls == [("Dacia", "Duster Comfort")]
    assert len(cached) == 1


def test_read_only_resolution_uses_the_ai_cache_but_never_asks(monkeypatch) -> None:
    """Report and workspace reads resolve categories without committing, so
    they must not call the model (its answer would be rolled back and asked
    again on every read); they still read what the benchmark screens cached."""

    classifier = _FakeClassifier("SUV")
    monkeypatch.setattr(
        vehicle_category, "build_vehicle_category_classifier", lambda: classifier
    )
    with _session() as session:
        before = resolve_vehicle_category(
            session, make="Dacia", model="Duster", allow_ai=False
        )
        asked = resolve_vehicle_category(session, make="Dacia", model="Duster")
        after = resolve_vehicle_category(session, make="Dacia", model="Duster", allow_ai=False)

    assert before.source == SOURCE_UNKNOWN
    assert asked.source == SOURCE_AI
    assert (after.category, after.source) == ("SUV", SOURCE_AI)
    assert len(classifier.calls) == 1


def test_lookup_wins_over_ai(monkeypatch) -> None:
    classifier = _FakeClassifier("Van")
    monkeypatch.setattr(
        vehicle_category, "build_vehicle_category_classifier", lambda: classifier
    )
    with _session() as session:
        resolved = resolve_vehicle_category(session, make="Nissan", model="Qashqai")

    assert (resolved.category, resolved.source) == ("SUV", SOURCE_LOOKUP)
    assert classifier.calls == []


def test_ai_answer_outside_the_catalogue_vocabulary_is_unknown(monkeypatch) -> None:
    classifier = _FakeClassifier("Flying car")
    monkeypatch.setattr(
        vehicle_category, "build_vehicle_category_classifier", lambda: classifier
    )
    with _session() as session:
        resolved = resolve_vehicle_category(session, make="Dacia", model="Spring")
        again = resolve_vehicle_category(session, make="Dacia", model="Spring")

    assert (resolved.category, resolved.source) == (UNKNOWN_CATEGORY, SOURCE_UNKNOWN)
    assert again.source == SOURCE_UNKNOWN
    # The refusal is cached too: an unhelpful answer is not re-asked per invoice.
    assert len(classifier.calls) == 1
