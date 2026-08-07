from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.comparison import (
    CurrentInvoiceLine,
    OntologyPriceEvidence,
    aggregate_challenges,
    compare_line,
    recency_weight,
    retrieve_candidates,
)
from app.comparison import (
    HistoryObservation as DomainHistoryObservation,
)
from app.comparison import (
    OntologyItem as DomainOntologyItem,
)
from app.config import get_settings
from app.enums import (
    ApprovalStatus,
    CaseStatus,
    ChallengeStatus,
    ComparisonStatus,
    InvoiceDocumentRole,
    MappingDecision,
    MappingStatus,
    OntologyVersionStatus,
    ReviewStatus,
    RunStatus,
)
from app.llm.base import LLMProviderError
from app.llm.mapping import ConstrainedMappingAdjudicator, MappingCandidate
from app.models import (
    Case,
    ChallengeResult,
    ComparisonComparable,
    HistoricalObservation,
    Invoice,
    MappingRun,
    OntologyItem,
    OntologyMapping,
    OntologyVersion,
    PriceComparison,
    ProcessingRun,
)
from app.services.vehicle_classification import select_vehicle_category_history

settings = get_settings()


@dataclass(frozen=True, slots=True)
class MappingOverride:
    """A human-governed mapping that must outrank deterministic retrieval."""

    ontology_item_id: str
    actor_id: str
    rationale: str


def _scope(unit: str | None) -> str:
    value = (unit or "each").strip().lower()
    if value in {"job", "test", "set", "pair"}:
        return "job" if value == "job" else value
    if value in {"hour", "hr", "hrs", "hours"}:
        return "hour"
    if value in {"litre", "litres", "l", "ltr"}:
        return "litre"
    return "each"


def _decimal(value: str | Decimal | None, fallback: str = "0") -> Decimal:
    return Decimal(str(value if value is not None else fallback))


def _mapping_decision(match_kind: str | None) -> MappingDecision:
    if match_kind is None:
        return MappingDecision.NO_MATCH
    if match_kind == "exact_part_number":
        return MappingDecision.EXACT_PART_NUMBER
    if match_kind in {"exact_synonym", "exact_canonical_name"}:
        return MappingDecision.SYNONYM
    return MappingDecision.FUZZY


def _type_compatible(line_kind: str, item_kind: str) -> bool:
    if line_kind == item_kind:
        return True
    # Repair operations are commonly labelled "labour" on an invoice while
    # the governed ontology stores the operation as a service (for example,
    # front wheel alignment). Treat those two operational types as compatible;
    # parts remain strictly separated from both.
    if line_kind == "labour":
        return item_kind in {"labour", "service"}
    if line_kind in {"service", "fee", "disposal"}:
        return item_kind in {"service", "fee", "labour"}
    return False


def _domain_items(items: list[OntologyItem]) -> tuple[DomainOntologyItem, ...]:
    return tuple(
        DomainOntologyItem(
            item_id=item.id,
            canonical_name=item.canonical_name,
            item_type=item.item_type.value,
            unit=item.unit,
            price_scope=_scope(item.unit),
            synonyms=tuple(synonym.synonym for synonym in item.synonyms),
            part_numbers=tuple(number for number in (item.manufacturer_part_number,) if number),
        )
        for item in items
    )


def _history_domain(
    observations: list[HistoricalObservation],
) -> tuple[DomainHistoryObservation, ...]:
    result: list[DomainHistoryObservation] = []
    for observation in observations:
        if observation.invoice_date is None:
            continue
        price = (
            observation.settled_amount_net
            or observation.approved_amount_net
            or observation.line_total_net
        )
        metadata = observation.comparability_metadata_json or {}
        result.append(
            DomainHistoryObservation(
                observation_id=observation.id,
                invoice_id=observation.source_invoice_id
                or observation.source_record_id
                or observation.id,
                observed_at=observation.invoice_date,
                document_type=observation.observation_type.value,
                net_line_total=_decimal(price) if price is not None else None,
                net_unit_price=(
                    _decimal(observation.unit_price_net)
                    if observation.unit_price_net is not None
                    else None
                ),
                quantity=(
                    _decimal(observation.quantity) if observation.quantity is not None else None
                ),
                unit=observation.unit,
                eligible=True,
                unit_compatible=metadata.get("unit_compatible", True),
                quantity_scope_equivalent=metadata.get("quantity_scope_equivalent", True),
                comparability_score=_decimal(metadata.get("comparability_score", "1")),
                source_lineage_id=(
                    "historical-seed-derived"
                    if observation.source_record_id
                    else observation.source_import_id
                ),
            )
        )
    return tuple(result)


def _eligible_history_pairs(
    rows: list[HistoricalObservation],
    observations: tuple[DomainHistoryObservation, ...],
    *,
    as_of_date: date,
) -> tuple[tuple[HistoricalObservation, DomainHistoryObservation, Decimal, Decimal], ...]:
    """Return the exact persisted rows eligible for the historical calculation."""

    row_by_id = {row.id: row for row in rows}
    eligible = []
    for observation in observations:
        row = row_by_id[observation.observation_id]
        document_type = observation.document_type.strip().lower()
        if "invoice" not in document_type or observation.observed_at >= as_of_date:
            continue
        if not observation.eligible or not observation.unit_compatible:
            continue
        if not observation.quantity_scope_equivalent:
            continue
        comparability = min(
            max(_decimal(observation.comparability_score), Decimal("0")),
            Decimal("1"),
        )
        if comparability == 0:
            continue
        line_total = (
            _decimal(observation.net_line_total) if observation.net_line_total is not None else None
        )
        if (
            line_total is None
            and observation.net_unit_price is not None
            and observation.quantity is not None
            and observation.quantity > 0
        ):
            line_total = _decimal(observation.net_unit_price) * observation.quantity
        if line_total is None or line_total <= 0:
            continue
        age_days = (as_of_date - observation.observed_at).days
        weight = (
            recency_weight(
                age_days=age_days,
                half_life_days=Decimal("365.25"),
            )
            * comparability
        )
        eligible.append((row, observation, line_total, weight))
    return tuple(eligible)


def _ontology_evidence(
    item: OntologyItem | None,
    version: OntologyVersion,
) -> OntologyPriceEvidence | None:
    if item is None or item.reference_price_net is None:
        return None
    approved = item.approval_status == ApprovalStatus.APPROVED
    return OntologyPriceEvidence(
        item_id=item.id,
        amount_net=_decimal(item.reference_price_net),
        price_scope=_scope(item.unit),
        unit=item.unit,
        approved=approved,
        reliable=item.reference_price_net is not None,
        confidence=Decimal("0.90") if approved else Decimal("0.65"),
        source_lineage_id=(
            "historical-seed-derived"
            if item.price_source and "historical" in item.price_source.lower()
            else version.source_import_id or version.id
        ),
        observed_at=item.effective_date,
    )


def _score_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _challenge_explanation(*, line: CurrentInvoiceLine, comparison: Any) -> str:
    evidence: list[str] = []
    if comparison.ontology_expected_net is not None:
        difference = comparison.difference_from_ontology_net or Decimal("0")
        evidence.append(
            f"approved ontology £{comparison.ontology_expected_net:.2f} "
            f"(billed £{difference:.2f} higher)"
        )
    if comparison.historical_expected_net is not None:
        difference = comparison.difference_from_history_net or Decimal("0")
        evidence.append(
            f"historical median £{comparison.historical_expected_net:.2f} "
            f"from {comparison.history.eligible_count} comparable claim"
            f"{'' if comparison.history.eligible_count == 1 else 's'} "
            f"(billed £{difference:.2f} higher)"
        )
    evidence_text = " and ".join(evidence) or "the available governed evidence"
    return (
        f"{line.description}: billed £{comparison.invoice_price_net:.2f}; "
        f"{evidence_text}. The supported net price is "
        f"£{comparison.challenge_price_net:.2f}, producing a "
        f"£{comparison.challenge_amount_net:.2f} challenge."
    )


def run_case_comparison(
    session: Session,
    case: Case,
    *,
    mapping_overrides: Mapping[str, MappingOverride] | None = None,
    llm_adjudicator: ConstrainedMappingAdjudicator | None = None,
) -> dict[str, Any]:
    """Map and compare current invoice lines with deterministic pilot policy."""

    overrides = mapping_overrides or {}
    processing_run = session.get(ProcessingRun, case.current_processing_run_id)
    if processing_run is None or processing_run.status != RunStatus.SUCCEEDED:
        raise ValueError("The case has no completed extraction run.")
    existing = session.scalars(
        select(PriceComparison).where(PriceComparison.processing_run_id == processing_run.id)
    ).all()
    if existing:
        return {
            "processing_run_id": processing_run.id,
            "status": "already_compared",
            "line_count": len(existing),
        }

    version = (
        session.get(OntologyVersion, processing_run.ontology_version_id)
        if processing_run.ontology_version_id
        else session.scalar(
            select(OntologyVersion)
            .where(OntologyVersion.status == OntologyVersionStatus.PUBLISHED)
            .order_by(OntologyVersion.sequence_number.desc())
        )
    )
    if version is None:
        raise ValueError("No ontology version exists.")
    if version.status != OntologyVersionStatus.PUBLISHED:
        raise ValueError("The processing run references an unpublished ontology version.")
    ontology_items = (
        session.scalars(
            select(OntologyItem)
            .options(selectinload(OntologyItem.synonyms))
            .order_by(OntologyItem.canonical_code)
        )
        .unique()
        .all()
    )
    domain_items = _domain_items(list(ontology_items))
    item_by_id = {item.id: item for item in ontology_items}

    mapping_run = MappingRun(
        processing_run_id=processing_run.id,
        ontology_version_id=version.id,
        model_provider=(llm_adjudicator.client.provider if llm_adjudicator else None),
        model_name=(llm_adjudicator.client.model_id if llm_adjudicator else None),
        prompt_version=(
            "constrained-mapping-v1" if llm_adjudicator else "deterministic-retrieval-v1"
        ),
        status=RunStatus.RUNNING,
    )
    session.add(mapping_run)
    session.flush()

    invoices = (
        session.scalars(
            select(Invoice)
            .where(
                Invoice.case_id == case.id,
                Invoice.document_role == InvoiceDocumentRole.INVOICE,
            )
            .options(selectinload(Invoice.line_items))
        )
        .unique()
        .all()
    )
    line_count = 0
    mapped_count = 0
    challenge_count = 0
    invoice_summaries: list[dict[str, Any]] = []
    active_llm_adjudicator = llm_adjudicator
    llm_failure_code: str | None = None

    for invoice in invoices:
        line_comparisons = []
        for line in invoice.line_items:
            if line.status == ReviewStatus.REJECTED:
                continue
            if line.line_total_net is None or invoice.invoice_date is None:
                continue
            line_count += 1
            retrieved_candidates = retrieve_candidates(
                description=line.raw_description,
                ontology_items=domain_items,
                part_number=line.part_number,
            )
            candidates = tuple(
                candidate
                for candidate in retrieved_candidates
                if _type_compatible(
                    line.item_kind.value,
                    item_by_id[candidate.item_id].item_type.value,
                )
            )
            override = overrides.get(line.id)
            llm_decision = None
            if active_llm_adjudicator and candidates and override is None:
                try:
                    llm_decision = active_llm_adjudicator.adjudicate(
                        invoice_description=line.raw_description,
                        candidates=[
                            MappingCandidate(
                                ontology_id=candidate.item_id,
                                canonical_name=candidate.canonical_name,
                            )
                            for candidate in candidates
                        ],
                    )
                except LLMProviderError as exc:
                    # A cloud outage or free-tier limit must not block invoice review.
                    # Disable further calls for this run and record the safe failure code.
                    llm_failure_code = exc.code
                    active_llm_adjudicator = None
            selected_candidate = (
                next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.item_id == llm_decision.selected_ontology_id
                    ),
                    None,
                )
                if llm_decision
                else candidates[0]
                if candidates and override is None
                else None
            )
            selected_item = (
                item_by_id.get(override.ontology_item_id)
                if override is not None
                else item_by_id.get(selected_candidate.item_id)
                if selected_candidate
                else None
            )
            if override is not None and selected_item is None:
                raise ValueError(
                    f"Mapping override references unknown ontology item {override.ontology_item_id}."
                )
            if override is not None and not _type_compatible(
                line.item_kind.value, selected_item.item_type.value
            ):
                raise ValueError(
                    "Mapping override item type is incompatible with the source invoice line."
                )
            if selected_item is not None:
                mapped_count += 1
            mapping_confidence = (
                Decimal("1")
                if override is not None
                else min(
                    selected_candidate.mapping_confidence,
                    Decimal(str(llm_decision.confidence)),
                )
                if selected_candidate and llm_decision
                else selected_candidate.mapping_confidence
                if selected_candidate
                else Decimal("0")
            )
            approved_mapping = bool(
                selected_item
                and (
                    override is not None
                    or mapping_confidence
                    > Decimal(str(settings.auto_accept_confidence_threshold))
                )
            )
            mapping = OntologyMapping(
                mapping_run_id=mapping_run.id,
                invoice_line_item_id=line.id,
                selected_ontology_item_id=selected_item.id if selected_item else None,
                decision=(
                    MappingDecision.MANUAL
                    if override is not None
                    else _mapping_decision(
                        selected_candidate.match_kind.value if selected_candidate else None
                    )
                ),
                retrieval_similarity=(
                    1.0
                    if override is not None
                    else float(selected_candidate.mapping_confidence)
                    if selected_candidate
                    else None
                ),
                llm_confidence=llm_decision.confidence if llm_decision else None,
                combined_confidence=(
                    1.0
                    if override is not None
                    else min(
                        float(selected_candidate.mapping_confidence),
                        llm_decision.confidence,
                    )
                    if selected_candidate and llm_decision
                    else float(selected_candidate.mapping_confidence)
                    if selected_candidate
                    else None
                ),
                rationale=(
                    override.rationale
                    if override is not None
                    else (
                        f"Constrained model decision: {llm_decision.rationale}"
                        if llm_decision
                        else f"Deterministic {selected_candidate.match_kind.value} candidate; "
                        "financial comparability is evaluated separately."
                        if selected_candidate
                        else (
                            "Retrieved ontology candidates failed the line-type check."
                            if retrieved_candidates
                            else "No ontology candidate met the retrieval threshold."
                        )
                    )
                ),
                alternative_candidates_json=[
                    {
                        "ontology_item_id": candidate.item_id,
                        "canonical_name": candidate.canonical_name,
                        "match_kind": candidate.match_kind.value,
                        "confidence": str(candidate.mapping_confidence),
                    }
                    for candidate in (
                        tuple(
                            candidate
                            for candidate in candidates
                            if selected_item is None or candidate.item_id != selected_item.id
                        )
                        if override is not None
                        else candidates[1:]
                        if selected_candidate
                        else retrieved_candidates
                    )
                ],
                flags_json={
                    "ontology_approval": (
                        selected_item.approval_status.value if selected_item else None
                    ),
                    "human_review_required": not approved_mapping,
                    "type_mismatch": bool(retrieved_candidates and not candidates),
                    "manual_research_override": override is not None,
                    "ai_provider_fallback": llm_failure_code,
                },
                ai_output_json=llm_decision.model_dump() if llm_decision else None,
                is_bundled=False,
                final_status=(
                    MappingStatus.APPROVED
                    if override is not None and approved_mapping
                    else MappingStatus.AUTO_ACCEPTED
                    if approved_mapping
                    else MappingStatus.REVIEW
                ),
                reviewed_by=override.actor_id if override is not None else None,
                reviewed_at=datetime.now(UTC) if override is not None else None,
            )
            session.add(mapping)
            session.flush()

            history_rows = (
                session.scalars(
                    select(HistoricalObservation)
                    .where(HistoricalObservation.ontology_item_id == selected_item.id)
                    .order_by(HistoricalObservation.invoice_date)
                ).all()
                if selected_item
                else []
            )
            history_rows, vehicle_benchmark = select_vehicle_category_history(
                list(history_rows),
                current_vehicle=invoice.vehicle,
                session=session,
            )
            history_domain = _history_domain(history_rows)
            current = CurrentInvoiceLine(
                line_id=line.id,
                description=line.raw_description,
                invoice_line_net=_decimal(line.line_total_net),
                invoice_date=invoice.invoice_date,
                quantity=_decimal(line.quantity) if line.quantity is not None else None,
                unit=line.unit,
                part_number=line.part_number,
                vat_rate=_decimal(line.vat_rate, "20"),
                vat_applicable=bool(line.vat_applicable),
                is_mot="mot" in line.raw_description.lower(),
            )
            evidence = _ontology_evidence(selected_item, version)
            comparison = compare_line(
                line=current,
                ontology=evidence,
                history_observations=history_domain,
                mapping_confidence=mapping_confidence,
                price_evidence_confidence=(evidence.confidence if evidence else Decimal("0.55")),
            )
            requires_human_review = comparison.review_required or not approved_mapping
            review_flags = list(comparison.review_flags)
            if not approved_mapping:
                review_flags.append("MAPPING_REVIEW_REQUIRED")
            line_comparisons.append(comparison)
            if comparison.challenge_amount_net > 0:
                challenge_count += 1

            comparison_row = PriceComparison(
                processing_run_id=processing_run.id,
                invoice_line_item_id=line.id,
                ontology_mapping_id=mapping.id,
                invoice_unit_net=line.unit_price_net,
                invoice_line_net=comparison.invoice_price_net,
                ontology_unit_net=(selected_item.reference_price_net if selected_item else None),
                ontology_line_net=comparison.ontology_expected_net,
                historical_median_unit_net=comparison.history.weighted_median_unit_net,
                historical_line_net=comparison.historical_expected_net,
                n_comparables=comparison.history.eligible_count,
                selected_benchmark_source=comparison.benchmark_source.value,
                benchmark_line_net=comparison.selected_benchmark_net,
                benchmark_policy_version=comparison.policy_version,
                ontology_version_id=version.id,
                benchmark_formula_json={
                    "formula": comparison.benchmark_formula,
                    "ontology_weight": "0.60",
                    "historical_weight": "0.40",
                    "difference_from_ontology": (
                        str(comparison.difference_from_ontology_net)
                        if comparison.difference_from_ontology_net is not None
                        else None
                    ),
                    "difference_from_history": (
                        str(comparison.difference_from_history_net)
                        if comparison.difference_from_history_net is not None
                        else None
                    ),
                    "vehicle_benchmark": vehicle_benchmark,
                },
                eligibility_flags_json={
                    "review_required": requires_human_review,
                    "flags": list(dict.fromkeys(review_flags)),
                    "sources_independent": comparison.sources_independent,
                    "lineage_note": comparison.source_lineage_note,
                    "vehicle_benchmark": vehicle_benchmark,
                },
                status=(
                    ComparisonStatus.REVIEW if requires_human_review else ComparisonStatus.ACCEPTED
                ),
            )
            session.add(comparison_row)
            session.flush()

            eligible_history = _eligible_history_pairs(
                history_rows,
                history_domain,
                as_of_date=current.invoice_date,
            )
            if len(eligible_history) != comparison.history.eligible_count:
                raise ValueError("Persisted historical comparables disagree with the calculation.")
            for history_row, history_value, normalised_total, weight in eligible_history:
                session.add(
                    ComparisonComparable(
                        price_comparison_id=comparison_row.id,
                        historical_observation_id=history_row.id,
                        comparable_class="previous_repair_service_invoice",
                        weight=weight,
                        original_line_net=history_row.line_total_net,
                        normalised_line_net=normalised_total,
                        adjustments_json={
                            "settlement_status": history_row.settlement_status.value,
                            "comparability_score": str(history_value.comparability_score),
                            "vehicle_class_used": vehicle_benchmark["vehicle_class_used"],
                            "category_specific": vehicle_benchmark["category_specific"],
                        },
                        stale_data_warning=(
                            (current.invoice_date - history_value.observed_at).days > 1095
                        ),
                        eligibility_reason=(
                            "Same mapped ontology item; past invoice only; "
                            f"vehicle population: {vehicle_benchmark['vehicle_class_used']}."
                        ),
                    )
                )

            session.add(
                ChallengeResult(
                    processing_run_id=processing_run.id,
                    price_comparison_id=comparison_row.id,
                    invoice_id=None,
                    challenge_net=comparison.challenge_amount_net,
                    challenge_vat=comparison.vat_impact,
                    challenge_gross=comparison.challenge_gross,
                    challenge_percentage=comparison.challenge_percentage,
                    evidence_strength_score=_score_int(comparison.challenge_score),
                    evidence_label=comparison.challenge_score_label,
                    recommended_payable_net=comparison.challenge_price_net,
                    narrative=_challenge_explanation(line=current, comparison=comparison),
                    score_breakdown_json={
                        "mapping_confidence": str(comparison.mapping_confidence),
                        "price_evidence_confidence": str(comparison.price_evidence_confidence),
                        "challenge_strength": str(comparison.challenge_score),
                    },
                    findings_json={
                        "severity": comparison.severity.value,
                        "review_flags": list(dict.fromkeys(review_flags)),
                        "line_description": line.raw_description,
                        "billed_net": str(comparison.invoice_price_net),
                        "supported_net": str(comparison.challenge_price_net),
                        "challenge_net": str(comparison.challenge_amount_net),
                        "ontology_net": (
                            str(comparison.ontology_expected_net)
                            if comparison.ontology_expected_net is not None
                            else None
                        ),
                        "historical_median_net": (
                            str(comparison.historical_expected_net)
                            if comparison.historical_expected_net is not None
                            else None
                        ),
                        "historical_claim_count": comparison.history.eligible_count,
                    },
                    status=(
                        ChallengeStatus.REVIEW if requires_human_review else ChallengeStatus.DRAFT
                    ),
                    reviewer_approved=False,
                )
            )

        if line_comparisons:
            summary = aggregate_challenges(line_comparisons)
            average_score = sum(
                (row.challenge_score for row in line_comparisons), Decimal("0")
            ) / Decimal(len(line_comparisons))
            label = (
                "Strong" if average_score >= 80 else "Moderate" if average_score >= 60 else "Weak"
            )
            percentage = (
                summary.challenge_amount_net / summary.invoice_price_net * Decimal("100")
                if summary.invoice_price_net > 0
                else Decimal("0")
            )
            session.add(
                ChallengeResult(
                    processing_run_id=processing_run.id,
                    price_comparison_id=None,
                    invoice_id=invoice.id,
                    challenge_net=summary.challenge_amount_net,
                    challenge_vat=summary.vat_impact,
                    challenge_gross=summary.challenge_gross,
                    challenge_percentage=percentage,
                    evidence_strength_score=_score_int(average_score),
                    evidence_label=label,
                    recommended_payable_net=summary.challenge_price_net,
                    narrative=(
                        f"Invoice Challenge Price £{summary.challenge_price_net:.2f} "
                        "(proposed payable before any liability apportionment)."
                    ),
                    score_breakdown_json={
                        "challenged_line_count": summary.challenged_line_count,
                        "severity_counts": summary.severity_counts,
                    },
                    findings_json={"positive_only": True, "mot_vat_exempt": True},
                    status=ChallengeStatus.REVIEW,
                    reviewer_approved=False,
                )
            )
            invoice_summaries.append(
                {
                    "invoice_id": invoice.id,
                    "invoice_price_net": str(summary.invoice_price_net),
                    "challenge_price_net": str(summary.challenge_price_net),
                    "challenge_amount_net": str(summary.challenge_amount_net),
                    "vat_impact": str(summary.vat_impact),
                    "gross_effect": str(summary.challenge_gross),
                    "challenged_lines": summary.challenged_line_count,
                }
            )

    mapping_run.status = RunStatus.SUCCEEDED
    mapping_run.completed_at = datetime.now(UTC)
    case.status = CaseStatus.COMPARISON_REVIEW
    session.flush()
    return {
        "processing_run_id": processing_run.id,
        "mapping_run_id": mapping_run.id,
        "status": "succeeded",
        "line_count": line_count,
        "mapped_count": mapped_count,
        "challenged_line_count": challenge_count,
        "mapping_override_count": len(overrides),
        "ai_status": (
            "fallback_deterministic"
            if llm_failure_code
            else "used"
            if llm_adjudicator
            else "not_configured"
        ),
        "ai_failure_code": llm_failure_code,
        "invoice_summaries": invoice_summaries,
    }
