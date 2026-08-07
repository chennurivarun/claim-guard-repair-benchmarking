from pathlib import Path

import pytest

from app.importers.seed_workbooks import load_seed_workbooks


def test_supplied_seed_counts_and_gold_isolation() -> None:
    sample_data = Path(__file__).resolve().parents[3] / "sample-data"
    ontology = sample_data / "ontology_seed.xlsx"
    history = sample_data / "historical_claims_seed.xlsx"
    if not ontology.exists() or not history.exists():
        pytest.skip("Supplied workbooks are not available")
    bundle = load_seed_workbooks(ontology, history)
    assert len(bundle.ontology_items) == 72
    assert len(bundle.runtime_history) == 191
    assert len(bundle.invoice_summaries) == 29
    assert len(bundle.acceptance_gold) == 34
    assert sum(row.document_role == "invoice" for row in bundle.runtime_history) == 188
    assert sum(row.document_role == "estimate" for row in bundle.runtime_history) == 3
    assert {row.claim_line_id for row in bundle.runtime_history}.isdisjoint(
        row.claim_line_id for row in bundle.acceptance_gold
    )
    assert all(item.approval_status == "Provisional" for item in bundle.ontology_items)
    assert sum(item.reference_price_net is None for item in bundle.ontology_items) == 9
    assert {row.invoice_number for row in bundle.acceptance_gold} == {"90538", "91283"}
