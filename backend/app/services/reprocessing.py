from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.enums import (
    AuditActorType,
    CaseStatus,
    OntologyVersionStatus,
    ResearchStatus,
    RunStatus,
    RunType,
)
from app.llm.mapping import ConstrainedMappingAdjudicator
from app.models import (
    AuditEvent,
    Case,
    OntologyVersion,
    ProcessingRun,
    ResearchItem,
    ResearchTask,
)
from app.services.case_result import build_case_result
from app.services.comparison_workflow import MappingOverride, run_case_comparison


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def _summary_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "challenge_price_net",
        "challenge_amount_net",
        "vat_impact",
        "gross_effect",
        "challenge_percentage",
        "challenge_strength",
    )
    return {
        key: {
            "before": before.get(key),
            "after": after.get(key),
            "change": str(_decimal(after.get(key)) - _decimal(before.get(key))),
        }
        for key in keys
    }


def reprocess_case(
    session: Session,
    case: Case,
    *,
    actor: str,
    ontology_version_id: str | None = None,
    llm_adjudicator: ConstrainedMappingAdjudicator | None = None,
) -> dict[str, Any]:
    """Recompare a claim in a new immutable run while preserving all prior rows."""

    if case.status == CaseStatus.FINALISED:
        raise ValueError("A finalised claim cannot be reprocessed.")
    previous_run = (
        session.get(ProcessingRun, case.current_processing_run_id)
        if case.current_processing_run_id
        else None
    )
    if previous_run is None or previous_run.status != RunStatus.SUCCEEDED:
        raise ValueError("The case has no completed processing run to reuse.")
    version = (
        session.get(OntologyVersion, ontology_version_id)
        if ontology_version_id
        else session.scalar(
            select(OntologyVersion)
            .where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
            .order_by(OntologyVersion.sequence_number.desc())
        )
    )
    if version is None or version.status != OntologyVersionStatus.PUBLISHED:
        raise ValueError("A published ontology version is required for reprocessing.")

    before = build_case_result(session, case.case_reference)
    now = datetime.now(UTC)
    configuration_hash = hashlib.sha256(
        f"{previous_run.configuration_hash}:{version.id}:{actor}:{now.isoformat()}".encode()
    ).hexdigest()
    run = ProcessingRun(
        case_id=case.id,
        run_type=RunType.REPROCESS,
        application_version=previous_run.application_version,
        configuration_hash=configuration_hash,
        ontology_version_id=version.id,
        benchmark_policy_version=previous_run.benchmark_policy_version,
        policy_config_version_id=previous_run.policy_config_version_id,
        model_provider=previous_run.model_provider,
        model_id=previous_run.model_id,
        prompt_version=previous_run.prompt_version,
        extraction_version=previous_run.extraction_version,
        started_at=now,
        completed_at=now,
        status=RunStatus.SUCCEEDED,
        metrics_json={
            **(previous_run.metrics_json or {}),
            "reused_extraction_run_id": previous_run.id,
            "reprocessed_by": actor,
        },
        source_import_versions_json=list(previous_run.source_import_versions_json or []),
    )
    session.add(run)
    session.flush()
    case.current_processing_run_id = run.id
    session.flush()

    approved_research = session.scalars(
        select(ResearchItem)
        .join(ResearchTask, ResearchTask.id == ResearchItem.research_task_id)
        .where(
            ResearchTask.case_id == case.id,
            ResearchItem.status == ResearchStatus.APPROVED,
        )
        .options(selectinload(ResearchItem.research_task))
    ).all()
    overrides = {
        item.research_task.invoice_line_item_id: MappingOverride(
            ontology_item_id=item.provisional_ontology_item_id,
            actor_id=item.reviewer or actor,
            rationale="Previously approved research mapping replayed during reprocessing.",
        )
        for item in approved_research
        if item.provisional_ontology_item_id
    }
    comparison = run_case_comparison(
        session,
        case,
        mapping_overrides=overrides,
        llm_adjudicator=llm_adjudicator,
    )
    after = build_case_result(session, case.case_reference)
    delta = _summary_delta(before.get("summary") or {}, after.get("summary") or {})
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=run.id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type="CASE_REPROCESSED",
            entity_type="case",
            entity_id=case.id,
            before_json={
                "processing_run_id": previous_run.id,
                "ontology_version_id": previous_run.ontology_version_id,
            },
            after_json={
                "processing_run_id": run.id,
                "ontology_version_id": version.id,
            },
            event_payload_json={"comparison": comparison, "summary_delta": delta},
        )
    )
    session.flush()
    return {
        "case_reference": case.case_reference,
        "previous_processing_run_id": previous_run.id,
        "processing_run_id": run.id,
        "ontology_version_id": version.id,
        "ontology_version": version.label,
        "policy_version": run.benchmark_policy_version,
        "comparison": comparison,
        "summary_delta": delta,
    }
