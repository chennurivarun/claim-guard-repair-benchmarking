from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.comparison import CurrentInvoiceLine, LineComparison, aggregate_challenges, compare_line
from app.domain.money import ZERO, money, percentage
from app.domain.normalisation import normalise_description
from app.enums import (
    ApprovalStatus,
    AuditActorType,
    CaseStatus,
    ChallengeStatus,
    ComparisonStatus,
    MappingDecision,
    MappingStatus,
    ReviewStatus,
)
from app.models import (
    AuditEvent,
    Case,
    ChallengeResult,
    ComparisonComparable,
    HistoricalObservation,
    InvoiceLineItem,
    OntologyItem,
    OntologyMapping,
    OntologySynonym,
    OntologyVersion,
    PriceComparison,
)
from app.services.comparison_workflow import (
    _decimal,
    _eligible_history_pairs,
    _history_domain,
    _ontology_evidence,
    _score_int,
    _type_compatible,
)
from app.services.vehicle_classification import select_vehicle_category_history


class MappingReviewError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BundleComponentDecision:
    ontology_item_id: str
    allocated_net: Decimal | None = None
    quantity: Decimal | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class MappingReviewCommand:
    actor: str
    decision: str
    rationale: str
    ontology_item_id: str | None = None
    bundle_components: tuple[BundleComponentDecision, ...] = ()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _mapping_snapshot(
    mapping: OntologyMapping,
    comparison: PriceComparison,
    challenge: ChallengeResult,
) -> dict[str, Any]:
    return _json_safe(
        {
            "mapping": {
                "id": mapping.id,
                "ontology_item_id": mapping.selected_ontology_item_id,
                "decision": mapping.decision.value,
                "status": mapping.final_status.value,
                "rationale": mapping.rationale,
                "reviewed_by": mapping.reviewed_by,
                "reviewed_at": mapping.reviewed_at.isoformat() if mapping.reviewed_at else None,
                "is_bundled": mapping.is_bundled,
                "bundle_components": mapping.bundle_components_json,
                "flags": mapping.flags_json,
            },
            "comparison": {
                "status": comparison.status.value,
                "benchmark_source": comparison.selected_benchmark_source,
                "benchmark_line_net": comparison.benchmark_line_net,
                "n_comparables": comparison.n_comparables,
                "flags": comparison.eligibility_flags_json,
            },
            "challenge": {
                "status": challenge.status.value,
                "challenge_net": challenge.challenge_net,
                "challenge_vat": challenge.challenge_vat,
                "challenge_gross": challenge.challenge_gross,
                "recommended_payable_net": challenge.recommended_payable_net,
                "reviewer_approved": challenge.reviewer_approved,
            },
        }
    )


def _clear_comparables(session: Session, comparison: PriceComparison) -> None:
    rows = session.scalars(
        select(ComparisonComparable).where(
            ComparisonComparable.price_comparison_id == comparison.id
        )
    ).all()
    for row in rows:
        session.delete(row)


def _invalidate_challenge_review(challenge: ChallengeResult) -> None:
    challenge.status = ChallengeStatus.REVIEW
    challenge.reviewer_approved = False
    challenge.approved_by = None
    challenge.approved_at = None


def _learn_approved_synonym(
    session: Session,
    *,
    line: InvoiceLineItem,
    item: OntologyItem,
    version: OntologyVersion,
) -> str | None:
    """Reuse a handler-approved invoice description for future exact matching."""

    synonym = line.raw_description.strip()
    normalised = normalise_description(synonym)
    if not normalised or normalised == normalise_description(item.canonical_name):
        return None
    existing = session.scalar(
        select(OntologySynonym).where(
            OntologySynonym.normalised_synonym == normalised,
        )
    )
    if existing is not None:
        if existing.ontology_item_id != item.id:
            return None
        if existing.approval_status != ApprovalStatus.APPROVED:
            existing.approval_status = ApprovalStatus.APPROVED
        return existing.id
    learned = OntologySynonym(
        ontology_item_id=item.id,
        synonym=synonym,
        normalised_synonym=normalised,
        source_type="handler_approved_invoice_mapping",
        source_reference=f"invoice_line:{line.id}",
        approval_status=ApprovalStatus.APPROVED,
        created_in_version_id=version.id,
    )
    try:
        with session.begin_nested():
            session.add(learned)
            session.flush()
        return learned.id
    except IntegrityError:
        # Another handler may approve the same description concurrently. The
        # savepoint keeps the outer mapping decision usable; reuse the winner.
        existing = session.scalar(
            select(OntologySynonym).where(
                OntologySynonym.normalised_synonym == normalised,
            )
        )
        if existing is None or existing.ontology_item_id != item.id:
            return None
        if existing.approval_status != ApprovalStatus.APPROVED:
            existing.approval_status = ApprovalStatus.APPROVED
        return existing.id


def _set_non_comparable(
    comparison: PriceComparison,
    challenge: ChallengeResult,
    *,
    invoice_line_net: Decimal,
    flags: list[str],
    formula: str,
) -> None:
    comparison.invoice_unit_net = None
    comparison.invoice_line_net = invoice_line_net
    comparison.ontology_unit_net = None
    comparison.ontology_line_net = None
    comparison.historical_median_unit_net = None
    comparison.historical_line_net = None
    comparison.historical_p25_net = None
    comparison.historical_p75_net = None
    comparison.historical_lowest_recent_net = None
    comparison.market_median_unit_net = None
    comparison.market_line_net = None
    comparison.n_comparables = 0
    comparison.selected_benchmark_source = "none"
    comparison.benchmark_unit_net = None
    comparison.benchmark_line_net = invoice_line_net
    comparison.benchmark_formula_json = {
        "formula": formula,
        "ontology_weight": "0.60",
        "historical_weight": "0.40",
    }
    comparison.eligibility_flags_json = {
        "review_required": True,
        "flags": flags,
        "sources_independent": False,
        "lineage_note": "No financial comparison was performed.",
    }
    comparison.status = ComparisonStatus.REVIEW

    challenge.challenge_net = ZERO
    challenge.challenge_vat = ZERO
    challenge.challenge_gross = ZERO
    challenge.challenge_percentage = ZERO
    challenge.evidence_strength_score = 0
    challenge.evidence_label = "Weak"
    challenge.recommended_payable_net = invoice_line_net
    challenge.narrative = f"Challenge Price £{invoice_line_net:.2f}; {formula}."
    challenge.score_breakdown_json = {
        "mapping_confidence": "0",
        "price_evidence_confidence": "0",
        "challenge_strength": "0",
    }
    challenge.findings_json = {"severity": "neutral", "review_flags": flags}
    _invalidate_challenge_review(challenge)


def _component_comparison(
    session: Session,
    *,
    line: InvoiceLineItem,
    item: OntologyItem,
    version: OntologyVersion,
    allocated_net: Decimal,
    quantity: Decimal | None,
    unit: str | None,
    component_index: int,
) -> tuple[
    LineComparison,
    list[HistoricalObservation],
    tuple[tuple[HistoricalObservation, Any, Decimal, Decimal], ...],
    dict[str, Any],
]:
    invoice = line.invoice
    if invoice.invoice_date is None:
        raise MappingReviewError(
            "INVOICE_DATE_REQUIRED",
            "The source invoice needs a date before its mapping can be compared.",
        )
    history_rows = list(
        session.scalars(
            select(HistoricalObservation)
            .where(HistoricalObservation.ontology_item_id == item.id)
            .order_by(HistoricalObservation.invoice_date)
        ).all()
    )
    history_rows, vehicle_benchmark = select_vehicle_category_history(
        history_rows,
        current_vehicle=invoice.vehicle,
    )
    history_domain = _history_domain(history_rows)
    current = CurrentInvoiceLine(
        line_id=f"{line.id}:bundle:{component_index}",
        description=f"{line.raw_description} / {item.canonical_name}",
        invoice_line_net=allocated_net,
        invoice_date=invoice.invoice_date,
        quantity=quantity,
        unit=unit,
        part_number=item.manufacturer_part_number,
        vat_rate=_decimal(line.vat_rate, "20"),
        vat_applicable=bool(line.vat_applicable),
        is_mot="mot" in line.raw_description.lower(),
    )
    evidence = _ontology_evidence(item, version)
    result = compare_line(
        line=current,
        ontology=evidence,
        history_observations=history_domain,
        mapping_confidence=Decimal("1"),
        price_evidence_confidence=evidence.confidence if evidence else Decimal("0.55"),
    )
    pairs = _eligible_history_pairs(
        history_rows,
        history_domain,
        as_of_date=invoice.invoice_date,
    )
    if len(pairs) != result.history.eligible_count:
        raise MappingReviewError(
            "COMPARABLES_CHANGED",
            "Persisted historical comparables disagree with the bundle calculation.",
        )
    return result, history_rows, pairs, vehicle_benchmark


def _persist_comparable_pairs(
    session: Session,
    comparison: PriceComparison,
    pairs: tuple[tuple[HistoricalObservation, Any, Decimal, Decimal], ...],
    *,
    component_index: int | None = None,
    ontology_item_id: str | None = None,
    vehicle_benchmark: dict[str, Any] | None = None,
) -> None:
    vehicle_population = (
        vehicle_benchmark["vehicle_class_used"] if vehicle_benchmark else "All vehicle categories"
    )
    for history_row, history_value, normalised_total, weight in pairs:
        adjustments: dict[str, Any] = {
            "settlement_status": history_row.settlement_status.value,
            "comparability_score": str(history_value.comparability_score),
        }
        if vehicle_benchmark:
            adjustments.update(
                {
                    "vehicle_class_used": vehicle_benchmark["vehicle_class_used"],
                    "category_specific": vehicle_benchmark["category_specific"],
                }
            )
        if component_index is not None:
            adjustments.update(
                {
                    "bundle_component_index": component_index,
                    "ontology_item_id": ontology_item_id,
                }
            )
        session.add(
            ComparisonComparable(
                price_comparison_id=comparison.id,
                historical_observation_id=history_row.id,
                comparable_class=(
                    "bundle_component_previous_invoice"
                    if component_index is not None
                    else "previous_repair_service_invoice"
                ),
                weight=weight,
                original_line_net=history_row.line_total_net,
                normalised_line_net=normalised_total,
                adjustments_json=adjustments,
                stale_data_warning=(
                    (
                        comparison.invoice_line_item.invoice.invoice_date
                        - history_value.observed_at
                    ).days
                    > 1095
                ),
                eligibility_reason=(
                    "Same handler-declared bundle component; past invoice only; "
                    f"vehicle population: {vehicle_population}."
                    if component_index is not None
                    else "Same mapped ontology item; past invoice only; "
                    f"vehicle population: {vehicle_population}."
                ),
            )
        )


def _set_single_comparison(
    session: Session,
    *,
    line: InvoiceLineItem,
    item: OntologyItem,
    version: OntologyVersion,
    comparison: PriceComparison,
    challenge: ChallengeResult,
) -> None:
    result, _, pairs, vehicle_benchmark = _component_comparison(
        session,
        line=line,
        item=item,
        version=version,
        allocated_net=_decimal(line.line_total_net),
        quantity=_decimal(line.quantity) if line.quantity is not None else None,
        unit=line.unit,
        component_index=0,
    )
    review_flags = list(result.review_flags)
    requires_review = result.review_required
    comparison.invoice_unit_net = line.unit_price_net
    comparison.invoice_line_net = result.invoice_price_net
    comparison.ontology_unit_net = item.reference_price_net
    comparison.ontology_line_net = result.ontology_expected_net
    comparison.historical_median_unit_net = result.history.weighted_median_unit_net
    comparison.historical_line_net = result.historical_expected_net
    comparison.n_comparables = result.history.eligible_count
    comparison.selected_benchmark_source = result.benchmark_source.value
    comparison.benchmark_line_net = result.selected_benchmark_net
    comparison.benchmark_formula_json = {
        "formula": result.benchmark_formula,
        "ontology_weight": "0.60",
        "historical_weight": "0.40",
        "difference_from_ontology": (
            str(result.difference_from_ontology_net)
            if result.difference_from_ontology_net is not None
            else None
        ),
        "difference_from_history": (
            str(result.difference_from_history_net)
            if result.difference_from_history_net is not None
            else None
        ),
        "reviewed_mapping": True,
        "vehicle_benchmark": vehicle_benchmark,
    }
    comparison.eligibility_flags_json = {
        "review_required": requires_review,
        "flags": review_flags,
        "sources_independent": result.sources_independent,
        "lineage_note": result.source_lineage_note,
        "vehicle_benchmark": vehicle_benchmark,
    }
    comparison.status = ComparisonStatus.REVIEW if requires_review else ComparisonStatus.ACCEPTED
    _persist_comparable_pairs(
        session,
        comparison,
        pairs,
        vehicle_benchmark=vehicle_benchmark,
    )

    challenge.challenge_net = result.challenge_amount_net
    challenge.challenge_vat = result.vat_impact
    challenge.challenge_gross = result.challenge_gross
    challenge.challenge_percentage = result.challenge_percentage
    challenge.evidence_strength_score = _score_int(result.challenge_score)
    challenge.evidence_label = result.challenge_score_label
    challenge.recommended_payable_net = result.challenge_price_net
    evidence_parts = []
    if result.ontology_expected_net is not None:
        evidence_parts.append(f"ontology £{result.ontology_expected_net:.2f}")
    if result.historical_expected_net is not None:
        evidence_parts.append(
            f"historical median £{result.historical_expected_net:.2f} "
            f"from {result.history.eligible_count} comparable claim"
            f"{'' if result.history.eligible_count == 1 else 's'}"
        )
    challenge.narrative = (
        f"{line.raw_description}: billed £{result.invoice_price_net:.2f}; "
        f"{' and '.join(evidence_parts) or 'governed evidence'} supports "
        f"£{result.challenge_price_net:.2f}. Line challenge: "
        f"£{result.challenge_amount_net:.2f}."
    )
    challenge.score_breakdown_json = {
        "mapping_confidence": str(result.mapping_confidence),
        "price_evidence_confidence": str(result.price_evidence_confidence),
        "challenge_strength": str(result.challenge_score),
    }
    challenge.findings_json = {
        "severity": result.severity.value,
        "review_flags": review_flags,
        "line_description": line.raw_description,
        "billed_net": str(result.invoice_price_net),
        "supported_net": str(result.challenge_price_net),
        "challenge_net": str(result.challenge_amount_net),
        "ontology_net": (
            str(result.ontology_expected_net)
            if result.ontology_expected_net is not None
            else None
        ),
        "historical_median_net": (
            str(result.historical_expected_net)
            if result.historical_expected_net is not None
            else None
        ),
        "historical_claim_count": result.history.eligible_count,
    }
    _invalidate_challenge_review(challenge)


def _all_or_none_allocated(components: tuple[BundleComponentDecision, ...]) -> bool:
    allocated = [component.allocated_net is not None for component in components]
    if any(allocated) and not all(allocated):
        raise MappingReviewError(
            "BUNDLE_ALLOCATION_INCOMPLETE",
            "Provide a net allocation for every component, or quantities only for an unresolved bundle.",
        )
    return all(allocated)


def _set_bundle_comparison(
    session: Session,
    *,
    line: InvoiceLineItem,
    version: OntologyVersion,
    comparison: PriceComparison,
    challenge: ChallengeResult,
    components: tuple[BundleComponentDecision, ...],
    items: dict[str, OntologyItem],
) -> tuple[list[dict[str, Any]], bool]:
    line_total = money(_decimal(line.line_total_net)) or ZERO
    allocation_resolved = _all_or_none_allocated(components)
    if allocation_resolved:
        allocation_total = (
            money(sum((money(component.allocated_net) or ZERO for component in components), ZERO))
            or ZERO
        )
        if allocation_total != line_total:
            raise MappingReviewError(
                "BUNDLE_ALLOCATION_MISMATCH",
                "Bundle net allocations must sum exactly to "
                f"the source line net (£{line_total:.2f}); received £{allocation_total:.2f}.",
            )

    component_payloads = [
        {
            "ontology_item_id": component.ontology_item_id,
            "canonical_name": items[component.ontology_item_id].canonical_name,
            "allocated_net": (
                f"{money(component.allocated_net):.2f}"
                if component.allocated_net is not None
                else None
            ),
            "quantity": str(component.quantity) if component.quantity is not None else None,
            "unit": component.unit or items[component.ontology_item_id].unit,
            "unit_source": "handler" if component.unit else "ontology_item",
        }
        for component in components
    ]
    if not allocation_resolved:
        _set_non_comparable(
            comparison,
            challenge,
            invoice_line_net=line_total,
            flags=["BUNDLE_ALLOCATION_REQUIRED", "NON_COMPARABLE"],
            formula="bundle allocation unresolved; handler quantities retained without price guessing",
        )
        return component_payloads, False

    results: list[LineComparison] = []
    all_pairs = []
    for index, component in enumerate(components, start=1):
        item = items[component.ontology_item_id]
        result, _, pairs, vehicle_benchmark = _component_comparison(
            session,
            line=line,
            item=item,
            version=version,
            allocated_net=money(component.allocated_net) or ZERO,
            quantity=component.quantity,
            unit=component.unit or item.unit,
            component_index=index,
        )
        results.append(result)
        all_pairs.append((index, item.id, pairs, vehicle_benchmark))
        component_payloads[index - 1].update(
            {
                "benchmark_source": result.benchmark_source.value,
                "challenge_price_net": f"{result.challenge_price_net:.2f}",
                "challenge_net": f"{result.challenge_amount_net:.2f}",
                "review_required": result.review_required,
                "review_flags": list(result.review_flags),
                "vehicle_benchmark": vehicle_benchmark,
            }
        )

    summary = aggregate_challenges(results)
    flags = list(dict.fromkeys(flag for result in results for flag in result.review_flags))
    requires_review = any(result.review_required for result in results)
    scores = [result.challenge_score for result in results]
    average_score = sum(scores, ZERO) / Decimal(len(scores))
    ontology_totals = [result.ontology_expected_net for result in results]
    history_totals = [result.historical_expected_net for result in results]
    comparison.invoice_unit_net = None
    comparison.invoice_line_net = summary.invoice_price_net
    comparison.ontology_unit_net = None
    comparison.ontology_line_net = (
        sum((value for value in ontology_totals if value is not None), ZERO)
        if all(value is not None for value in ontology_totals)
        else None
    )
    comparison.historical_median_unit_net = None
    comparison.historical_line_net = (
        sum((value for value in history_totals if value is not None), ZERO)
        if all(value is not None for value in history_totals)
        else None
    )
    comparison.n_comparables = sum(result.history.eligible_count for result in results)
    comparison.selected_benchmark_source = "bundle_components"
    comparison.benchmark_unit_net = None
    comparison.benchmark_line_net = summary.challenge_price_net
    comparison.benchmark_formula_json = {
        "formula": "sum of handler-allocated component comparisons",
        "ontology_weight": "0.60",
        "historical_weight": "0.40",
        "bundle_components": component_payloads,
    }
    comparison.eligibility_flags_json = {
        "review_required": requires_review,
        "flags": flags,
        "sources_independent": all(result.sources_independent for result in results),
        "lineage_note": "Each declared component was compared independently; results were summed.",
        "bundle_allocation_resolved": True,
    }
    comparison.status = ComparisonStatus.REVIEW if requires_review else ComparisonStatus.ACCEPTED
    for index, ontology_item_id, pairs, vehicle_benchmark in all_pairs:
        _persist_comparable_pairs(
            session,
            comparison,
            pairs,
            component_index=index,
            ontology_item_id=ontology_item_id,
            vehicle_benchmark=vehicle_benchmark,
        )

    label = "Strong" if average_score >= 80 else "Moderate" if average_score >= 60 else "Weak"
    challenge.challenge_net = summary.challenge_amount_net
    challenge.challenge_vat = summary.vat_impact
    challenge.challenge_gross = summary.challenge_gross
    challenge.challenge_percentage = percentage(
        summary.challenge_amount_net, summary.invoice_price_net
    )
    challenge.evidence_strength_score = _score_int(average_score)
    challenge.evidence_label = label
    challenge.recommended_payable_net = summary.challenge_price_net
    challenge.narrative = (
        f"Challenge Price £{summary.challenge_price_net:.2f}; "
        "handler-declared bundle allocations compared component by component."
    )
    challenge.score_breakdown_json = {
        "challenge_strength": str(average_score),
        "bundle_component_count": len(results),
    }
    challenge.findings_json = {
        "severity_counts": summary.severity_counts,
        "review_flags": flags,
        "bundle_allocation_resolved": True,
    }
    _invalidate_challenge_review(challenge)
    return component_payloads, True


def refresh_invoice_rollup(
    session: Session,
    *,
    line: InvoiceLineItem,
    processing_run_id: str,
) -> ChallengeResult:
    comparisons = list(
        session.scalars(
            select(PriceComparison)
            .join(InvoiceLineItem)
            .where(
                InvoiceLineItem.invoice_id == line.invoice_id,
                PriceComparison.processing_run_id == processing_run_id,
            )
        ).all()
    )
    comparison_ids = [row.id for row in comparisons]
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
    invoice_challenge = session.scalar(
        select(ChallengeResult).where(
            ChallengeResult.processing_run_id == processing_run_id,
            ChallengeResult.invoice_id == line.invoice_id,
        )
    )
    if invoice_challenge is None:
        raise MappingReviewError(
            "INVOICE_SUMMARY_NOT_FOUND",
            "The invoice comparison summary is missing; rerun the comparison pipeline.",
        )

    invoice_net = money(sum((_decimal(row.invoice_line_net) for row in comparisons), ZERO)) or ZERO
    reviewable_challenges = [
        row for row in line_challenges if row.status != ChallengeStatus.REJECTED
    ]
    challenge_net = (
        money(
            sum(
                (max(_decimal(row.challenge_net), ZERO) for row in reviewable_challenges),
                ZERO,
            )
        )
        or ZERO
    )
    vat_impact = (
        money(
            sum(
                (max(_decimal(row.challenge_vat), ZERO) for row in reviewable_challenges),
                ZERO,
            )
        )
        or ZERO
    )
    gross_effect = money(challenge_net + vat_impact) or ZERO
    challenge_price = money(invoice_net - challenge_net) or ZERO
    average_score = (
        Decimal(sum(row.evidence_strength_score for row in reviewable_challenges))
        / Decimal(len(reviewable_challenges))
        if reviewable_challenges
        else ZERO
    )
    label = "Strong" if average_score >= 80 else "Moderate" if average_score >= 60 else "Weak"
    invoice_challenge.challenge_net = challenge_net
    invoice_challenge.challenge_vat = vat_impact
    invoice_challenge.challenge_gross = gross_effect
    invoice_challenge.challenge_percentage = percentage(challenge_net, invoice_net)
    invoice_challenge.evidence_strength_score = _score_int(average_score)
    invoice_challenge.evidence_label = label
    invoice_challenge.recommended_payable_net = challenge_price
    invoice_challenge.narrative = (
        f"Invoice Challenge Price £{challenge_price:.2f} "
        "(proposed payable before any liability apportionment)."
    )
    invoice_challenge.score_breakdown_json = {
        "challenged_line_count": sum(
            _decimal(row.challenge_net) > 0 for row in reviewable_challenges
        ),
        "recomputed_after_mapping_review": True,
    }
    invoice_challenge.findings_json = {"positive_only": True, "mot_vat_exempt": True}
    _invalidate_challenge_review(invoice_challenge)
    return invoice_challenge


def review_line_mapping(
    session: Session,
    *,
    case: Case,
    line_id: str,
    command: MappingReviewCommand,
) -> dict[str, Any]:
    """Apply one handler mapping decision and atomically refresh its financial result."""

    if case.status == CaseStatus.FINALISED:
        raise MappingReviewError(
            "CASE_ALREADY_FINALISED",
            "Mappings cannot change after case finalisation.",
        )
    action = command.decision.strip().lower().replace("_", "-")
    if action not in {"approve", "change", "reject", "bundle"}:
        raise MappingReviewError(
            "INVALID_MAPPING_DECISION",
            "Decision must be approve, change, reject or bundle.",
        )
    if action != "bundle" and command.bundle_components:
        raise MappingReviewError(
            "BUNDLE_COMPONENTS_NOT_ALLOWED",
            "Bundle components are only valid for a bundle decision.",
        )
    if action in {"reject", "bundle"} and command.ontology_item_id:
        raise MappingReviewError(
            "ONTOLOGY_ITEM_NOT_ALLOWED",
            f"An ontology_item_id is not valid for a {action} decision.",
        )
    line = session.scalar(
        select(InvoiceLineItem)
        .join(InvoiceLineItem.invoice)
        .where(InvoiceLineItem.id == line_id, InvoiceLineItem.invoice.has(case_id=case.id))
    )
    if line is None:
        raise MappingReviewError("INVOICE_LINE_NOT_FOUND", "Invoice line not found for this case.")
    if line.status == ReviewStatus.REJECTED:
        raise MappingReviewError(
            "EXTRACTION_LINE_REJECTED",
            "Restore the rejected extraction before reviewing its ontology mapping.",
        )
    if line.line_total_net is None:
        raise MappingReviewError(
            "LINE_NET_REQUIRED",
            "The source line needs a net total before its mapping can be reviewed.",
        )
    mapping = session.scalar(
        select(OntologyMapping)
        .where(OntologyMapping.invoice_line_item_id == line.id)
        .order_by(OntologyMapping.updated_at.desc())
    )
    comparison = session.scalar(
        select(PriceComparison)
        .where(PriceComparison.invoice_line_item_id == line.id)
        .order_by(PriceComparison.updated_at.desc())
    )
    if mapping is None or comparison is None:
        raise MappingReviewError(
            "COMPARISON_NOT_READY",
            "Run ontology mapping and price comparison before recording a mapping decision.",
        )
    challenge = session.scalar(
        select(ChallengeResult).where(ChallengeResult.price_comparison_id == comparison.id)
    )
    if challenge is None:
        raise MappingReviewError(
            "CHALLENGE_RESULT_NOT_FOUND",
            "The line challenge result is missing; rerun the comparison pipeline.",
        )
    version = session.get(OntologyVersion, comparison.ontology_version_id)
    if version is None:
        raise MappingReviewError("ONTOLOGY_VERSION_NOT_FOUND", "Ontology version not found.")

    before = _mapping_snapshot(mapping, comparison, challenge)
    original_description = line.raw_description
    original_line_net = line.line_total_net
    previous_approval = challenge.reviewer_approved
    _clear_comparables(session, comparison)
    now = datetime.now(UTC)
    mapping.reviewed_by = command.actor
    mapping.reviewed_at = now
    mapping.rationale = command.rationale
    flags = dict(mapping.flags_json or {})
    flags.update({"human_review_required": False, "review_action": action})
    mapping.flags_json = flags

    allocation_resolved: bool | None = None
    learned_synonym_id: str | None = None
    if action == "reject":
        mapping.selected_ontology_item_id = None
        mapping.decision = MappingDecision.NO_MATCH
        mapping.final_status = MappingStatus.REJECTED
        mapping.combined_confidence = 1.0
        mapping.is_bundled = False
        mapping.bundle_components_json = None
        _set_non_comparable(
            comparison,
            challenge,
            invoice_line_net=_decimal(line.line_total_net),
            flags=["MAPPING_REJECTED", "NON_COMPARABLE"],
            formula="handler rejected the ontology mapping; no benchmark applied",
        )
    elif action == "bundle":
        if len(command.bundle_components) < 2:
            raise MappingReviewError(
                "BUNDLE_COMPONENTS_REQUIRED",
                "A bundled line needs at least two handler-declared components.",
            )
        item_ids = {component.ontology_item_id for component in command.bundle_components}
        items = {
            item.id: item
            for item in session.scalars(select(OntologyItem).where(OntologyItem.id.in_(item_ids)))
        }
        missing = sorted(item_ids - items.keys())
        if missing:
            raise MappingReviewError(
                "ONTOLOGY_ITEM_NOT_FOUND",
                f"Unknown ontology item(s): {', '.join(missing)}.",
            )
        mapping.selected_ontology_item_id = None
        mapping.decision = MappingDecision.BUNDLED
        mapping.combined_confidence = 1.0
        mapping.is_bundled = True
        component_payloads, allocation_resolved = _set_bundle_comparison(
            session,
            line=line,
            version=version,
            comparison=comparison,
            challenge=challenge,
            components=command.bundle_components,
            items=items,
        )
        mapping.bundle_components_json = component_payloads
        mapping.final_status = (
            MappingStatus.APPROVED if allocation_resolved else MappingStatus.REVIEW
        )
        mapping.flags_json = {
            **flags,
            "bundle_allocation_resolved": allocation_resolved,
            "human_review_required": not allocation_resolved,
        }
    else:
        ontology_item_id = command.ontology_item_id or mapping.selected_ontology_item_id
        if not ontology_item_id:
            raise MappingReviewError(
                "ONTOLOGY_ITEM_REQUIRED",
                "Approve/change needs an ontology item identifier.",
            )
        item = session.get(OntologyItem, ontology_item_id)
        if item is None:
            raise MappingReviewError("ONTOLOGY_ITEM_NOT_FOUND", "Ontology item not found.")
        if not _type_compatible(line.item_kind.value, item.item_type.value):
            raise MappingReviewError(
                "ONTOLOGY_TYPE_MISMATCH",
                "The selected ontology item type is incompatible with the source invoice line.",
            )
        if action == "change" and ontology_item_id == mapping.selected_ontology_item_id:
            raise MappingReviewError(
                "MAPPING_UNCHANGED",
                "Change must select a different ontology item; use approve to confirm this one.",
            )
        mapping.selected_ontology_item_id = item.id
        mapping.decision = MappingDecision.MANUAL
        mapping.final_status = (
            MappingStatus.EDITED if action == "change" else MappingStatus.APPROVED
        )
        mapping.retrieval_similarity = 1.0
        mapping.combined_confidence = 1.0
        mapping.is_bundled = False
        mapping.bundle_components_json = None
        mapping.flags_json = {
            **flags,
            "ontology_approval": item.approval_status.value,
            "manual_mapping_override": action == "change",
        }
        _set_single_comparison(
            session,
            line=line,
            item=item,
            version=version,
            comparison=comparison,
            challenge=challenge,
        )
        learned_synonym_id = _learn_approved_synonym(
            session,
            line=line,
            item=item,
            version=version,
        )

    if line.raw_description != original_description or line.line_total_net != original_line_net:
        raise MappingReviewError(
            "SOURCE_LINE_MUTATED",
            "Mapping review must not alter the original extracted invoice line.",
        )
    invoice_challenge = refresh_invoice_rollup(
        session,
        line=line,
        processing_run_id=comparison.processing_run_id,
    )
    case.status = CaseStatus.COMPARISON_REVIEW
    session.flush()
    after = _mapping_snapshot(mapping, comparison, challenge)
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=comparison.processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=command.actor,
            event_type=f"MAPPING_{action.upper()}",
            entity_type="ontology_mapping",
            entity_id=mapping.id,
            before_json=before,
            after_json=after,
            event_payload_json={
                "rationale": command.rationale,
                "source_line_preserved": True,
                "source_line": {
                    "id": line.id,
                    "description": original_description,
                    "line_total_net": original_line_net,
                },
                "recomputed_scope": "affected_line_and_invoice_rollup",
                "previous_challenge_approval_invalidated": previous_approval,
                "bundle_allocation_resolved": allocation_resolved,
                "learned_synonym_id": learned_synonym_id,
            },
        )
    )
    session.flush()
    return {
        "case_reference": case.case_reference,
        "line_id": line.id,
        "source_description": line.raw_description,
        "source_line_net": line.line_total_net,
        "decision": action,
        "learned_synonym_id": learned_synonym_id,
        "mapping": after["mapping"],
        "comparison": after["comparison"],
        "challenge": after["challenge"],
        "invoice_summary": {
            "challenge_price_net": invoice_challenge.recommended_payable_net,
            "challenge_net": invoice_challenge.challenge_net,
            "vat_impact": invoice_challenge.challenge_vat,
            "gross_effect": invoice_challenge.challenge_gross,
        },
    }


__all__ = [
    "BundleComponentDecision",
    "MappingReviewCommand",
    "MappingReviewError",
    "review_line_mapping",
]
