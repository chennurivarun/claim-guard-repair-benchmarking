"""Audited handler corrections for classified document pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.enums import AuditActorType, PageType, ReviewStatus
from app.models import AuditEvent, DocumentPage


class PageCorrectionError(ValueError):
    """A safe, user-facing page correction validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PageCorrectionCommand:
    actor: str
    reason: str
    page_type: str | None = None
    group_id: str | None = None
    group_id_set: bool = False
    rotation: int | None = None


@dataclass(frozen=True)
class PageCorrectionResult:
    page: DocumentPage
    changed_fields: tuple[str, ...]
    reprocess_required: bool


def _page_state(page: DocumentPage) -> dict[str, Any]:
    return {
        "page_type": page.page_type.value,
        "group_id": page.group_id,
        "rotation": page.rotation,
        "review_status": page.review_status.value,
        "classification_confidence": page.classification_confidence,
        "extraction_method": page.extraction_method.value,
    }


def correct_document_page(
    session: Session,
    *,
    page: DocumentPage,
    command: PageCorrectionCommand,
) -> PageCorrectionResult:
    """Apply a handler correction without overwriting the original extraction evidence."""

    actor = command.actor.strip()
    reason = command.reason.strip()
    if not actor:
        raise PageCorrectionError("ACTOR_REQUIRED", "A handler identity is required.")
    if len(reason) < 3:
        raise PageCorrectionError("REASON_REQUIRED", "A correction reason is required.")

    requested: dict[str, Any] = {}
    if command.page_type is not None:
        try:
            requested["page_type"] = PageType(command.page_type.strip().lower())
        except ValueError as exc:
            raise PageCorrectionError(
                "INVALID_PAGE_TYPE",
                f"Unsupported page classification: {command.page_type}",
            ) from exc
    if command.group_id_set:
        group_id = command.group_id.strip() if command.group_id else None
        requested["group_id"] = group_id or None
    if command.rotation is not None:
        if command.rotation not in {0, 90, 180, 270}:
            raise PageCorrectionError(
                "INVALID_ROTATION",
                "Rotation must be 0, 90, 180 or 270 degrees.",
            )
        requested["rotation"] = command.rotation
    if not requested:
        raise PageCorrectionError(
            "CORRECTION_REQUIRED",
            "Provide a page classification, group identifier or rotation correction.",
        )

    before = _page_state(page)
    changed_fields = tuple(
        field for field, value in requested.items() if getattr(page, field) != value
    )
    if not changed_fields:
        raise PageCorrectionError(
            "NO_PAGE_CHANGES",
            "The supplied values already match this document page.",
        )

    for field in changed_fields:
        setattr(page, field, requested[field])
    page.review_status = ReviewStatus.CORRECTED

    corrected_at = datetime.now(UTC)
    document = page.document
    metadata = dict(document.metadata_json or {})
    corrections = dict(metadata.get("page_corrections") or {})
    corrections[str(page.page_number)] = {
        "page_type": page.page_type.value,
        "group_id": page.group_id,
        "rotation": page.rotation,
        "corrected_by": actor,
        "corrected_at": corrected_at.isoformat(),
        "reason": reason,
        "changed_fields": list(changed_fields),
    }
    metadata["page_corrections"] = corrections
    metadata["reprocess_required"] = True
    metadata["reprocess_reason"] = (
        "A handler corrected page classification, grouping or rotation after extraction."
    )
    document.metadata_json = metadata

    after = _page_state(page)
    session.add(
        AuditEvent(
            case_id=document.case_id,
            processing_run_id=document.case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type="DOCUMENT_PAGE_CORRECTED",
            entity_type="document_page",
            entity_id=page.id,
            before_json=before,
            after_json=after,
            event_payload_json={
                "reason": reason,
                "changed_fields": list(changed_fields),
                "raw_extraction_preserved": True,
                "reprocess_required": True,
            },
        )
    )
    session.flush()
    return PageCorrectionResult(
        page=page,
        changed_fields=changed_fields,
        reprocess_required=True,
    )


__all__ = [
    "PageCorrectionCommand",
    "PageCorrectionError",
    "PageCorrectionResult",
    "correct_document_page",
]
