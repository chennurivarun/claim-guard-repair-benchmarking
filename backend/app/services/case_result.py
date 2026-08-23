from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import (
    ApprovalStatus,
    ClaimPartyRole,
    ClaimVehicleRole,
    LineItemKind,
    ReviewStatus,
)
from app.models import (
    AuditEvent,
    Case,
    ChallengeResult,
    ClaimContext,
    ComparisonComparable,
    Document,
    DocumentPage,
    ExternalEvidence,
    HistoricalObservation,
    Invoice,
    InvoiceLineItem,
    LiabilityAssessment,
    MathFinding,
    OntologyItem,
    OntologyMapping,
    OntologyVersion,
    PriceComparison,
    PriceObservation,
    ProcessingRun,
    ResearchItem,
    ResearchTask,
    SourceProvider,
    Vehicle,
)
from app.services.benchmarking import (
    DEFAULT_COMPARISON_POLICY,
    _build_repairer_trends,
    _repairer_group_key,
    calculate_benchmark_statistics,
    canonical_benchmark_category,
)

settings = get_settings()


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _display_status(value: Any) -> str:
    return str(_enum_value(value) or "HUMAN_REVIEW_REQUIRED").replace("_", " ").upper()


def _decimal(value: Any, default: str = "0") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value))


def _money_float(value: Any) -> float:
    return float(_decimal(value).quantize(Decimal("0.01")))


def _optional_money_float(value: Any) -> float | None:
    return None if value in (None, "") else _money_float(value)


def _percent(value: Any) -> int:
    number = _decimal(value)
    if number <= 1:
        number *= 100
    return max(0, min(100, int(number.quantize(Decimal("1")))))


def _normalised_bbox(value: Any, page: DocumentPage | None) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4 or page is None:
        return None
    if not page.width or not page.height:
        return None
    x0, y0, x1, y1 = (float(item) for item in value)
    return [
        round(max(0.0, min(1.0, x0 / page.width)), 6),
        round(max(0.0, min(1.0, y0 / page.height)), 6),
        round(max(0.0, min(1.0, x1 / page.width)), 6),
        round(max(0.0, min(1.0, y1 / page.height)), 6),
    ]


def _source_record(
    *,
    page: DocumentPage | None,
    regions: dict[str, Any] | None,
    fallback_bbox: Any = None,
    raw_text: str | None = None,
    method: Any = None,
    precision: str | None = None,
) -> dict[str, Any] | None:
    if page is None:
        return None
    normalised_regions = {
        name: box
        for name, value in (regions or {}).items()
        if (box := _normalised_bbox(value, page)) is not None
    }
    fallback = _normalised_bbox(fallback_bbox, page)
    if fallback and "row" not in normalised_regions:
        normalised_regions["row"] = fallback
    return {
        "pageId": page.id,
        "pageNumber": page.page_number,
        "method": _enum_value(method) if method else page.extraction_method.value,
        "precision": precision or ("exact" if regions else "approximate"),
        "rawText": raw_text,
        "regions": normalised_regions,
    }


def _payload_source_record(
    source: dict[str, Any] | None,
    pages_by_number: dict[int, DocumentPage],
) -> dict[str, Any] | None:
    if not source:
        return None
    page = pages_by_number.get(int(source.get("page_number") or 0))
    return _source_record(
        page=page,
        regions=source.get("regions"),
        fallback_bbox=source.get("bbox"),
        raw_text=source.get("raw_text"),
        method=source.get("method"),
        precision=source.get("precision"),
    )


def _source_reference(
    source: dict[str, Any] | None,
    field: str,
    label: str,
) -> dict[str, Any] | None:
    if not source:
        return None
    bbox = (source.get("regions") or {}).get(field)
    if bbox is None:
        return None
    return {
        "pageId": source["pageId"],
        "pageNumber": source["pageNumber"],
        "label": label,
        "bbox": bbox,
        "precision": source.get("precision", "approximate"),
    }


def _date_label(value: date | datetime | None) -> str:
    if value is None:
        return ""
    return f"{value.day} {value:%b %Y}"


def _vehicle_label(vehicle: Any) -> str:
    if vehicle is None:
        return ""
    year = getattr(vehicle, "manufacture_year", None)
    values = [
        getattr(vehicle, "make", None),
        getattr(vehicle, "model", None),
        getattr(vehicle, "variant", None),
    ]
    label = " ".join(str(value) for value in values if value)
    return f"{label} ({year})" if label and year else label


def _latest_by(items: list[Any], key: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for item in sorted(items, key=lambda row: row.updated_at, reverse=True):
        output.setdefault(str(getattr(item, key)), item)
    return output


def _load_case_graph(session: Session, case_reference: str) -> dict[str, Any]:
    case = session.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise LookupError(f"Claim not found: {case_reference}")

    context = session.scalar(select(ClaimContext).where(ClaimContext.case_id == case.id))
    liability = (
        session.scalar(
            select(LiabilityAssessment)
            .where(LiabilityAssessment.claim_context_id == context.id)
            .order_by(LiabilityAssessment.created_at.desc())
        )
        if context
        else None
    )
    invoices = list(
        session.scalars(
            select(Invoice)
            .where(Invoice.case_id == case.id)
            .order_by(Invoice.invoice_date, Invoice.created_at)
        ).all()
    )
    invoice_ids = [invoice.id for invoice in invoices]
    lines = (
        list(
            session.scalars(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id.in_(invoice_ids))
                .order_by(InvoiceLineItem.invoice_id, InvoiceLineItem.sequence_no)
            ).all()
        )
        if invoice_ids
        else []
    )
    line_ids = [line.id for line in lines]
    mappings = (
        list(
            session.scalars(
                select(OntologyMapping)
                .where(OntologyMapping.invoice_line_item_id.in_(line_ids))
                .order_by(OntologyMapping.updated_at.desc())
            ).all()
        )
        if line_ids
        else []
    )
    comparisons = (
        list(
            session.scalars(
                select(PriceComparison)
                .where(PriceComparison.invoice_line_item_id.in_(line_ids))
                .order_by(PriceComparison.updated_at.desc())
            ).all()
        )
        if line_ids
        else []
    )
    comparison_ids = [
        comparison.id for comparison in _latest_by(comparisons, "invoice_line_item_id").values()
    ]
    comparables = (
        list(
            session.scalars(
                select(ComparisonComparable).where(
                    ComparisonComparable.price_comparison_id.in_(comparison_ids)
                )
            ).all()
        )
        if comparison_ids
        else []
    )
    price_observation_ids = {
        row.price_observation_id for row in comparables if row.price_observation_id
    }
    historical_observation_ids = {
        row.historical_observation_id for row in comparables if row.historical_observation_id
    }
    price_observations = {
        row.id: row
        for row in (
            session.scalars(
                select(PriceObservation).where(PriceObservation.id.in_(price_observation_ids))
            ).all()
            if price_observation_ids
            else []
        )
    }
    historical_observations = {
        row.id: row
        for row in (
            session.scalars(
                select(HistoricalObservation).where(
                    HistoricalObservation.id.in_(historical_observation_ids)
                )
            ).all()
            if historical_observation_ids
            else []
        )
    }
    line_challenges = (
        list(
            session.scalars(
                select(ChallengeResult).where(
                    ChallengeResult.price_comparison_id.in_(comparison_ids)
                )
            ).all()
        )
        if comparison_ids
        else []
    )
    invoice_challenges = (
        list(
            session.scalars(
                select(ChallengeResult).where(ChallengeResult.invoice_id.in_(invoice_ids))
            ).all()
        )
        if invoice_ids
        else []
    )
    documents = list(session.scalars(select(Document).where(Document.case_id == case.id)).all())
    document_ids = [document.id for document in documents]
    pages = (
        list(
            session.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id.in_(document_ids))
                .order_by(DocumentPage.document_id, DocumentPage.page_number)
            ).all()
        )
        if document_ids
        else []
    )
    checks = (
        list(
            session.scalars(
                select(MathFinding).where(MathFinding.invoice_id.in_(invoice_ids))
            ).all()
        )
        if invoice_ids
        else []
    )
    research_tasks = list(
        session.scalars(select(ResearchTask).where(ResearchTask.case_id == case.id)).all()
    )
    task_ids = [task.id for task in research_tasks]
    evidence = (
        list(
            session.scalars(
                select(ExternalEvidence).where(ExternalEvidence.research_task_id.in_(task_ids))
            ).all()
        )
        if task_ids
        else []
    )
    versions = list(
        session.scalars(select(OntologyVersion).order_by(OntologyVersion.sequence_number)).all()
    )
    audit = list(
        session.scalars(
            select(AuditEvent).where(AuditEvent.case_id == case.id).order_by(AuditEvent.created_at)
        ).all()
    )
    ontology_ids = {
        mapping.selected_ontology_item_id
        for mapping in mappings
        if mapping.selected_ontology_item_id
    }
    ontology_ids.update(
        component["ontology_item_id"]
        for mapping in mappings
        for component in (mapping.bundle_components_json or [])
        if component.get("ontology_item_id")
    )
    ontology = {
        item.id: item
        for item in (
            session.scalars(select(OntologyItem).where(OntologyItem.id.in_(ontology_ids))).all()
            if ontology_ids
            else []
        )
    }
    vehicles = {
        vehicle.id: vehicle
        for vehicle in (
            session.scalars(
                select(Vehicle).where(
                    Vehicle.id.in_({row.vehicle_id for row in invoices if row.vehicle_id})
                )
            ).all()
            if any(row.vehicle_id for row in invoices)
            else []
        )
    }
    return {
        "case": case,
        "context": context,
        "liability": liability,
        "invoices": invoices,
        "lines": lines,
        "mappings": mappings,
        "comparisons": comparisons,
        "comparables": comparables,
        "price_observations": price_observations,
        "historical_observations": historical_observations,
        "line_challenges": line_challenges,
        "invoice_challenges": invoice_challenges,
        "documents": documents,
        "pages": pages,
        "checks": checks,
        "research_tasks": research_tasks,
        "evidence": evidence,
        "versions": versions,
        "audit": audit,
        "ontology": ontology,
        "vehicles": vehicles,
    }


def _comparable_record(row: ComparisonComparable, graph: dict[str, Any]) -> dict[str, Any]:
    price = graph["price_observations"].get(row.price_observation_id or "")
    history = graph["historical_observations"].get(row.historical_observation_id or "")
    source = history or price
    observed_date = (
        history.invoice_date
        if history
        else (price.observed_at or price.effective_from)
        if price
        else None
    )
    approval_status = _enum_value(source.approval_status) if source else None
    settlement_status = _enum_value(history.settlement_status) if history else None
    return {
        "id": row.id,
        "source_type": "historical" if history else "ontology_price",
        "source_observation_id": row.historical_observation_id or row.price_observation_id,
        "description": history.raw_description if history else None,
        "price_net": row.normalised_line_net or row.original_line_net,
        "original_price_net": row.original_line_net,
        "normalised_price_net": row.normalised_line_net,
        "observed_date": observed_date,
        "weight": row.weight,
        "approval_status": approval_status,
        "settlement_status": settlement_status,
        "provenance": {
            "source_record_id": getattr(source, "source_record_id", None),
            "claim_reference": history.claim_reference if history else None,
            "source_reference": (
                f"/api/v1/historical-observations/{history.id}"
                if history
                else price.source_url_or_ref
                if price
                else None
            ),
            "observation_type": _enum_value(history.observation_type) if history else None,
            "approved_amount_net": history.approved_amount_net if history else None,
            "settled_amount_net": history.settled_amount_net if history else None,
        },
        "vehicle": (
            {
                "make": history.vehicle_make,
                "model": history.vehicle_model,
                "variant": history.vehicle_variant,
                "year": history.vehicle_year,
            }
            if history
            else None
        ),
        "comparability_metadata": history.comparability_metadata_json if history else None,
        "comparable_class": row.comparable_class,
        "adjustments": row.adjustments_json,
        "stale_data_warning": row.stale_data_warning,
        "eligible": True,
        "eligibility_reason": row.eligibility_reason,
    }


def build_case_result(
    session: Session,
    case_reference: str,
    *,
    _graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single normalized graph used by every report format."""

    graph = _graph or _load_case_graph(session, case_reference)
    case: Case = graph["case"]
    context: ClaimContext | None = graph["context"]
    liability: LiabilityAssessment | None = graph["liability"]
    invoices: list[Invoice] = graph["invoices"]
    lines: list[InvoiceLineItem] = graph["lines"]
    mappings_by_line = _latest_by(graph["mappings"], "invoice_line_item_id")
    comparisons_by_line = _latest_by(graph["comparisons"], "invoice_line_item_id")
    challenges_by_comparison = {
        challenge.price_comparison_id: challenge for challenge in graph["line_challenges"]
    }
    invoice_challenges = {
        challenge.invoice_id: challenge for challenge in graph["invoice_challenges"]
    }
    ontology: dict[str, OntologyItem] = graph["ontology"]
    vehicles: dict[str, Vehicle] = graph["vehicles"]
    comparables_by_comparison: dict[str, list[dict[str, Any]]] = {}
    for comparable in graph["comparables"]:
        comparables_by_comparison.setdefault(comparable.price_comparison_id, []).append(
            _comparable_record(comparable, graph)
        )

    invoice_records = []
    for invoice in invoices:
        vehicle = vehicles.get(invoice.vehicle_id or "")
        net_total = _decimal(invoice.subtotal_net) + _decimal(invoice.non_vat_total)
        invoice_records.append(
            {
                "id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "repairer": invoice.supplier_name,
                "repairer_address": invoice.supplier_address,
                "vehicle_registration": vehicle.registration if vehicle else None,
                "net_total": net_total,
                "net_subtotal": invoice.subtotal_net,
                "vat_total": invoice.vat_total,
                "non_vat_total": invoice.non_vat_total,
                "gross_total": invoice.gross_total,
                "currency": invoice.currency,
            }
        )

    line_records: list[dict[str, Any]] = []
    mapping_records: list[dict[str, Any]] = []
    comparison_records: list[dict[str, Any]] = []
    challenge_records: list[dict[str, Any]] = []
    for line in lines:
        rejected = line.status == ReviewStatus.REJECTED
        mapping = mappings_by_line.get(line.id)
        comparison = comparisons_by_line.get(line.id)
        challenge = challenges_by_comparison.get(comparison.id) if comparison else None
        item = (
            ontology.get(mapping.selected_ontology_item_id)
            if mapping and mapping.selected_ontology_item_id
            else None
        )
        is_mot = "mot" in line.raw_description.lower()
        line_record = {
            "id": line.id,
            "invoice_id": line.invoice_id,
            "sequence_no": line.sequence_no,
            "description": line.raw_description,
            "normalised_description": line.normalised_description,
            "part_number": line.part_number,
            "kind": _enum_value(line.item_kind),
            "quantity": line.quantity,
            "unit": line.unit,
            "unit_price_net": line.unit_price_net,
            "invoice_net": line.line_total_net,
            "line_total_net": line.line_total_net,
            "vat_rate": line.vat_rate,
            "vat_amount": line.vat_amount,
            "gross_total": line.line_gross,
            "is_mot": is_mot,
            "extraction_confidence": line.extraction_confidence,
            "review_status": _enum_value(line.status),
            "source_page_id": line.source_page_id,
            "source_bbox_json": line.source_bbox_json,
            "source_regions_json": line.source_regions_json,
            "source_raw_text": line.source_raw_text,
            "extraction_method": _enum_value(line.extraction_method),
            "user_corrected": line.user_corrected,
            "difference_from_ontology_net": None,
            "difference_from_history_net": None,
            "comparables": [],
        }
        line_records.append(line_record)
        if mapping and not rejected:
            mapping_records.append(
                {
                    "id": mapping.id,
                    "line_id": line.id,
                    "status": _enum_value(mapping.final_status),
                    "decision": _enum_value(mapping.decision),
                    "ontology_item_id": mapping.selected_ontology_item_id,
                    "ontology_item_name": item.canonical_name if item else None,
                    "ontology_approval": _enum_value(item.approval_status) if item else None,
                    "mapping_confidence": mapping.combined_confidence,
                    "rationale": mapping.rationale,
                    "reviewed_by": mapping.reviewed_by,
                    "reviewed_at": mapping.reviewed_at,
                    "is_bundled": mapping.is_bundled,
                    "bundle_components": mapping.bundle_components_json,
                    "flags": mapping.flags_json,
                }
            )
        if comparison and not rejected:
            formula = comparison.benchmark_formula_json or {}
            comparable_records = comparables_by_comparison.get(comparison.id, [])
            line_record.update(
                {
                    "difference_from_ontology_net": formula.get("difference_from_ontology"),
                    "difference_from_history_net": formula.get("difference_from_history"),
                    "comparables": comparable_records,
                }
            )
            comparison_records.append(
                {
                    "id": comparison.id,
                    "line_id": line.id,
                    "invoice_net": comparison.invoice_line_net,
                    "ontology_price_net": comparison.ontology_line_net,
                    "historical_median_net": comparison.historical_line_net,
                    "historical_p25_net": comparison.historical_p25_net,
                    "historical_p75_net": comparison.historical_p75_net,
                    "historical_count": comparison.n_comparables,
                    "challenge_price_net": comparison.benchmark_line_net,
                    "benchmark_source": comparison.selected_benchmark_source,
                    "policy_version": comparison.benchmark_policy_version,
                    "status": _enum_value(comparison.status),
                    "difference_from_ontology_net": formula.get("difference_from_ontology"),
                    "difference_from_history_net": formula.get("difference_from_history"),
                    "comparables": comparable_records,
                    "formula": formula,
                    "eligibility": comparison.eligibility_flags_json,
                }
            )
        if challenge and comparison and not rejected:
            approved = bool(challenge.reviewer_approved)
            challenge_records.append(
                {
                    "id": challenge.id,
                    "line_id": line.id,
                    "invoice_id": line.invoice_id,
                    "description": line.raw_description,
                    "invoice_net": comparison.invoice_line_net,
                    "challenge_price_net": challenge.recommended_payable_net,
                    "challenge_amount_net": challenge.challenge_net,
                    "challenge_vat": challenge.challenge_vat,
                    "challenge_gross": challenge.challenge_gross,
                    "vat_rate": line.vat_rate,
                    "is_mot": is_mot,
                    "approved": approved,
                    "challengeable": _decimal(challenge.challenge_net) > 0,
                    "status": _enum_value(challenge.status),
                    "ontology_item_id": mapping.selected_ontology_item_id if mapping else None,
                    "ontology_approval": _enum_value(item.approval_status) if item else None,
                    "ontology_price_net": comparison.ontology_line_net,
                    "historical_median_net": comparison.historical_line_net,
                    "historical_count": comparison.n_comparables,
                    "benchmark_source": comparison.selected_benchmark_source,
                    "reason": challenge.narrative,
                    "challenge_score": challenge.evidence_strength_score,
                    "approved_by": challenge.approved_by,
                    "approved_at": challenge.approved_at,
                }
            )

    primary_summary = next(
        (
            invoice_challenges[invoice.id]
            for invoice in reversed(invoices)
            if invoice.id in invoice_challenges
        ),
        None,
    )
    return {
        "report_date": datetime.now(UTC).date(),
        "case": {
            "id": case.id,
            "case_reference": case.case_reference,
            "claim_number": context.claim_number if context else None,
            "status": _enum_value(case.status),
            "paying_insurer_name": context.paying_insurer_name if context else None,
            "claiming_insurer_name": context.claiming_insurer_name if context else None,
            "paying_policy_number": context.paying_policy_number if context else None,
            "accident_date": context.accident_at if context else None,
        },
        "liability": {
            "status": _display_status(liability.effective_status if liability else None),
            "human_confirmed": bool(liability and liability.human_confirmed),
            "confirmed_by": liability.confirmed_by if liability else None,
            "confirmed_at": liability.confirmed_at if liability else None,
            "split_liability_percentage": liability.split_liability_percentage
            if liability
            else None,
            "rationale": liability.human_rationale if liability else None,
        },
        "invoices": invoice_records,
        "pages": [
            {
                "id": page.id,
                "document_id": page.document_id,
                "page_number": page.page_number,
                "classification": _enum_value(page.page_type),
                "confidence": page.classification_confidence,
                "extraction_method": _enum_value(page.extraction_method),
                "rotation": page.rotation,
                "group_id": page.group_id,
            }
            for page in graph["pages"]
        ],
        "lines": line_records,
        "checks": [
            {
                "id": finding.id,
                "invoice_id": finding.invoice_id,
                "line_id": finding.line_item_id,
                "check_type": finding.check_code,
                "status": _enum_value(finding.status),
                "severity": _enum_value(finding.severity),
                "expected": finding.expected_value,
                "observed": finding.observed_value,
                "difference": finding.difference,
                "explanation": finding.explanation,
            }
            for finding in graph["checks"]
        ],
        "mappings": mapping_records,
        "comparisons": comparison_records,
        "challenges": challenge_records,
        "evidence": [
            {
                "id": row.id,
                "type": "external_research",
                "source": row.source_uri,
                "title": row.title,
                "captured_at": row.captured_at,
                "price_net": row.price_net,
                "approval_status": _enum_value(row.approval_status),
                "content_hash": row.content_hash,
            }
            for row in graph["evidence"]
        ],
        "versions": [
            {
                "id": version.id,
                "type": "ontology",
                "version": version.label,
                "sequence": version.sequence_number,
                "status": _enum_value(version.status),
                "published_at": version.published_at,
            }
            for version in graph["versions"]
        ]
        + [{"type": "policy", "version": "claimguard-v1.4", "status": "ACTIVE"}],
        "audit": [
            {
                "id": event.id,
                "timestamp": event.created_at,
                "actor": event.actor_id,
                "actor_type": _enum_value(event.actor_type),
                "action": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "processing_run_id": event.processing_run_id,
                "correlation_id": event.correlation_id,
                "before": event.before_json,
                "after": event.after_json,
                "payload": event.event_payload_json,
                "previous_event_hash": event.previous_event_hash,
                "event_hash": event.event_hash,
            }
            for event in graph["audit"]
        ],
        "summary": (
            {
                "invoice_price_net": _decimal(primary_summary.recommended_payable_net)
                + _decimal(primary_summary.challenge_net),
                "challenge_price_net": primary_summary.recommended_payable_net,
                "challenge_amount_net": primary_summary.challenge_net,
                "vat_impact": primary_summary.challenge_vat,
                "gross_effect": primary_summary.challenge_gross,
                "challenge_percentage": primary_summary.challenge_percentage,
                "challenge_strength": primary_summary.evidence_strength_score,
            }
            if primary_summary
            else {}
        ),
    }


def _uploaded_line_identity(
    line: InvoiceLineItem,
    *,
    latest_mappings: dict[str, OntologyMapping],
    ontology: dict[str, OntologyItem],
) -> tuple[set[str], str, str]:
    """Return the same canonical identity everywhere uploaded lines are benchmarked."""

    mapping = latest_mappings.get(line.id)
    item_id = mapping.selected_ontology_item_id if mapping else None
    category = canonical_benchmark_category(
        line.raw_description,
        line.normalised_description,
    )
    keys = {f"description:{category.casefold()}"}
    identity = f"description:{category.casefold()}"
    if item_id:
        keys.add(f"ontology:{item_id}")
        identity = item_id
        item = ontology.get(item_id)
        if item:
            category = item.canonical_name
    return keys, category, identity


def _uploaded_line_p90_benchmarks(
    graph: dict[str, Any],
    *,
    current_invoice: Invoice,
    minimum_count: int = 3,
) -> dict[str, dict[str, Any]]:
    """Compare current lines with earlier uploaded invoices in the same batch.

    The invoice order already used by the workspace (invoice date, then upload
    time) defines "earlier".  Consequently, the invoice under review can never
    contribute to its own benchmark and later invoices cannot leak backwards.
    """

    invoices: list[Invoice] = graph["invoices"]
    try:
        current_index = next(
            index for index, candidate in enumerate(invoices) if candidate.id == current_invoice.id
        )
    except StopIteration:
        return {}
    prior_invoices = invoices[:current_index]
    if not prior_invoices:
        return {}

    prior_invoice_ids = {invoice.id for invoice in prior_invoices}
    invoice_by_id = {invoice.id: invoice for invoice in prior_invoices}
    latest_mappings = _latest_by(graph["mappings"], "invoice_line_item_id")
    ontology: dict[str, OntologyItem] = graph["ontology"]

    observations_by_key: dict[str, list[dict[str, Any]]] = {}
    for line in graph["lines"]:
        if line.invoice_id not in prior_invoice_ids:
            continue
        if line.status == ReviewStatus.REJECTED:
            continue
        price = _decimal(line.line_total_net)
        if price <= 0:
            continue
        invoice = invoice_by_id[line.invoice_id]
        keys, category, _ = _uploaded_line_identity(
            line,
            latest_mappings=latest_mappings,
            ontology=ontology,
        )
        observation = {
            "lineId": line.id,
            "invoiceId": invoice.id,
            "invoiceNumber": invoice.invoice_number or invoice.id,
            "invoiceDate": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
            "description": line.raw_description,
            "category": category,
            "price": _money_float(price),
        }
        for key in keys:
            observations_by_key.setdefault(key, []).append(observation)

    results: dict[str, dict[str, Any]] = {}
    for line in graph["lines"]:
        if line.invoice_id != current_invoice.id or line.status == ReviewStatus.REJECTED:
            continue
        current_price = _decimal(line.line_total_net)
        if current_price <= 0:
            continue
        keys, category, _ = _uploaded_line_identity(
            line,
            latest_mappings=latest_mappings,
            ontology=ontology,
        )
        observations = {
            row["lineId"]: row for key in keys for row in observations_by_key.get(key, [])
        }
        ordered_observations = sorted(
            observations.values(),
            key=lambda row: (row["invoiceDate"] or "", row["invoiceNumber"], row["lineId"]),
        )
        if len(ordered_observations) < minimum_count:
            continue
        statistics = calculate_benchmark_statistics(
            Decimal(str(row["price"])) for row in ordered_observations
        )
        p90 = statistics.percentile_90
        if p90 is None or p90 <= 0:
            continue
        difference = (current_price - p90).quantize(Decimal("0.01"))
        percentage = (difference / p90 * Decimal("100")).quantize(Decimal("0.1"))
        challenged = difference > 0
        decision = "Challenge" if challenged else "Within Benchmark"
        relation = "exceeds" if challenged else "is at or below"
        explanation = (
            f"The current charge of £{current_price:.2f} {relation} the historical "
            f"P90 benchmark of £{p90:.2f}"
            + (
                f" by £{difference:.2f} ({percentage:.1f}%)."
                if challenged
                else "; no price challenge is recommended."
            )
        )
        results[line.id] = {
            "category": category,
            "currentPrice": _money_float(current_price),
            "historicalCount": statistics.count,
            "historicalMean": _money_float(statistics.mean),
            "p90": _money_float(p90),
            "difference": _money_float(difference),
            "percentageDifference": float(percentage),
            "decision": decision,
            "challenged": challenged,
            "explanation": explanation,
            "observations": ordered_observations,
            "method": "Interpolated percentile (PERCENTILE.INC)",
            "currentInvoiceExcluded": True,
        }
    return results


def _uploaded_vehicle_category(
    invoice: Invoice,
    vehicles: dict[str, Vehicle],
) -> str:
    vehicle = vehicles.get(invoice.vehicle_id) if invoice.vehicle_id else None
    if vehicle is None:
        return "Unclassified"
    return str(
        vehicle.insurance_group_category
        or vehicle.market_segment
        or vehicle.official_vehicle_class
        or "Unclassified"
    )


def _uploaded_batch_benchmark_dashboard(
    graph: dict[str, Any],
    *,
    vehicle_class: str | None = None,
    ontology_item_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    minimum_count: int = 1,
    challenge_threshold_pct: Decimal | int | float = Decimal("10"),
) -> dict[str, Any] | None:
    """Build dashboard rows and graph edges from one uploaded invoice batch.

    Every P90 exception is produced by ``_uploaded_line_p90_benchmarks`` so the
    aggregate table, Review Findings and repairer graph share one population and
    one current-invoice-exclusion rule.
    """

    invoices: list[Invoice] = graph["invoices"]
    if not invoices:
        return None
    invoice_by_id = {invoice.id: invoice for invoice in invoices}
    latest_mappings = _latest_by(graph["mappings"], "invoice_line_item_id")
    ontology: dict[str, OntologyItem] = graph["ontology"]
    vehicles: dict[str, Vehicle] = graph["vehicles"]

    records: list[dict[str, Any]] = []
    records_by_line: dict[str, dict[str, Any]] = {}
    for line in graph["lines"]:
        invoice = invoice_by_id.get(line.invoice_id)
        if invoice is None or line.status == ReviewStatus.REJECTED:
            continue
        cost = _decimal(line.line_total_net)
        if cost <= 0:
            continue
        _, category, item_id = _uploaded_line_identity(
            line,
            latest_mappings=latest_mappings,
            ontology=ontology,
        )
        vehicle = vehicles.get(invoice.vehicle_id) if invoice.vehicle_id else None
        record = {
            "line": line,
            "invoice": invoice,
            "itemId": item_id,
            "item": category,
            "vehicleClass": _uploaded_vehicle_category(invoice, vehicles),
            "cost": cost,
            "source": {
                "id": line.id,
                "invoiceDate": invoice.invoice_date,
                "amount": _money_float(cost),
                "vehicleClass": _uploaded_vehicle_category(invoice, vehicles),
                "vehicleMake": vehicle.make if vehicle else None,
                "vehicleModel": vehicle.model if vehicle else None,
                "rawDescription": line.raw_description,
                "sourceRecordId": invoice.invoice_number or invoice.id,
                "repairer": invoice.supplier_name or "Unknown repairer",
                "source": {
                    "evidence_label": "Uploaded repair invoice",
                    "invoice_id": invoice.id,
                    "line_id": line.id,
                },
            },
        }
        records.append(record)
        records_by_line[line.id] = record
    if not records:
        return None

    available_vehicle_classes = sorted({str(row["vehicleClass"]) for row in records})
    available_items = sorted(
        {(str(row["itemId"]), str(row["item"])) for row in records},
        key=lambda row: row[1],
    )
    filtered_records = [
        row
        for row in records
        if (vehicle_class is None or row["vehicleClass"] == vehicle_class)
        and (ontology_item_id is None or row["itemId"] == ontology_item_id)
        and (
            date_from is None
            or (row["invoice"].invoice_date and row["invoice"].invoice_date >= date_from)
        )
        and (
            date_to is None
            or (row["invoice"].invoice_date and row["invoice"].invoice_date <= date_to)
        )
    ]

    threshold_percentage = Decimal(str(challenge_threshold_pct))
    minimum_amount = DEFAULT_COMPARISON_POLICY.minimum_challenge_amount
    exceptions_by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for invoice in invoices:
        for line_id, result in _uploaded_line_p90_benchmarks(
            graph,
            current_invoice=invoice,
        ).items():
            record = records_by_line.get(line_id)
            if record is None or record not in filtered_records:
                continue
            difference = Decimal(str(result["difference"]))
            percentage = Decimal(str(result["percentageDifference"]))
            if difference < minimum_amount or percentage <= threshold_percentage:
                continue
            exception = {
                "observationId": line_id,
                "invoiceNumber": invoice.invoice_number or invoice.id,
                "repairer": invoice.supplier_name or "Unknown repairer",
                "description": record["line"].raw_description,
                "amount": result["currentPrice"],
                "p90": result["p90"],
                "difference": result["difference"],
                "percentageAboveP90": result["percentageDifference"],
                "historicalCount": result["historicalCount"],
            }
            group_key = (
                str(record["itemId"]),
                str(record["item"]),
                str(record["vehicleClass"]),
            )
            exceptions_by_group.setdefault(group_key, []).append(exception)

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in filtered_records:
        group_key = (
            str(record["itemId"]),
            str(record["item"]),
            str(record["vehicleClass"]),
        )
        groups.setdefault(group_key, []).append(record)

    details: list[dict[str, Any]] = []
    repairer_item_exceptions: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for (item_id, item_name, category), group_records in groups.items():
        statistics = calculate_benchmark_statistics(row["cost"] for row in group_records)
        if statistics.count < max(1, minimum_count):
            continue
        labour_rates = [
            rate
            for row in group_records
            if _enum_value(row["line"].item_kind) == LineItemKind.LABOUR.value
            and (rate := _decimal(row["line"].unit_price_net)) > 0
        ]
        exceptions = sorted(
            exceptions_by_group.get((item_id, item_name, category), []),
            key=lambda row: (str(row["invoiceNumber"]), str(row["observationId"])),
        )
        for exception in exceptions:
            repairer = str(exception["repairer"])
            repairer_item_exceptions.setdefault(
                (_repairer_group_key(repairer), item_id, item_name),
                [],
            ).append(exception)
        latest_observed = max(
            (row["invoice"].invoice_date for row in group_records if row["invoice"].invoice_date),
            default=None,
        )
        details.append(
            {
                "ontologyItemId": item_id,
                "item": item_name,
                "vehicleClass": category,
                "statistics": statistics.payload(),
                "labourStatistics": calculate_benchmark_statistics(labour_rates).payload(),
                "sourceCount": len(group_records),
                "invoiceCount": len(
                    {
                        str(row["invoice"].invoice_number or row["invoice"].id)
                        for row in group_records
                    }
                ),
                "exceptionCount": len(exceptions),
                "exceptionInvoiceCount": len({str(row["invoiceNumber"]) for row in exceptions}),
                "exceptions": exceptions,
                "sourceObservations": [
                    row["source"]
                    for row in sorted(
                        group_records,
                        key=lambda row: (
                            row["invoice"].invoice_date or date.min,
                            str(row["invoice"].invoice_number or row["invoice"].id),
                            row["line"].sequence_no,
                        ),
                    )
                ],
                "sampleStrength": (
                    "strong"
                    if statistics.count >= 10
                    else "usable"
                    if statistics.count >= 3
                    else "insufficient"
                ),
                "latestObservedAt": latest_observed,
            }
        )

    details.sort(key=lambda row: (-int(row["statistics"]["count"]), str(row["item"])))
    all_costs = [row["cost"] for row in filtered_records]
    overall = calculate_benchmark_statistics(all_costs)
    labour_rates = [
        rate
        for row in filtered_records
        if _enum_value(row["line"].item_kind) == LineItemKind.LABOUR.value
        and (rate := _decimal(row["line"].unit_price_net)) > 0
    ]
    labour = calculate_benchmark_statistics(labour_rates)
    category_costs: dict[str, list[Decimal]] = {}
    for row in filtered_records:
        category_costs.setdefault(str(row["vehicleClass"]), []).append(row["cost"])
    category_totals = [
        {
            "vehicleClass": category,
            "averageCost": _money_float(stats.mean) if stats.mean is not None else None,
            "count": stats.count,
        }
        for category, costs in category_costs.items()
        if (stats := calculate_benchmark_statistics(costs)).count
    ]
    category_totals.sort(key=lambda row: (-int(row["count"]), str(row["vehicleClass"])))
    most_observed = details[0] if details else None
    highest_category = max(
        details,
        key=lambda row: row["statistics"]["mean"] or 0,
        default=None,
    )
    classified_records = [row for row in records if row["vehicleClass"] != "Unclassified"]
    latest_observation = max(
        (row["invoice"].invoice_date for row in records if row["invoice"].invoice_date),
        default=None,
    )
    return {
        "summary": {
            "averageRepairCost": _money_float(overall.mean) if overall.mean is not None else None,
            "averageLabourRate": _money_float(labour.mean) if labour.mean is not None else None,
            "mostObservedItem": most_observed["item"] if most_observed else None,
            "observationCount": overall.count,
            "mostExpensiveRepairCategory": highest_category["item"] if highest_category else None,
            "mostExpensiveRepairAverage": (
                highest_category["statistics"]["mean"] if highest_category else None
            ),
        },
        "vehicleCategories": category_totals,
        "benchmarks": details,
        "repairerTrends": _build_repairer_trends(repairer_item_exceptions),
        "filterOptions": {
            "vehicleClasses": available_vehicle_classes,
            "repairItems": [{"id": item_id, "name": name} for item_id, name in available_items],
        },
        "appliedFilters": {
            "vehicleClass": vehicle_class,
            "ontologyItemId": ontology_item_id,
            "dateFrom": date_from,
            "dateTo": date_to,
            "minimumCount": max(1, minimum_count),
            "challengeThresholdPct": float(threshold_percentage),
            "minimumChallengeAmount": _money_float(minimum_amount),
        },
        "dataQuality": {
            "invoiceObservationCount": len(records),
            "validCostCount": len(records),
            "invalidOrMissingCostCount": 0,
            "classifiedCount": len(classified_records),
            "unclassifiedCount": len(records) - len(classified_records),
            "classifiedCoveragePct": (
                round((len(classified_records) / len(records)) * 100, 1) if records else 0
            ),
            "latestObservationDate": latest_observation,
        },
        "definitions": {
            "cost": "Net line totals from the invoices uploaded to this claim batch.",
            "labour": "Extracted hourly labour rate where the uploaded line is labour.",
            "challengeGate": (
                "A rolling P90 exception must exceed the selected percentage threshold and "
                f"the £{minimum_amount:.2f} minimum positive variance. The current invoice is excluded."
            ),
            "officialClasses": {},
            "coverageNote": (
                "This table, its challenge counts and the knowledge graph use the same "
                "uploaded-invoice batch and canonical ontology mappings."
            ),
        },
    }


def build_uploaded_batch_benchmark_dashboard(
    session: Session,
    case_reference: str,
    **filters: Any,
) -> dict[str, Any] | None:
    """Load one claim batch and return its uploaded-invoice benchmark dashboard."""

    return _uploaded_batch_benchmark_dashboard(
        _load_case_graph(session, case_reference),
        **filters,
    )


def build_claim_workspace(
    session: Session,
    case_reference: str,
    *,
    invoice_id: str | None = None,
) -> dict[str, Any]:
    """Serialize a case into the compact shadcn reviewer workspace contract."""

    graph = _load_case_graph(session, case_reference)
    result = build_case_result(session, case_reference, _graph=graph)
    case: Case = graph["case"]
    context: ClaimContext | None = graph["context"]
    liability: LiabilityAssessment | None = graph["liability"]
    invoices: list[Invoice] = graph["invoices"]
    invoice = (
        next((row for row in invoices if row.id == invoice_id), None)
        if invoice_id
        else next(
            (row for row in reversed(invoices) if _enum_value(row.document_role) == "invoice"),
            invoices[-1] if invoices else None,
        )
    )
    if invoice is None:
        if invoice_id:
            raise ValueError("The selected invoice does not belong to this claim.")
        raise ValueError("The claim has no extracted invoice.")

    claim_parties = {party.party_role: party for party in (context.parties if context else [])}
    claim_vehicles = {
        vehicle.vehicle_role: vehicle for vehicle in (context.vehicles if context else [])
    }
    invoice_vehicle = graph["vehicles"].get(invoice.vehicle_id or "")
    insured_vehicle = claim_vehicles.get(ClaimVehicleRole.INSURED_VEHICLE)
    third_party_vehicle = claim_vehicles.get(
        ClaimVehicleRole.THIRD_PARTY_VEHICLE
    ) or claim_vehicles.get(ClaimVehicleRole.CLAIMANT_VEHICLE)

    uploaded_line_benchmarks = _uploaded_line_p90_benchmarks(
        graph,
        current_invoice=invoice,
    )

    invoice_pages = sorted(
        (page for page in graph["pages"] if page.document_id == invoice.document_id),
        key=lambda page: page.page_number,
    )
    pages_by_id = {page.id: page for page in invoice_pages}
    pages_by_number = {page.page_number: page for page in invoice_pages}
    model_lines = {line.id: line for line in graph["lines"] if line.invoice_id == invoice.id}
    result_lines = {row["id"]: row for row in result["lines"] if row["invoice_id"] == invoice.id}
    mappings = {row["line_id"]: row for row in result["mappings"]}
    comparisons = {row["line_id"]: row for row in result["comparisons"]}
    challenges = {row["line_id"]: row for row in result["challenges"]}
    lines = []
    for line_id, row in result_lines.items():
        model_line = model_lines[line_id]
        rejected = row.get("review_status") == ReviewStatus.REJECTED.value
        mapping = mappings.get(line_id)
        comparison = comparisons.get(line_id)
        challenge = challenges.get(line_id)
        mapping_review_status = str((mapping or {}).get("status") or "").upper()
        item = (
            graph["ontology"].get(mapping["ontology_item_id"])
            if mapping and mapping.get("ontology_item_id")
            else None
        )
        approval = item.approval_status if item else None
        if rejected:
            mapping_status = "EXCLUDED"
        elif mapping and mapping.get("is_bundled"):
            allocation_resolved = bool(
                (mapping.get("flags") or {}).get("bundle_allocation_resolved")
            )
            mapping_status = "MATCH" if allocation_resolved else "PROVISIONAL"
        elif mapping is None or mapping.get("ontology_item_id") is None:
            mapping_status = "NO_MATCH"
        elif mapping_review_status in {"AUTO_ACCEPTED", "APPROVED"}:
            mapping_status = "MATCH"
        elif approval == ApprovalStatus.APPROVED:
            mapping_status = "MATCH"
        else:
            mapping_status = "PROVISIONAL"

        challenge_amount = _decimal(challenge["challenge_amount_net"] if challenge else 0)
        flags = comparison.get("eligibility", {}).get("flags", []) if comparison else []
        if rejected:
            comparison_status = "EXCLUDED"
        elif comparison is None:
            comparison_status = "MISSING"
        elif challenge_amount > 0:
            comparison_status = "CHALLENGE"
        elif any("gate" in str(flag).lower() for flag in flags):
            comparison_status = "BELOW_GATE"
        else:
            comparison_status = "WITHIN"
        score_breakdown = next(
            (
                item.score_breakdown_json
                for item in graph["line_challenges"]
                if comparison and item.price_comparison_id == comparison["id"]
            ),
            {},
        )
        rationale = (
            (challenge or mapping or {}).get("reason")
            or (mapping or {}).get("rationale")
            or "Awaiting review."
        )
        if challenge and comparison and challenge_amount > 0:
            evidence_parts = []
            if comparison.get("ontology_price_net") is not None:
                evidence_parts.append(
                    f"approved ontology £{_decimal(comparison['ontology_price_net']):.2f}"
                )
            if comparison.get("historical_median_net") is not None:
                count = int(comparison.get("historical_count", 0))
                evidence_parts.append(
                    f"historical median £{_decimal(comparison['historical_median_net']):.2f} "
                    f"from {count} comparable claim{'' if count == 1 else 's'}"
                )
            rationale = (
                f"{row['description']}: billed £{_decimal(row.get('invoice_net')):.2f}; "
                f"{' and '.join(evidence_parts) or 'governed evidence'} supports "
                f"£{_decimal(challenge.get('challenge_price_net')):.2f}. "
                f"Line challenge: £{challenge_amount:.2f}."
            )
        kind_value = str(row["kind"] or "unknown").lower()
        kind = (
            "Labour"
            if kind_value == "labour"
            else "Service"
            if kind_value in {"service", "mot"}
            else "Fee"
            if kind_value == "fee"
            else "Part"
        )
        workspace_line = {
            "id": line_id,
            "description": row["description"],
            "partNumber": row.get("part_number"),
            "kind": kind,
            "quantity": float(_decimal(row.get("quantity"), "1")),
            "unit": row.get("unit") or "item",
            "unitPrice": _money_float(row.get("unit_price_net")),
            "currentTotal": _money_float(row.get("invoice_net")),
            "vatRate": float(_decimal(row.get("vat_rate"))),
            "historicalCount": int(comparison.get("historical_count", 0)) if comparison else 0,
            "challenge": _money_float(challenge_amount),
            "extractionConfidence": _percent(row.get("extraction_confidence")),
            "extractionReviewStatus": row.get("review_status") or "pending",
            "requiresExtractionReview": (
                _decimal(row.get("extraction_confidence"))
                < _decimal(settings.extraction_review_threshold)
                and row.get("review_status")
                not in {
                    ReviewStatus.APPROVED.value,
                    ReviewStatus.CORRECTED.value,
                    ReviewStatus.REJECTED.value,
                }
            ),
            "source": _source_record(
                page=pages_by_id.get(model_line.source_page_id or ""),
                regions=model_line.source_regions_json,
                fallback_bbox=model_line.source_bbox_json,
                raw_text=model_line.source_raw_text,
                method=model_line.extraction_method,
            ),
            "mappingStatus": mapping_status,
            "comparisonStatus": comparison_status,
            "rationale": rationale,
        }
        if p90_benchmark := uploaded_line_benchmarks.get(line_id):
            workspace_line["p90Benchmark"] = p90_benchmark
        if mapping:
            workspace_line.update(
                {
                    "ontologyId": mapping.get("ontology_item_id"),
                    "ontologyName": mapping.get("ontology_item_name")
                    or (
                        " + ".join(
                            component.get("canonical_name", "Unnamed component")
                            for component in (mapping.get("bundle_components") or [])
                        )
                        if mapping.get("is_bundled")
                        else None
                    ),
                    "mappingConfidence": _percent(mapping.get("mapping_confidence")),
                    "mappingDecision": mapping.get("decision"),
                    "mappingReviewStatus": mapping.get("status"),
                    "mappingReviewedBy": mapping.get("reviewed_by"),
                    "mappingReviewedAt": mapping.get("reviewed_at"),
                    "isBundled": bool(mapping.get("is_bundled")),
                    "bundleComponents": mapping.get("bundle_components") or [],
                }
            )
        if comparison:
            formula = comparison.get("formula") or {}
            eligibility = comparison.get("eligibility") or {}
            workspace_line.update(
                {
                    "ontologyTotal": _money_float(comparison.get("ontology_price_net")),
                    "historicalMedian": _money_float(comparison.get("historical_median_net")),
                    "recommended": _money_float(
                        challenge.get("challenge_price_net")
                        if challenge
                        else comparison.get("challenge_price_net")
                    ),
                    "governedBenchmark": _optional_money_float(
                        comparison.get("challenge_price_net")
                    ),
                    "governedBenchmarkSource": comparison.get("benchmark_source"),
                    "governedBenchmarkFormula": formula.get("formula"),
                    "differenceFromOntology": _optional_money_float(
                        comparison.get("difference_from_ontology_net")
                    ),
                    "differenceFromHistory": _optional_money_float(
                        comparison.get("difference_from_history_net")
                    ),
                    "comparables": [
                        {
                            "id": comparable["id"],
                            "sourceType": comparable["source_type"],
                            "sourceObservationId": comparable["source_observation_id"],
                            "description": comparable["description"],
                            "priceNet": _optional_money_float(comparable["price_net"]),
                            "originalPriceNet": _optional_money_float(
                                comparable["original_price_net"]
                            ),
                            "normalisedPriceNet": _optional_money_float(
                                comparable["normalised_price_net"]
                            ),
                            "observedDate": (
                                comparable["observed_date"].isoformat()
                                if comparable["observed_date"]
                                else None
                            ),
                            "weight": float(_decimal(comparable["weight"])),
                            "approvalStatus": comparable["approval_status"],
                            "settlementStatus": comparable["settlement_status"],
                            "provenance": comparable["provenance"],
                            "vehicle": comparable["vehicle"],
                            "comparabilityMetadata": comparable["comparability_metadata"],
                            "comparableClass": comparable["comparable_class"],
                            "adjustments": comparable["adjustments"],
                            "staleDataWarning": comparable["stale_data_warning"],
                            "eligible": comparable["eligible"],
                            "eligibilityReason": comparable["eligibility_reason"],
                        }
                        for comparable in comparison.get("comparables", [])
                    ],
                    "evidenceRationale": eligibility.get("lineage_note")
                    or formula.get("formula")
                    or "Persisted ontology and historic evidence.",
                }
            )
            if (
                comparison.get("historical_p25_net") is not None
                and comparison.get("historical_p75_net") is not None
            ):
                workspace_line["historicalRange"] = [
                    _money_float(comparison["historical_p25_net"]),
                    _money_float(comparison["historical_p75_net"]),
                ]
        if challenge:
            workspace_line.update(
                {
                    "challengeResultId": challenge.get("id"),
                    "challengeStatus": challenge.get("status"),
                    "challengeApproved": bool(challenge.get("approved")),
                    "challengeVat": _money_float(challenge.get("challenge_vat")),
                    "challengeStrength": int(challenge.get("challenge_score") or 0),
                }
            )
        evidence_confidence = score_breakdown.get("price_evidence_confidence")
        if evidence_confidence is not None:
            workspace_line["evidenceConfidence"] = _percent(evidence_confidence)
        lines.append(workspace_line)

    invoice_net = _decimal(invoice.subtotal_net) + _decimal(invoice.non_vat_total)
    reviewable_lines = [
        line
        for line in lines
        if _decimal(line.get("challenge")) > 0 and line.get("challengeStatus") != "rejected"
    ]
    challenge_amount = sum(
        (_decimal(line.get("challenge")) for line in reviewable_lines), Decimal("0")
    )
    vat_impact = sum(
        (_decimal(line.get("challengeVat")) for line in reviewable_lines), Decimal("0")
    )
    challenge_price = invoice_net - challenge_amount
    invoice_challenge = next(
        (row for row in graph["invoice_challenges"] if row.invoice_id == invoice.id),
        None,
    )
    challenge_percentage = (
        _decimal(invoice_challenge.challenge_percentage)
        if invoice_challenge
        else challenge_amount / invoice_net * Decimal("100")
        if invoice_net > 0
        else Decimal("0")
    )
    challenge_strength = (
        int(invoice_challenge.evidence_strength_score or 0) if invoice_challenge else 0
    )
    vehicle = invoice_vehicle

    research_tasks: list[ResearchTask] = graph["research_tasks"]
    task_ids = [task.id for task in research_tasks]
    research_suggestions = {
        item.research_task_id: item
        for item in (
            session.scalars(
                select(ResearchItem).where(ResearchItem.research_task_id.in_(task_ids))
            ).all()
            if task_ids
            else []
        )
    }
    evidence_by_task: dict[str, list[ExternalEvidence]] = {}
    for evidence in graph["evidence"]:
        evidence_by_task.setdefault(evidence.research_task_id, []).append(evidence)
    line_descriptions = {line.id: line.raw_description for line in graph["lines"]}
    research_records = []
    for task in sorted(research_tasks, key=lambda item: item.created_at, reverse=True):
        suggestion = research_suggestions.get(task.id)
        research_records.append(
            {
                "taskId": task.id,
                "researchItemId": suggestion.id if suggestion else None,
                "lineId": task.invoice_line_item_id,
                "lineDescription": line_descriptions.get(task.invoice_line_item_id, "Invoice line"),
                "queryText": task.query_text,
                "status": _display_status(suggestion.status if suggestion else task.status),
                "sourceAllowListVersion": task.source_allow_list_version,
                # Task B2: distinguish machine-staged proposals (from an unmatched
                # priced invoice line) from reviewer-triggered research in the UI.
                "initiatedAutomatically": task.initiated_automatically,
                "sourceType": (
                    ((suggestion.raw_suggestion_json or {}).get("workflow") or {}).get(
                        "source_type"
                    )
                    if suggestion
                    else None
                ),
                "candidate": suggestion.suggested_canonical_name if suggestion else None,
                "itemType": _enum_value(suggestion.suggested_item_type) if suggestion else None,
                "category": suggestion.suggested_category if suggestion else None,
                "unit": suggestion.suggested_unit if suggestion else None,
                "partNumber": suggestion.suggested_part_number if suggestion else None,
                "priceNet": _optional_money_float(suggestion.suggested_price_net)
                if suggestion
                else None,
                "sourceUrls": list(suggestion.source_urls_json) if suggestion else [],
                "dateChecked": suggestion.date_checked.isoformat() if suggestion else None,
                "confidence": _percent(suggestion.confidence)
                if suggestion and suggestion.confidence is not None
                else None,
                "rationale": suggestion.rationale if suggestion else None,
                "reviewer": suggestion.reviewer if suggestion else None,
                "reviewedAt": suggestion.reviewed_at if suggestion else None,
                "ontologyItemId": suggestion.provisional_ontology_item_id if suggestion else None,
                "evidence": [
                    {
                        "id": evidence.id,
                        "title": evidence.title,
                        "sourceUri": evidence.source_uri,
                        "capturedAt": evidence.captured_at,
                        "priceNet": _optional_money_float(evidence.price_net),
                        "approvalStatus": _display_status(evidence.approval_status),
                    }
                    for evidence in evidence_by_task.get(task.id, [])
                ],
            }
        )

    ontology_items = list(
        session.scalars(select(OntologyItem).order_by(OntologyItem.canonical_code)).all()
    )
    ontology_item_ids = [item.id for item in ontology_items]
    price_observations = list(
        session.scalars(
            select(PriceObservation)
            .where(PriceObservation.ontology_item_id.in_(ontology_item_ids))
            .order_by(PriceObservation.effective_from.desc(), PriceObservation.created_at.desc())
        ).all()
        if ontology_item_ids
        else []
    )
    observations_by_item: dict[str, list[PriceObservation]] = {}
    for observation in price_observations:
        if observation.ontology_item_id:
            observations_by_item.setdefault(observation.ontology_item_id, []).append(observation)
    provider_ids = {
        observation.source_provider_id
        for observation in price_observations
        if observation.source_provider_id
    }
    source_providers = {
        provider.id: provider
        for provider in (
            session.scalars(select(SourceProvider).where(SourceProvider.id.in_(provider_ids))).all()
            if provider_ids
            else []
        )
    }
    ontology_versions = {version.id: version for version in graph["versions"]}
    ontology_bank_items = [
        {
            "id": item.id,
            "code": item.canonical_code,
            "name": item.canonical_name,
            "itemType": _display_status(item.item_type).title(),
            "category": item.category,
            "unit": item.unit,
            "referencePriceNet": _optional_money_float(item.reference_price_net),
            "status": _display_status(item.status),
            "approvalStatus": _display_status(item.approval_status),
            "confidence": _display_status(item.confidence_level),
            "observationCount": len(observations_by_item.get(item.id, [])),
            "source": item.price_source,
            "sourceRef": item.source_url_or_ref,
            "effectiveDate": item.effective_date.isoformat() if item.effective_date else None,
            "createdInVersion": (
                ontology_versions[item.created_in_version_id].label
                if item.created_in_version_id in ontology_versions
                else None
            ),
        }
        for item in ontology_items
    ]
    ontology_price_records = [
        {
            "id": observation.id,
            "ontologyItemId": observation.ontology_item_id,
            "ontologyCode": next(
                (
                    item.canonical_code
                    for item in ontology_items
                    if item.id == observation.ontology_item_id
                ),
                None,
            ),
            "source": observation.source_type,
            "sourceRef": observation.source_url_or_ref,
            "providerName": (
                source_providers[observation.source_provider_id].name
                if observation.source_provider_id in source_providers
                else None
            ),
            "date": observation.effective_from.isoformat(),
            "unit": observation.unit,
            "priceScope": _enum_value(observation.price_scope),
            "vatBasis": _enum_value(observation.vat_basis),
            "originalPrice": _optional_money_float(observation.original_price),
            "priceNet": _money_float(observation.price_net),
            "approvalStatus": _display_status(observation.approval_status),
        }
        for observation in price_observations[:200]
    ]
    total_sources_payload = ((invoice.extraction_payload_json or {}).get("totals") or {}).get(
        "sources"
    ) or {}
    total_sources = {
        name: _payload_source_record(source, pages_by_number)
        for name, source in total_sources_payload.items()
    }
    source_by_line = {line["id"]: line.get("source") for line in lines}

    def line_total_sources(predicate: Any) -> list[dict[str, Any]]:
        references = []
        for line in lines:
            if line.get("extractionReviewStatus") == ReviewStatus.REJECTED.value:
                continue
            if predicate(line):
                reference = _source_reference(
                    source_by_line.get(line["id"]), "line_total", "Line total"
                )
                if reference:
                    references.append(reference)
        return references

    live_checks = []
    for finding in (row for row in graph["checks"] if row.invoice_id == invoice.id):
        references: list[dict[str, Any] | None] = []
        code = finding.check_code
        if finding.line_item_id:
            source = source_by_line.get(finding.line_item_id)
            references.extend(
                [
                    _source_reference(source, "quantity", "Quantity"),
                    _source_reference(source, "unit_price", "Unit price"),
                    _source_reference(source, "line_total", "Line total"),
                ]
            )
        elif code == "LABOUR_TOTAL_MISMATCH":
            references.extend(line_total_sources(lambda line: line.get("kind") == "Labour"))
            references.append(
                _source_reference(total_sources.get("labour_net"), "value", "Printed labour")
            )
        elif code == "PARTS_TOTAL_MISMATCH":
            references.extend(
                line_total_sources(
                    lambda line: line.get("kind") != "Labour" and _decimal(line.get("vatRate")) > 0
                )
            )
            references.append(
                _source_reference(total_sources.get("parts_net"), "value", "Printed parts")
            )
        elif code == "SUBTOTAL_MISMATCH":
            references.extend(line_total_sources(lambda line: _decimal(line.get("vatRate")) > 0))
            references.append(
                _source_reference(total_sources.get("subtotal_net"), "value", "Printed subtotal")
            )
        elif code == "VAT_MISCALC":
            references.extend(
                [
                    _source_reference(total_sources.get("subtotal_net"), "value", "Subtotal"),
                    _source_reference(total_sources.get("vat_amount"), "value", "VAT"),
                ]
            )
        elif code == "TOTAL_MISMATCH":
            references.extend(
                [
                    _source_reference(total_sources.get("subtotal_net"), "value", "Subtotal"),
                    _source_reference(total_sources.get("vat_amount"), "value", "VAT"),
                    _source_reference(total_sources.get("non_vatable"), "value", "MOT"),
                    _source_reference(total_sources.get("total_gross"), "value", "Gross total"),
                ]
            )
        live_checks.append(
            {
                "id": finding.id,
                "type": code,
                "status": _enum_value(finding.status),
                "severity": _enum_value(finding.severity),
                "expected": _optional_money_float(finding.expected_value),
                "observed": _optional_money_float(finding.observed_value),
                "difference": _optional_money_float(finding.difference),
                "explanation": finding.explanation,
                "lineId": finding.line_item_id,
                "sources": [reference for reference in references if reference],
            }
        )
    check_order = {"fail": 0, "not_applicable": 1, "pass": 2}
    live_checks.sort(key=lambda check: check_order.get(str(check["status"]), 1))
    current_run = (
        session.get(ProcessingRun, case.current_processing_run_id)
        if case.current_processing_run_id
        else None
    )
    return {
        "liability": {
            "status": _display_status(liability.effective_status if liability else None),
            "humanConfirmed": bool(liability and liability.human_confirmed),
            "confirmedBy": liability.confirmed_by if liability else None,
            "rationale": liability.human_rationale if liability else None,
            "splitLiabilityPercentage": (
                float(_decimal(liability.split_liability_percentage))
                if liability and liability.split_liability_percentage is not None
                else None
            ),
        },
        "claim": {
            "id": case.case_reference,
            "status": _enum_value(case.status),
            "policyNumber": (context.paying_policy_number or context.claiming_policy_number or "")
            if context
            else "",
            "accidentDate": _date_label(context.accident_at if context else None),
            "accidentLocation": context.accident_location or "" if context else "",
            "accidentDescription": context.accident_description or "" if context else "",
            "damageDescription": context.damage_description or "" if context else "",
            "payingInsurer": context.paying_insurer_name or "" if context else "",
            "claimingParty": context.claiming_insurer_name or context.third_party_name or ""
            if context
            else "",
            "insuredDriver": (
                claim_parties.get(ClaimPartyRole.INSURED_DRIVER).name
                if claim_parties.get(ClaimPartyRole.INSURED_DRIVER)
                else ""
            ),
            "thirdPartyDriver": (
                claim_parties.get(ClaimPartyRole.CLAIMANT_DRIVER).name
                if claim_parties.get(ClaimPartyRole.CLAIMANT_DRIVER)
                else claim_parties.get(ClaimPartyRole.THIRD_PARTY).name
                if claim_parties.get(ClaimPartyRole.THIRD_PARTY)
                else ""
            ),
            "insuredVehicle": _vehicle_label(insured_vehicle),
            "insuredVrm": insured_vehicle.registration or "" if insured_vehicle else "",
            "thirdPartyVehicle": _vehicle_label(third_party_vehicle) or _vehicle_label(vehicle),
            "thirdPartyVrm": (
                third_party_vehicle.registration
                if third_party_vehicle
                else vehicle.registration
                if vehicle
                else ""
            )
            or "",
        },
        "invoice": {
            "id": invoice.id,
            "documentId": invoice.document_id,
            "pageNumbers": [page.page_number for page in invoice_pages],
            "extractionReviewThreshold": settings.extraction_review_threshold,
            "number": invoice.invoice_number or "",
            "date": _date_label(invoice.invoice_date),
            "garage": invoice.supplier_name or "",
            "address": invoice.supplier_address or "",
            "vehicle": _vehicle_label(vehicle),
            "vehicleCategory": {
                "groupRange": vehicle.insurance_group_range if vehicle else None,
                "groupCategory": (vehicle.insurance_group_category if vehicle else None),
                "source": vehicle.insurance_group_source if vehicle else None,
                "matchStatus": (
                    vehicle.insurance_group_match_status if vehicle else "manual_review"
                ),
            },
            "vrm": vehicle.registration or "" if vehicle else "",
            "mileage": int(vehicle.mileage or 0) if vehicle else 0,
            "partsNet": _money_float(invoice.parts_net),
            "labourNet": _money_float(invoice.labour_net),
            "taxableNet": _money_float(invoice.subtotal_net),
            "vat": _money_float(invoice.vat_total),
            "mot": _money_float(invoice.non_vat_total),
            "netIncludingMot": _money_float(invoice_net),
            "gross": _money_float(invoice.gross_total),
        },
        "lines": lines,
        "checks": live_checks,
        "summary": {
            "challengePrice": _money_float(challenge_price),
            "challengeAmount": _money_float(challenge_amount),
            "vatImpact": _money_float(vat_impact),
            "grossEffect": _money_float(challenge_amount + vat_impact),
            "challengePercentage": float(challenge_percentage.quantize(Decimal("0.01"))),
            "challengeStrength": challenge_strength,
        },
        "researchItems": research_records,
        "ontologyBank": {
            "items": ontology_bank_items,
            "versions": result["versions"],
            "priceObservations": ontology_price_records,
        },
        "auditEvents": result["audit"],
        "versions": {
            "ontology": (
                ontology_versions[current_run.ontology_version_id].label
                if current_run and current_run.ontology_version_id in ontology_versions
                else next(
                    (
                        version.label
                        for version in reversed(graph["versions"])
                        if _enum_value(version.status) == "published"
                    ),
                    "unversioned",
                )
            ),
            "policy": current_run.benchmark_policy_version if current_run else "claimguard-v1.4",
            "processingRunId": current_run.id if current_run else None,
            "application": current_run.application_version if current_run else None,
        },
    }
