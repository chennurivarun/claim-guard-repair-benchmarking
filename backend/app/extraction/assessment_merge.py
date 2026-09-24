"""Keep assessment detail found by another reader without duplicating sections."""

from __future__ import annotations

import re

from app.domain.line_item_type import UNKNOWN, ensure_line_item_type
from app.extraction.schemas import ExtractedAssessmentOperation, ExtractedEngineerAssessment


def operation_section(operation: ExtractedAssessmentOperation) -> str:
    section = operation.line_item_type
    if not section or section == UNKNOWN:
        section = operation.category
    return ensure_line_item_type(section)


def needs_assessment_details(assessment: ExtractedEngineerAssessment) -> bool:
    if not assessment.operations:
        return True
    sections = {operation_section(row) for row in assessment.operations}
    return any(
        getattr(assessment.fields, field) and section not in sections
        for field, section in (
            ("parts_net", "parts"), ("labour_net", "labour"),
            ("paint_net", "paint_materials"), ("extras_net", "extras"),
        )
    )


def merge_assessment_extractions(
    primary: ExtractedEngineerAssessment, fallback: ExtractedEngineerAssessment,
) -> ExtractedEngineerAssessment:
    """Fill absent sections/fields, retaining the primary reader's printed values.

    Never append a second interpretation of a section already read. Both
    readers must be describing the same assessment, and row numbers are
    assigned here because model-generated sequence numbers are not unique.
    """
    for field in ("assessment_number", "registration", "claim_reference", "vin"):
        left, right = getattr(primary.fields, field), getattr(fallback.fields, field)
        if left and right and re.sub(r"\W", "", left).upper() != re.sub(r"\W", "", right).upper():
            return primary
    sections = {operation_section(row) for row in primary.operations}
    additions = [row for row in fallback.operations if operation_section(row) not in sections]
    fields = primary.fields.model_dump()
    for name, value in fallback.fields.model_dump().items():
        if fields.get(name) is None:
            fields[name] = value
    return primary.model_copy(update={
        "fields": primary.fields.model_copy(update=fields),
        "operations": [
            row.model_copy(update={"sequence_no": index, "line_item_type": operation_section(row)})
            for index, row in enumerate([*primary.operations, *additions], 1)
        ],
        "page_numbers": sorted(set(primary.page_numbers) | set(fallback.page_numbers)),
        "extraction_confidence": min(primary.extraction_confidence, fallback.extraction_confidence)
        if additions else primary.extraction_confidence,
    })
