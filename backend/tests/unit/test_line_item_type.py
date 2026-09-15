from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

from app.database import Base
from app.domain.line_item_type import (
    CANONICAL_TYPES,
    SECTION_SYNONYMS,
    ensure_line_item_type,
)
from app.enums import LineItemKind


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("LABOUR", "labour"),
        ("PAINT WORK", "paint"),
        ("Paint Labour", "paint"),
        ("PARTS", "parts"),
        ("Parts", "parts"),
        ("EXTRAS", "extras"),
        ("Paint and Materials", "paint_materials"),
        ("Paint & Materials", "paint_materials"),
        ("Total Paint & Materials Amount", "paint_materials"),
        ("Additional Items", "additional"),
        ("Additional charges", "additional"),
        ("Additional Costs", "additional"),
        ("Specialist Operation", "specialist_operation"),
        ("Sundry parts", "sundry"),
        ("Deduction", "discount"),
        ("Discount", "discount"),
    ],
)
def test_known_section_headings_map_to_canonical_codes(heading: str, expected: str) -> None:
    assert ensure_line_item_type(heading) == expected
    assert expected in CANONICAL_TYPES


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("  paint   WORK  ", "paint"),
        ("Specialist Operation:", "specialist_operation"),
        ("PARTS.", "parts"),
    ],
)
def test_matching_ignores_case_whitespace_and_punctuation(heading: str, expected: str) -> None:
    assert ensure_line_item_type(heading) == expected


def test_unknown_heading_becomes_a_slug() -> None:
    assert ensure_line_item_type("ABC Widgets") == "abc_widgets"
    assert ensure_line_item_type("Total ABC Amount") == "total_abc_amount"


def test_slug_is_a_valid_column_value() -> None:
    code = ensure_line_item_type("!! Glass & Trim -- replacement  (supplementary schedule) !!")
    assert len(code) <= 40
    assert code.replace("_", "").isalnum()
    assert code.strip("_") == code


@pytest.mark.parametrize("raw", [None, "", "   ", "---", "!!!"])
def test_blank_headings_are_unknown(raw: str | None) -> None:
    assert ensure_line_item_type(raw) == "unknown"


def test_canonical_codes_round_trip_through_the_vocabulary() -> None:
    for code in CANONICAL_TYPES:
        assert ensure_line_item_type(code) == code


def test_every_synonym_group_has_a_canonical_code() -> None:
    assert set(SECTION_SYNONYMS) == set(CANONICAL_TYPES)


def test_ensure_line_item_type_never_raises() -> None:
    # The signature is str | None, but this runs on parser output; a surprise
    # type must degrade to a code, never break an upload.
    assert ensure_line_item_type(12345) == "12345"  # type: ignore[arg-type]


def test_fresh_schema_exposes_the_extract_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(bind=engine)
        inspector = inspect(engine)

        invoice_columns = {column["name"] for column in inspector.get_columns("invoices")}
        assert {"policy_number", "paint_net", "other_net"} <= invoice_columns

        line_columns = {column["name"] for column in inspector.get_columns("invoice_line_items")}
        assert {"line_item_type", "is_section_total", "raw_category"} <= line_columns

        operation_columns = {
            column["name"] for column in inspector.get_columns("assessment_operations")
        }
        assert "raw_category" in operation_columns

        assert "ix_invoices_claim_policy" in {
            index["name"] for index in inspector.get_indexes("invoices")
        }
        assert "ix_engineer_assessment_claim_policy" in {
            index["name"] for index in inspector.get_indexes("engineer_assessments")
        }
    finally:
        engine.dispose()


def test_line_item_kind_enum_is_unchanged() -> None:
    # line_item_type is an open vocabulary precisely so this governed enum, which
    # drives mapping and benchmarkability, never has to grow for a new section.
    assert [member.value for member in LineItemKind] == [
        "part",
        "labour",
        "paint",
        "service",
        "fee",
        "disposal",
        "consumable",
        "recovery",
        "storage",
        "subcontract",
        "diagnostic",
        "discount",
        "unknown",
    ]
