from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher

from app.domain.normalisation import normalise_description

from .models import MappingCandidate, MatchKind, OntologyItem

try:  # RapidFuzz is an optimisation, not a runtime requirement.
    from rapidfuzz.fuzz import token_set_ratio as _rapidfuzz_token_set_ratio
except ImportError:  # pragma: no cover - covered indirectly on minimal installs
    _rapidfuzz_token_set_ratio = None


# Narrow, code-owned spelling aliases prevent short invoice abbreviations from
# tying with semantically different ontology items during token-set matching.
# Business synonyms still belong to the governed ontology bank; these entries
# only cover presentation variants used by repairers for the same item.
_NORMALISED_INVOICE_ALIASES = {
    "ol filter": "oil filter",
    "oil fil": "oil filter",
    "engine oil filter": "oil filter",
    "oil filter element": "oil filter",
    "filter - oil": "oil filter",
    "oil-fltr": "oil filter",
    "oilfilter": "oil filter",
    "oil disposal": "oil & filter / environmental disposal charge",
    "oil and filter disposal": "oil & filter / environmental disposal charge",
    "waste oil disposal": "oil & filter / environmental disposal charge",
    "environmental oil disposal": "oil & filter / environmental disposal charge",
    "oil/filter disposal charge": "oil & filter / environmental disposal charge",
    "oil disposal fee": "oil & filter / environmental disposal charge",
    "waste oil and filter": "oil & filter / environmental disposal charge",
    "oil & filter disposal": "oil & filter / environmental disposal charge",
}


def normalise_part_number(value: str | None) -> str:
    """Normalise presentation punctuation while preserving the part-number identity."""

    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _fallback_token_score(left: str, right: str) -> float:
    left_tokens = " ".join(sorted(set(left.split())))
    right_tokens = " ".join(sorted(set(right.split())))
    return SequenceMatcher(None, left_tokens, right_tokens).ratio() * 100


def _fuzzy_score(left: str, right: str) -> Decimal:
    scorer: Callable[[str, str], float]
    scorer = _rapidfuzz_token_set_ratio or _fallback_token_score
    return (Decimal(str(scorer(left, right))) / Decimal("100")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def retrieve_candidates(
    *,
    description: str,
    ontology_items: Iterable[OntologyItem],
    part_number: str | None = None,
    top_k: int = 8,
    fuzzy_min: Decimal = Decimal("0.45"),
) -> tuple[MappingCandidate, ...]:
    """Retrieve deterministic exact candidates before bounded fuzzy candidates.

    The function deliberately does not decide whether a candidate is financially
    comparable. Unit, quantity, fitment and approval checks belong to the
    comparison/review stages.
    """

    raw_normalised_text = normalise_description(description)
    normalised_text = _NORMALISED_INVOICE_ALIASES.get(
        raw_normalised_text, raw_normalised_text
    )
    items = tuple(sorted(ontology_items, key=lambda item: item.item_id))
    wanted_part_number = normalise_part_number(part_number)

    if wanted_part_number:
        exact_part_matches = []
        for item in items:
            for candidate_number in item.part_numbers:
                if normalise_part_number(candidate_number) == wanted_part_number:
                    exact_part_matches.append(
                        MappingCandidate(
                            item_id=item.item_id,
                            canonical_name=item.canonical_name,
                            match_kind=MatchKind.EXACT_PART_NUMBER,
                            mapping_confidence=Decimal("1.0000"),
                            matched_on=candidate_number,
                            normalised_invoice_text=normalised_text,
                        )
                    )
                    break
        if exact_part_matches:
            return tuple(exact_part_matches[:top_k])

    exact_text_matches: list[MappingCandidate] = []
    for item in items:
        canonical = normalise_description(item.canonical_name)
        if canonical == normalised_text:
            exact_text_matches.append(
                MappingCandidate(
                    item_id=item.item_id,
                    canonical_name=item.canonical_name,
                    match_kind=MatchKind.EXACT_CANONICAL_NAME,
                    mapping_confidence=Decimal("0.9900"),
                    matched_on=item.canonical_name,
                    normalised_invoice_text=normalised_text,
                )
            )
            continue
        matched_synonym = next(
            (
                synonym
                for synonym in item.synonyms
                if normalise_description(synonym) == normalised_text
            ),
            None,
        )
        if matched_synonym is not None:
            exact_text_matches.append(
                MappingCandidate(
                    item_id=item.item_id,
                    canonical_name=item.canonical_name,
                    match_kind=MatchKind.EXACT_SYNONYM,
                    mapping_confidence=Decimal("0.9800"),
                    matched_on=matched_synonym,
                    normalised_invoice_text=normalised_text,
                )
            )
    if exact_text_matches:
        return tuple(exact_text_matches[:top_k])

    fuzzy_matches: list[MappingCandidate] = []
    for item in items:
        searchable = (item.canonical_name, *item.synonyms)
        best_text = item.canonical_name
        best_score = Decimal("0")
        for candidate_text in searchable:
            score = _fuzzy_score(normalised_text, normalise_description(candidate_text))
            if score > best_score:
                best_score = score
                best_text = candidate_text
        if best_score >= fuzzy_min:
            fuzzy_matches.append(
                MappingCandidate(
                    item_id=item.item_id,
                    canonical_name=item.canonical_name,
                    match_kind=MatchKind.FUZZY,
                    mapping_confidence=best_score,
                    matched_on=best_text,
                    normalised_invoice_text=normalised_text,
                )
            )

    fuzzy_matches.sort(key=lambda candidate: (-candidate.mapping_confidence, candidate.item_id))
    return tuple(fuzzy_matches[:top_k])
