from decimal import Decimal

from app.extraction.assessment_merge import merge_assessment_extractions, needs_assessment_details
from app.extraction.schemas import (
    EngineerAssessmentFields,
    ExtractedAssessmentOperation,
    ExtractedEngineerAssessment,
)


def assessment(rows, **fields):
    return ExtractedEngineerAssessment(
        fields=EngineerAssessmentFields(assessment_number="A-12", **fields),
        operations=[ExtractedAssessmentOperation(
            sequence_no=1, category=section, description=description, total=total, page_number=1,
        ) for section, description, total in rows],
        page_numbers=[1], extraction_method="test", extraction_confidence=0.9,
    )


def test_missing_parts_are_added_without_duplicating_labour_or_rewriting_printed_totals():
    primary = assessment([("Labour", "Fit door", "50")], parts_net="100", labour_net="50")
    fallback = assessment([
        ("Labour", "Fit door duplicate reading", "60"),
        ("Parts", "Front door", "80"), ("Parts", "Hinge", "10"),
    ], parts_net="90")
    assert needs_assessment_details(primary)
    merged = merge_assessment_extractions(primary, fallback)
    assert [row.description for row in merged.operations] == ["Fit door", "Front door", "Hinge"]
    assert [row.sequence_no for row in merged.operations] == [1, 2, 3]
    assert merged.fields.parts_net == Decimal("100")
    assert sum(row.total for row in merged.operations if row.line_item_type == "parts") == 90
    assert not needs_assessment_details(merged)


def test_conflicting_identity_cannot_contribute_operations():
    primary = assessment([], registration="AB12XYZ")
    fallback = assessment([("Parts", "Wrong vehicle door", "80")], registration="ZZ99ZZZ")
    assert merge_assessment_extractions(primary, fallback).operations == []


def test_summary_only_responses_remain_empty_and_retry_does_not_duplicate_detail():
    empty = assessment([], parts_net="80")
    assert needs_assessment_details(merge_assessment_extractions(empty, empty))
    detailed = assessment([("Parts", "Front door", "80")], parts_net="80")
    merged = merge_assessment_extractions(empty, detailed)
    again = merge_assessment_extractions(merged, detailed)
    assert len(again.operations) == 1
