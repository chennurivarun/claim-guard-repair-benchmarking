"""Two benchmark sources, vehicle category, benchmark analysis and challenges.

Implements ``BUILD_SPEC_2026-09-18_benchmarks-and-challenges.md``.

**Population of a source** (``third_party`` = ``historical_claim`` uploads,
``aviva_dlg`` = ``in_house`` uploads).  Only that source's uploaded invoices:
each invoice's own priced lines -- never a rolled-up section total -- plus the
paired engineer assessment's rows behind a rolled-up total, and only when that
section total agrees with the assessment's (the 15 Sep rule, read off
``section_breakdown_for_invoice``'s ``matches``).  No synthetic rows, no seed
workbook rows: nothing here reads ``historical_observations``.

**Repair item identity.**  An invoice line takes the identity
``case_result._uploaded_line_identity`` already gives it everywhere uploaded
lines are benchmarked: the approved ontology item's canonical name when the
line is mapped, otherwise its normalised description
(``canonical_benchmark_category``).  An assessment row carries no ontology
mapping, so it is always the normalised description -- the same space, so a
"L/R DOOR" printed on an invoice and on an assessment meet.  The key is that
name slugged; rows are grouped by (vehicle category, repair item key, price
kind), where price kind keeps a part's price apart from the labour to fit it
(parts / labour incl. paintwork / paint materials / extras and charges).

**Vehicle category** comes from ``app.services.vehicle_category`` (lookup ->
AI, cached -> Unknown).  Only invoices in a category feed that category's P90;
one observation is a valid P90 and ``n`` is always shown beside it.

**Challenge rule** uses the 50/50 average of both source P90s. Both sources
are required. The percentage and minimum thresholds are read from the
frozen ``price_decision.DEFAULT_POLICY``: a benchmark is violated when the
line exceeds the combined price by more than the threshold *and* by at least the minimum
challenge amount.  High = both source P90s violated, Medium = one, provided the blended rule
also qualifies; Low = above a source P90 without an actionable blended challenge.  ``price_decision.py`` itself is not used or changed: this is
a separate analysis, and the 50/30/20 blend is not involved.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.domain.normalisation import normalise_description
from app.domain.price_decision import DEFAULT_POLICY
from app.enums import AuditActorType, DocumentKind, InvoiceDocumentRole, LineItemKind, ReviewStatus
from app.llm import benchmark_writing
from app.models import (
    AssessmentOperation,
    AuditEvent,
    Case,
    EngineerAssessment,
    Invoice,
    OntologyItem,
    OntologyMapping,
)
from app.services.benchmarking import calculate_benchmark_statistics, canonical_benchmark_category
from app.services.case_result import (
    _assessment_section_verdicts,
    _is_assessment_total_lookalike,
    _latest_by,
    _uploaded_line_identity,
)
from app.services.engineer_assessment import section_breakdown_for_invoice
from app.services.vehicle_category import VehicleCategory, VehicleCategoryResolver

CENT = Decimal("0.01")
HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class BenchmarkSource:
    key: str
    intake_group: str
    label: str
    #: How the source is named inside a sentence.
    phrase: str


SOURCES: dict[str, BenchmarkSource] = {
    "third_party": BenchmarkSource(
        "third_party", "historical_claim", "Insurer Third Party invoices", "third-party"
    ),
    "aviva_dlg": BenchmarkSource("aviva_dlg", "in_house", "EXL/ In house Benchmark invoices", "In-house"),
}
LIVE_GROUP = "live"
ORIGIN_INVOICE = "invoice"
ORIGIN_ASSESSMENT = "engineer_assessment"

#: The price kind a section code belongs to; anything else is an extra/charge.
_PRICE_KIND = {
    "parts": "parts",
    "labour": "labour",
    "paint": "labour",
    "paint_materials": "paint_materials",
}
_KIND_BY_ITEM_KIND = {
    LineItemKind.PART.value: "parts",
    LineItemKind.LABOUR.value: "labour",
    LineItemKind.PAINT.value: "labour",
}


class BenchmarkAnalysisError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else f"{_money(value):.2f}"


def _gbp(value: Decimal | str) -> str:
    return f"£{_money(Decimal(str(value))):,.2f}"


def _amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


# ---------------------------------------------------------------------------
# D3: one line against one benchmark, then against both
# ---------------------------------------------------------------------------


def compare_to_benchmark(
    amount: Decimal | None,
    p90: Decimal | None,
    observations: int,
    *,
    threshold_pct: Decimal,
    minimum: Decimal = DEFAULT_POLICY.minimum_challenge_amount,
) -> dict[str, Any]:
    """One line against one source's P90 for its category and repair item.

    A repair item with no observations in the source is *unavailable*: not a
    zero P90, and never violated.  Comparisons use exact values; only the
    displayed figures are rounded.
    """

    if observations <= 0 or p90 is None:
        return {
            "available": False,
            "p90": None,
            "observations": 0,
            "above_p90": False,
            "violated": False,
            "difference": None,
            "difference_pct": None,
        }
    if amount is None:
        return {
            "available": True,
            "p90": _text(p90),
            "observations": observations,
            "above_p90": False,
            "violated": False,
            "difference": None,
            "difference_pct": None,
        }
    difference = amount - p90
    percentage = (difference / p90 * HUNDRED) if p90 > 0 else None
    above = difference > 0
    violated = (
        above
        and percentage is not None
        and percentage > threshold_pct
        and difference >= minimum
    )
    return {
        "available": True,
        "p90": _text(p90),
        "observations": observations,
        "above_p90": above,
        "violated": bool(violated),
        "difference": _text(difference),
        "difference_pct": _text(percentage),
    }


def _source_phrase(key: str) -> str:
    source = SOURCES.get(key)
    return source.phrase if source else key


def _cited(key: str, comparison: dict[str, Any]) -> str:
    return (
        f"the {_source_phrase(key)} P90 ({_gbp(comparison['p90'])}, "
        f"n={comparison['observations']})"
    )


def challenge_for_line(
    amount: Decimal | None,
    comparisons: dict[str, dict[str, Any]],
    *,
    threshold_pct: Decimal,
    minimum: Decimal = DEFAULT_POLICY.minimum_challenge_amount,
) -> dict[str, Any]:
    """Challenge at an equal blend of the two independent source P90s.

    Both sources are required. Apply the existing percentage/minimum rule to
    the rounded blended price; never propose an increase to the billed price.
    Individual source violations still determine High versus Medium.
    """
    result = {
        "is_challenge": False, "level": None, "justified_amount": None,
        "challenge_amount": "0.00", "reason": "",
    }
    required = ("third_party", "aviva_dlg")
    missing = [key for key in required if not comparisons.get(key, {}).get("available")
               or comparisons[key].get("p90") is None]
    if missing:
        result["reason"] = (
            "Waiting for both benchmarks: no observations for this repair item in "
            + " and ".join(_source_phrase(key) for key in missing)
            + ". A 50/50 challenge price requires both source P90s."
        )
        return result
    if amount is None:
        result["reason"] = "The line carries no amount to compare."
        return result

    justified = _money(sum((Decimal(comparisons[key]["p90"]) for key in required),
                          Decimal("0")) / Decimal("2"))
    combined = compare_to_benchmark(amount, justified, 1,
                                    threshold_pct=threshold_pct, minimum=minimum)
    citation = " and ".join(_cited(key, comparisons[key]) for key in required)
    basis = f"50/50 average of {citation} = {_gbp(justified)}. "
    if combined["violated"]:
        violated = [key for key in required if comparisons[key]["violated"]]
        challenge = _money(amount - justified)
        return {
            "is_challenge": True,
            "level": "high" if len(violated) == 2 else "medium",
            "justified_amount": _text(justified),
            "challenge_amount": _text(challenge),
            "reason": basis + (
                f"The invoiced {_gbp(amount)} exceeds this combined price by "
                f"{combined['difference_pct']}%, beyond the {threshold_pct.normalize():f}% "
                f"threshold and the {_gbp(minimum)} minimum. Challenge {_gbp(challenge)}."
            ),
        }
    above = any(comparisons[key]["above_p90"] for key in required)
    result["level"] = "low" if above else None
    result["reason"] = basis + (
        f"Within the {threshold_pct.normalize():f}% threshold or under the {_gbp(minimum)} "
        "minimum against the combined price; not challenged."
        if amount > justified else "At or below the combined price; not challenged."
    )
    return result


# ---------------------------------------------------------------------------
# Loading and the rows each invoice contributes
# ---------------------------------------------------------------------------


@dataclass
class _CaseData:
    case: Case
    invoices: list[Invoice]
    assessment_by_invoice: dict[str, EngineerAssessment]
    latest_mappings: dict[str, OntologyMapping]
    ontology: dict[str, OntologyItem]
    resolver: VehicleCategoryResolver
    breakdowns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _intake_group(invoice: Invoice) -> str | None:
    return ((invoice.document.metadata_json if invoice.document else None) or {}).get(
        "intake_group"
    )


def _is_uploaded_invoice(invoice: Invoice) -> bool:
    return (
        _enum_value(invoice.document_role) == InvoiceDocumentRole.INVOICE.value
        and invoice.document is not None
        and _enum_value(invoice.document.document_kind) != DocumentKind.ENGINEER_ASSESSMENT.value
    )


def _load(session: Session, case: Case) -> _CaseData:
    invoices = list(
        session.scalars(
            select(Invoice)
            .where(Invoice.case_id == case.id)
            .options(
                selectinload(Invoice.vehicle),
                selectinload(Invoice.document),
                selectinload(Invoice.line_items),
            )
            .order_by(Invoice.created_at, Invoice.id)
        )
        .unique()
        .all()
    )
    assessments = list(
        session.scalars(
            select(EngineerAssessment)
            .where(EngineerAssessment.case_id == case.id)
            .options(
                selectinload(EngineerAssessment.operations),
                selectinload(EngineerAssessment.document),
            )
            .order_by(EngineerAssessment.created_at, EngineerAssessment.id)
        ).all()
    )
    assessment_by_invoice: dict[str, EngineerAssessment] = {}
    for assessment in assessments:
        if assessment.paired_invoice_id:
            # First in load order wins, as in the extracts endpoint.
            assessment_by_invoice.setdefault(assessment.paired_invoice_id, assessment)
    line_ids = [line.id for invoice in invoices for line in invoice.line_items]
    mappings = (
        list(
            session.scalars(
                select(OntologyMapping).where(OntologyMapping.invoice_line_item_id.in_(line_ids))
            ).all()
        )
        if line_ids
        else []
    )
    latest_mappings = _latest_by(mappings, "invoice_line_item_id")
    ontology_ids = {
        mapping.selected_ontology_item_id
        for mapping in latest_mappings.values()
        if mapping.selected_ontology_item_id
    }
    ontology = (
        {
            item.id: item
            for item in session.scalars(
                select(OntologyItem).where(OntologyItem.id.in_(ontology_ids))
            ).all()
        }
        if ontology_ids
        else {}
    )
    return _CaseData(
        case=case,
        invoices=invoices,
        assessment_by_invoice=assessment_by_invoice,
        latest_mappings=latest_mappings,
        ontology=ontology,
        resolver=VehicleCategoryResolver(session),
    )


def _vehicle_category(data: _CaseData, invoice: Invoice) -> VehicleCategory:
    vehicle = invoice.vehicle
    return data.resolver(
        vehicle.make if vehicle else None,
        vehicle.model if vehicle else None,
    )


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "unlabelled"


def _display(label: str, mapped: bool) -> str:
    return label if mapped else label[:1].upper() + label[1:]


def _price_kind(line_item_type: str | None, item_kind: str | None = None) -> str:
    if line_item_type in _PRICE_KIND:
        return _PRICE_KIND[line_item_type]
    if line_item_type in (None, "", "unknown") and item_kind in _KIND_BY_ITEM_KIND:
        return _KIND_BY_ITEM_KIND[item_kind]
    return "extras"


@dataclass(frozen=True)
class _Row:
    """One priced line an invoice contributes: its own, or its assessment's."""

    origin: str
    line_id: str
    description: str
    line_item_type: str
    kind: str
    amount: Decimal | None
    repair_item: str
    repair_item_key: str
    assessment: EngineerAssessment | None = None


def _breakdowns(session: Session, data: _CaseData, invoice: Invoice) -> list[dict[str, Any]]:
    if invoice.id not in data.breakdowns:
        data.breakdowns[invoice.id] = section_breakdown_for_invoice(
            session, invoice, data.assessment_by_invoice.get(invoice.id)
        )
    return data.breakdowns[invoice.id]


def _invoice_rows(session: Session, data: _CaseData, invoice: Invoice) -> list[_Row]:
    """Invoice lines first, then the admitted assessment rows behind totals."""

    rows: list[_Row] = []
    for line in sorted(invoice.line_items, key=lambda item: item.sequence_no):
        if line.is_section_total or line.status == ReviewStatus.REJECTED:
            # "You cannot compare invoices on totals anywhere."
            continue
        mapping = data.latest_mappings.get(line.id)
        _, label, _ = _uploaded_line_identity(
            line, latest_mappings=data.latest_mappings, ontology=data.ontology
        )
        mapped = bool(mapping and mapping.selected_ontology_item_id in data.ontology)
        line_item_type = line.line_item_type or "unknown"
        rows.append(
            _Row(
                origin=ORIGIN_INVOICE,
                line_id=line.id,
                description=line.raw_description,
                line_item_type=line_item_type,
                kind=_price_kind(line.line_item_type, _enum_value(line.item_kind)),
                amount=_amount(line.line_total_net),
                repair_item=_display(label, mapped),
                repair_item_key=_slug(label),
            )
        )

    assessment = data.assessment_by_invoice.get(invoice.id)
    if assessment is None:
        return rows
    operations = {operation.id: operation for operation in assessment.operations}
    # A matched "Total Labour" covers paintwork too, but not when the
    # invoice's own paint & materials total contradicts the assessment's --
    # the same withdrawal the prior-assessment benchmark applies.
    paint_disagrees = (
        _assessment_section_verdicts(invoice, assessment).get("paint_materials") is False
    )
    seen: set[str] = set()
    for breakdown in _breakdowns(session, data, invoice):
        if breakdown["matches"] is not True:
            continue
        for row in breakdown["rows"]:
            operation: AssessmentOperation | None = operations.get(row["id"])
            if operation is None or operation.id in seen:
                continue
            if operation.category == "paint" and paint_disagrees:
                continue
            amount = _amount(operation.total_net)
            if amount is None:
                continue
            if _is_assessment_total_lookalike(operation, assessment, amount):
                continue
            seen.add(operation.id)
            label = canonical_benchmark_category(
                operation.raw_description, normalise_description(operation.raw_description)
            )
            rows.append(
                _Row(
                    origin=ORIGIN_ASSESSMENT,
                    line_id=operation.id,
                    description=operation.raw_description,
                    line_item_type=operation.category,
                    kind=_price_kind(operation.category),
                    amount=amount,
                    repair_item=_display(label, False),
                    repair_item_key=_slug(label),
                    assessment=assessment,
                )
            )
    return rows


def _evidence(invoice: Invoice, row: _Row) -> dict[str, Any]:
    vehicle = invoice.vehicle
    document = (
        row.assessment.document
        if row.origin == ORIGIN_ASSESSMENT and row.assessment is not None
        else invoice.document
    )
    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "document_filename": document.original_filename if document is not None else None,
        "vehicle_make": vehicle.make if vehicle else None,
        "vehicle_model": vehicle.model if vehicle else None,
        "registration": vehicle.registration if vehicle else None,
        "description": row.description,
        "amount": _text(row.amount),
        "origin": row.origin,
        "source_line_id": row.line_id,
        # Additive to the contract: which assessment a row came from.
        "assessment_number": (
            row.assessment.assessment_number
            if row.origin == ORIGIN_ASSESSMENT and row.assessment is not None
            else None
        ),
    }


_GroupKey = tuple[str, str, str]


@dataclass
class _Population:
    source: BenchmarkSource
    invoices: list[tuple[Invoice, VehicleCategory]]
    groups: dict[_GroupKey, list[tuple[Decimal, _Row, dict[str, Any]]]]


def _population(
    session: Session,
    data: _CaseData,
    source: BenchmarkSource,
    *,
    exclude_invoice_id: str | None = None,
) -> _Population:
    invoices = [
        invoice
        for invoice in data.invoices
        if _is_uploaded_invoice(invoice)
        and _intake_group(invoice) == source.intake_group
        and invoice.id != exclude_invoice_id
    ]
    categorised = [(invoice, _vehicle_category(data, invoice)) for invoice in invoices]
    groups: dict[_GroupKey, list[tuple[Decimal, _Row, dict[str, Any]]]] = {}
    for invoice, category in categorised:
        for row in _invoice_rows(session, data, invoice):
            if row.amount is None or row.amount <= 0:
                continue
            key = (category.category, row.repair_item_key, row.kind)
            groups.setdefault(key, []).append((row.amount, row, _evidence(invoice, row)))
    for observations in groups.values():
        observations.sort(
            key=lambda item: (
                str(item[2]["invoice_number"] or ""),
                item[1].origin != ORIGIN_INVOICE,
                item[1].description,
                item[1].line_id,
            )
        )
    return _Population(source=source, invoices=categorised, groups=groups)


def _statistics(observations: list[tuple[Decimal, _Row, dict[str, Any]]]):
    return calculate_benchmark_statistics(amount for amount, _, _ in observations)


# ---------------------------------------------------------------------------
# GET /claims/{ref}/benchmarks?source=
# ---------------------------------------------------------------------------


def _case(session: Session, case_reference: str) -> Case:
    case = session.scalar(select(Case).where(Case.case_reference == case_reference))
    if case is None:
        raise BenchmarkAnalysisError("NOT_FOUND", "Claim not found", 404)
    return case


def _threshold(value: Decimal | None) -> Decimal:
    return Decimal(DEFAULT_POLICY.default_threshold_pct) if value is None else value


def _threshold_text(value: Decimal) -> str:
    return f"{value.normalize():f}"


def build_source_benchmarks(
    session: Session,
    case_reference: str,
    source_key: str,
    *,
    threshold_pct: Decimal | None = None,
) -> dict[str, Any]:
    source = SOURCES.get(source_key)
    if source is None:
        raise BenchmarkAnalysisError(
            "UNKNOWN_SOURCE", f"source must be one of: {', '.join(sorted(SOURCES))}"
        )
    case = _case(session, case_reference)
    data = _load(session, case)
    population = _population(session, data, source)

    rows = []
    for (category, key, kind), observations in population.groups.items():
        statistics = _statistics(observations)
        first_row = observations[0][1]
        rows.append(
            {
                "vehicle_category": category,
                "repair_item": first_row.repair_item,
                "repair_item_key": key,
                "line_item_type": kind,
                "observations": statistics.count,
                "p90": _text(statistics.percentile_90),
                "median": _text(statistics.median),
                "min": _text(statistics.minimum),
                "max": _text(statistics.maximum),
                "evidence": [evidence for _, _, evidence in observations],
            }
        )
    rows.sort(key=lambda row: (row["vehicle_category"], row["line_item_type"], row["repair_item"]))

    by_category: dict[str, list[VehicleCategory]] = {}
    for _, category in population.invoices:
        by_category.setdefault(category.category, []).append(category)
    vehicle_categories = [
        {
            "category": category,
            "invoice_count": len(resolved),
            "source": (
                resolved[0].source
                if len({item.source for item in resolved}) == 1
                else "mixed"
            ),
        }
        for category, resolved in sorted(by_category.items())
    ]
    approval = (case.mapping_group_approvals_json or {}).get(source.intake_group)
    return {
        "source": source.key,
        "intake_group": source.intake_group,
        "label": source.label,
        "invoice_count": len(population.invoices),
        "threshold_pct": _threshold_text(_threshold(threshold_pct)),
        "vehicle_categories": vehicle_categories,
        "rows": rows,
        # Additive to the contract: each vehicle's category and where it came
        # from, and whether this source's mapping has been approved.
        "invoices": [
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "document_filename": invoice.document.original_filename,
                "vehicle_make": invoice.vehicle.make if invoice.vehicle else None,
                "vehicle_model": invoice.vehicle.model if invoice.vehicle else None,
                "registration": invoice.vehicle.registration if invoice.vehicle else None,
                "vehicle_category": category.category,
                "vehicle_category_source": category.source,
            }
            for invoice, category in population.invoices
        ],
        "mapping_approved": bool(approval),
    }


# ---------------------------------------------------------------------------
# GET /claims/{ref}/benchmark-analysis?invoice_id=
# ---------------------------------------------------------------------------


def _live_invoices(data: _CaseData) -> list[Invoice]:
    return [
        invoice
        for invoice in data.invoices
        if _is_uploaded_invoice(invoice) and _intake_group(invoice) == LIVE_GROUP
    ]


def _analysis_line(
    row: _Row,
    category: VehicleCategory,
    populations: dict[str, _Population],
    threshold_pct: Decimal,
) -> dict[str, Any]:
    comparisons: dict[str, dict[str, Any]] = {}
    for key, population in populations.items():
        observations = population.groups.get(
            (category.category, row.repair_item_key, row.kind), []
        )
        statistics = _statistics(observations)
        compared = compare_to_benchmark(
            row.amount,
            statistics.percentile_90,
            statistics.count,
            threshold_pct=threshold_pct,
        )
        compared["evidence"] = [evidence for _, _, evidence in observations]
        comparisons[key] = compared
    return {
        "line_id": row.line_id,
        "origin": row.origin,
        "line_item_type": row.line_item_type,
        "description": row.description,
        "repair_item": row.repair_item,
        "amount": _text(row.amount),
        "benchmarks": comparisons,
        "challenge": challenge_for_line(row.amount, comparisons, threshold_pct=threshold_pct),
    }


def build_benchmark_analysis(
    session: Session,
    case_reference: str,
    *,
    invoice_id: str | None = None,
    threshold_pct: Decimal | None = None,
) -> dict[str, Any]:
    threshold = _threshold(threshold_pct)
    case = _case(session, case_reference)
    data = _load(session, case)
    live = _live_invoices(data)
    if invoice_id:
        invoice = next(
            (row for row in data.invoices if row.id == invoice_id and _is_uploaded_invoice(row)),
            None,
        )
        if invoice is None:
            raise BenchmarkAnalysisError(
                "INVOICE_NOT_FOUND", "Invoice not found in this claim.", 404
            )
    else:
        if not live:
            raise BenchmarkAnalysisError(
                "NO_LIVE_INVOICE", "Upload a new invoice to analyse against the benchmarks.", 404
            )
        invoice = live[-1]

    category = _vehicle_category(data, invoice)
    # The invoice under analysis never helps set its own benchmark.
    populations = {
        key: _population(session, data, source, exclude_invoice_id=invoice.id)
        for key, source in SOURCES.items()
    }
    lines = [
        _analysis_line(row, category, populations, threshold)
        for row in _invoice_rows(session, data, invoice)
    ]
    assessment = data.assessment_by_invoice.get(invoice.id)
    challenges = [line for line in lines if line["challenge"]["is_challenge"]]
    total = sum(
        (Decimal(line["challenge"]["challenge_amount"]) for line in challenges), Decimal("0")
    )
    vehicle = invoice.vehicle
    return {
        "invoice": {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "vehicle_make": vehicle.make if vehicle else None,
            "vehicle_model": vehicle.model if vehicle else None,
            "vehicle_category": category.category,
            "vehicle_category_source": category.source,
            "registration": vehicle.registration if vehicle else None,
            "paired_assessment_number": assessment.assessment_number if assessment else None,
            "intake_group": _intake_group(invoice),
        },
        "live_invoices": [
            {
                "id": row.id,
                "invoice_number": row.invoice_number,
                "registration": row.vehicle.registration if row.vehicle else None,
            }
            for row in live
        ],
        "threshold_pct": _threshold_text(threshold),
        "minimum_challenge_amount": _text(DEFAULT_POLICY.minimum_challenge_amount),
        "lines": lines,
        "section_breakdowns": [
            {"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, **breakdown}
            for breakdown in _breakdowns(session, data, invoice)
        ],
        "totals": {
            "line_count": len(lines),
            "challenge_count": len(challenges),
            "by_level": {
                level: sum(1 for line in lines if line["challenge"]["level"] == level)
                for level in ("high", "medium", "low")
            },
            "total_challenge_amount": _text(total),
        },
    }


# ---------------------------------------------------------------------------
# POST /claims/{ref}/challenge-email
# ---------------------------------------------------------------------------

#: Keys whose values are money in an analysis payload -- the only figures an
#: email may quote.
_MONEY_KEYS = frozenset(
    {
        "amount",
        "p90",
        "difference",
        "justified_amount",
        "challenge_amount",
        "total_challenge_amount",
        "minimum_challenge_amount",
        "invoice_total",
        "assessment_total",
        "rows_total",
        "total_net",
        "unit_price_net",
    }
)
_MONEY_PATTERN = re.compile(r"£\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")


def money_figures_in_text(text: str) -> set[Decimal]:
    """Every £ figure in ``text``, normalised to pence."""

    figures = set()
    for whole, pence in _MONEY_PATTERN.findall(text or ""):
        figures.add(_money(Decimal(f"{whole.replace(',', '')}.{pence or '0'}")))
    return figures


def analysis_money_figures(analysis: Any) -> set[Decimal]:
    """Every money figure an analysis payload contains, at any depth."""

    figures: set[Decimal] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _MONEY_KEYS and isinstance(item, (str, int, float, Decimal)):
                    try:
                        figures.add(_money(Decimal(str(item))))
                    except ArithmeticError:
                        pass
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(analysis)
    return figures


def _origin_label(origin: str) -> str:
    return "engineer assessment" if origin == ORIGIN_ASSESSMENT else "invoice"


def _figures_list(lines: list[dict[str, Any]], rationales: dict[str, str]) -> str:
    entries = []
    for index, line in enumerate(lines, 1):
        challenge = line["challenge"]
        entry = (
            f"{index}. {line['description']} ({line['repair_item']}, from the "
            f"{_origin_label(line['origin'])}): invoiced {_gbp(line['amount'])}; "
            f"justified figure {_gbp(challenge['justified_amount'])}; "
            f"challenged {_gbp(challenge['challenge_amount'])}.\n"
            f"   {challenge['reason']}"
        )
        if rationales.get(line["line_id"]):
            entry += f"\n   {rationales[line['line_id']].strip()}"
        entries.append(entry)
    return "\n\n".join(entries)


def _reference_line(invoice: dict[str, Any]) -> str:
    parts = [f"repair invoice {invoice.get('invoice_number') or invoice.get('id')}"]
    vehicle = " ".join(
        value for value in (invoice.get("vehicle_make"), invoice.get("vehicle_model")) if value
    )
    if vehicle:
        parts.append(f"vehicle {vehicle}")
    if invoice.get("registration"):
        parts.append(f"registration {invoice['registration']}")
    return "Re: " + ", ".join(parts)


def _template(
    analysis: dict[str, Any], lines: list[dict[str, Any]], total: Decimal, recipient: str | None
) -> tuple[str, str]:
    invoice = analysis["invoice"]
    count = len(lines)
    subject = (
        f"Repair invoice {invoice.get('invoice_number') or invoice.get('id')}: "
        f"{count} item{'s' if count != 1 else ''} challenged, {_gbp(total)}"
    )
    body = "\n\n".join(
        [
            f"Dear {recipient or 'Sir or Madam'},",
            _reference_line(invoice),
            (
                "We have reviewed this invoice line by line against our repair-cost "
                f"benchmarks for {invoice.get('vehicle_category') or 'Unknown'} vehicles: "
                "the 90th percentile (P90) of the same repair item on insurer third party "
                "invoices and EXL/in-house invoices. Both sources are required. The proposed "
                "price is 50% of each source's P90, rounded to the nearest penny. "
                f"A line is challenged where it exceeds this combined price by more than "
                f"{analysis['threshold_pct']}% and by at least "
                f"{_gbp(analysis['minimum_challenge_amount'])}."
            ),
            "We challenge the following items:",
            _figures_list(lines, {}),
            f"Total challenged: {_gbp(total)}.",
            (
                "Please review these items and confirm the revised amount, or send "
                "supporting evidence for the invoiced figures."
            ),
            "Kind regards,\nClaims handler",
        ]
    )
    return subject, body


def compose_challenge_email(
    analysis: dict[str, Any],
    selected_lines: list[dict[str, Any]],
    *,
    recipient: str | None,
    writer: Any,
) -> dict[str, Any]:
    """The draft for the selected lines.  Never sends anything.

    The figures list is assembled here, deterministically.  A configured
    writer may supply the subject, opening, closing and one rationale per
    line; if any of that text quotes a £ figure the analysis does not contain,
    the whole AI draft is discarded for the template.  The one derived figure
    is the total of the selected lines, which the template also quotes.
    """

    total = sum(
        (Decimal(line["challenge"]["challenge_amount"]) for line in selected_lines),
        Decimal("0"),
    )
    allowed = analysis_money_figures(analysis) | {_money(total)}
    subject, body = _template(analysis, selected_lines, total, recipient)
    generated_by = "template"

    if writer is not None:
        payload = {
            "invoice": analysis["invoice"],
            "recipient": recipient,
            "pricing_method": "50% Third-party P90 + 50% In-house P90; both required",
            "threshold_pct": analysis["threshold_pct"],
            "minimum_challenge_amount": analysis["minimum_challenge_amount"],
            "total_challenge_amount": _text(total),
            "lines": [
                {
                    "line_id": line["line_id"],
                    "description": line["description"],
                    "repair_item": line["repair_item"],
                    "origin": line["origin"],
                    "amount": line["amount"],
                    "level": line["challenge"]["level"],
                    "justified_amount": line["challenge"]["justified_amount"],
                    "challenge_amount": line["challenge"]["challenge_amount"],
                    "reason": line["challenge"]["reason"],
                }
                for line in selected_lines
            ],
        }
        try:
            prose = writer.write(payload)
            selected_ids = {line["line_id"] for line in selected_lines}
            rationales = {
                str(item["line_id"]): str(item["rationale"])
                for item in prose.get("rationales") or []
                if str(item.get("line_id")) in selected_ids
            }
            texts = [
                str(prose["subject"]),
                str(prose["opening"]),
                str(prose["closing"]),
                *rationales.values(),
            ]
            if all(money_figures_in_text(text) <= allowed for text in texts):
                subject = str(prose["subject"]).strip()
                body = "\n\n".join(
                    [
                        f"Dear {recipient or 'Sir or Madam'},",
                        _reference_line(analysis["invoice"]),
                        str(prose["opening"]).strip(),
                        _figures_list(selected_lines, rationales),
                        f"Total challenged: {_gbp(total)}.",
                        str(prose["closing"]).strip(),
                        "Kind regards,\nClaims handler",
                    ]
                )
                generated_by = "ai"
        except Exception:  # noqa: BLE001 - any AI failure means the template
            pass

    return {
        "subject": subject,
        "body": body,
        "generated_by": generated_by,
        "lines": selected_lines,
        "total_challenge_amount": _text(total),
    }


def build_challenge_email_writer() -> Any:
    """The configured writer, or ``None`` -- the normal state on a client machine."""

    return benchmark_writing.build_challenge_email_writer(get_settings())


def draft_challenge_email(
    session: Session,
    case_reference: str,
    *,
    invoice_id: str,
    line_ids: Iterable[str],
    recipient: str | None,
    actor: str,
) -> dict[str, Any]:
    """Draft (never send) the email, and record one audit event saying so."""

    requested = list(dict.fromkeys(line_ids))
    analysis = build_benchmark_analysis(session, case_reference, invoice_id=invoice_id)
    by_id = {line["line_id"]: line for line in analysis["lines"]}
    unknown = [line_id for line_id in requested if line_id not in by_id]
    if unknown:
        raise BenchmarkAnalysisError(
            "UNKNOWN_LINE", f"Not lines of this invoice's analysis: {', '.join(unknown)}"
        )
    not_challenged = [
        line_id for line_id in requested if not by_id[line_id]["challenge"]["is_challenge"]
    ]
    if not_challenged:
        raise BenchmarkAnalysisError(
            "LINE_NOT_CHALLENGED",
            "Only High and Medium lines are challenges: "
            + ", ".join(not_challenged),
        )
    # Analysis order, not request order: invoice lines first, then assessment.
    selected = [line for line in analysis["lines"] if line["line_id"] in set(requested)]
    draft = compose_challenge_email(
        analysis,
        selected,
        recipient=(recipient or "").strip() or None,
        writer=build_challenge_email_writer(),
    )

    case = _case(session, case_reference)
    session.add(
        AuditEvent(
            case_id=case.id,
            processing_run_id=case.current_processing_run_id,
            actor_type=AuditActorType.USER,
            actor_id=actor,
            event_type="CHALLENGE_EMAIL_DRAFTED",
            entity_type="invoice",
            entity_id=analysis["invoice"]["id"],
            before_json=None,
            after_json={
                "subject": draft["subject"],
                "total_challenge_amount": draft["total_challenge_amount"],
            },
            event_payload_json={
                "line_ids": [line["line_id"] for line in selected],
                "levels": {line["line_id"]: line["challenge"]["level"] for line in selected},
                "challenge_amounts": {
                    line["line_id"]: line["challenge"]["challenge_amount"] for line in selected
                },
                "generated_by": draft["generated_by"],
                "recipient": (recipient or "").strip() or None,
                "threshold_pct": analysis["threshold_pct"],
                # A draft only: the server never sends it.
                "sent": False,
            },
        )
    )
    return draft
