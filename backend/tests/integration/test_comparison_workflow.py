from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.enums import (
    ApprovalStatus,
    CaseStatus,
    ChallengeStatus,
    ComparisonStatus,
    DocumentRole,
    MappingStatus,
)
from app.importers.seed_workbooks import SeedWorkbookBundle, load_seed_workbooks
from app.init_db import initialize_database
from app.llm.mapping import ConstrainedMappingAdjudicator
from app.models import (
    Case,
    ChallengeResult,
    ComparisonComparable,
    Invoice,
    InvoiceLineItem,
    MappingRun,
    OntologyMapping,
    PriceComparison,
    ProcessingRun,
)
from app.services import document_processing
from app.services.case_result import build_case_result, build_claim_workspace
from app.services.comparison_workflow import run_case_comparison
from app.services.reprocessing import reprocess_case
from app.services.seed_import_service import import_seed_workbooks

SAMPLE_DATA = Path(__file__).resolve().parents[3] / "sample-data"
ONTOLOGY_PATH = SAMPLE_DATA / "ontology_seed.xlsx"
HISTORY_PATH = SAMPLE_DATA / "historical_claims_seed.xlsx"
INVOICE_PATH = SAMPLE_DATA / "1643919_doc_16439191.pdf.pdf"


@pytest.fixture()
def comparison_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    required = (ONTOLOGY_PATH, HISTORY_PATH, INVOICE_PATH)
    if not all(path.is_file() for path in required):
        pytest.skip("Supplied comparison acceptance files are not available")

    engine = create_engine(f"sqlite:///{tmp_path / 'comparison.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    yield engine
    engine.dispose()


def _count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


class ReplacementPilotAdapter:
    """AT-009 replacement provider using the canonical adapter contract."""

    provider_key = "replacement_pilot"

    def __init__(self) -> None:
        self.called = False

    def load(self, ontology_path: Path, historical_path: Path) -> SeedWorkbookBundle:
        self.called = True
        return load_seed_workbooks(ontology_path, historical_path)


class AllowListedMappingClient:
    """Selects only the first candidate supplied by the workflow."""

    provider = "acceptance-stub"
    model_id = "mapping-v1"

    def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        candidates = kwargs["payload"]["candidate_options"]
        return {
            "selected_ontology_id": candidates[0]["ontology_id"],
            "confidence": 0.96,
            "rationale": "Selected from the supplied candidate allow-list.",
        }


def test_native_invoice_comparison_persists_reviewable_results(
    comparison_engine,
) -> None:
    with Session(comparison_engine, expire_on_commit=False) as session:
        replacement_adapter = ReplacementPilotAdapter()
        imported = import_seed_workbooks(
            session,
            ONTOLOGY_PATH,
            HISTORY_PATH,
            adapter=replacement_adapter,
        )
        assert replacement_adapter.called is True
        assert imported.ontology_items_created == 72
        assert imported.historical_observations_created == 191

        case = Case(case_reference="CG-COMPARE-91283", created_by="pytest.handler")
        session.add(case)
        session.flush()
        document = document_processing.store_pdf(
            session,
            case=case,
            filename=INVOICE_PATH.name,
            content=INVOICE_PATH.read_bytes(),
            role=DocumentRole.CURRENT,
        )
        extraction_run = document_processing.process_document(session, document)
        assert extraction_run.metrics_json == {
            "page_count": 2,
            "invoice_units": 1,
            "extracted_lines": 18,
        }
        extracted_lines = session.scalars(select(InvoiceLineItem)).all()
        assert all(
            line.status.value == "approved"
            for line in extracted_lines
            if Decimal(str(line.extraction_confidence or 0)) > Decimal("0.95")
        )

        result = run_case_comparison(session, case)
        session.commit()

        assert result["status"] == "succeeded"
        assert result["line_count"] == 18
        assert result["mapped_count"] == 18
        assert result["challenged_line_count"] == 2
        assert result["invoice_summaries"] == [
            {
                "invoice_id": result["invoice_summaries"][0]["invoice_id"],
                "invoice_price_net": "643.26",
                "challenge_price_net": "546.51",
                "challenge_amount_net": "96.75",
                "vat_impact": "19.35",
                "gross_effect": "116.10",
                "challenged_lines": 2,
            }
        ]
        assert case.status == CaseStatus.COMPARISON_REVIEW
        assert _count(session, MappingRun) == 1
        assert _count(session, OntologyMapping) == 18
        assert _count(session, PriceComparison) == 18
        assert _count(session, ChallengeResult) == 19

        mappings = session.scalars(select(OntologyMapping)).all()
        high_confidence_mappings = [
            mapping
            for mapping in mappings
            if mapping.selected_ontology_item_id
            and Decimal(str(mapping.combined_confidence or 0)) > Decimal("0.95")
        ]
        review_mappings = [mapping for mapping in mappings if mapping not in high_confidence_mappings]
        assert high_confidence_mappings
        assert all(
            mapping.final_status == MappingStatus.AUTO_ACCEPTED
            for mapping in high_confidence_mappings
        )
        assert all(
            mapping.flags_json["human_review_required"] is False
            for mapping in high_confidence_mappings
        )
        assert all(mapping.final_status == MappingStatus.REVIEW for mapping in review_mappings)
        assert all(
            mapping.flags_json["human_review_required"] is True
            for mapping in review_mappings
        )
        assert all(
            mapping.flags_json["ontology_approval"] in {None, ApprovalStatus.PROVISIONAL.value}
            for mapping in mappings
        )

        comparisons = session.scalars(select(PriceComparison)).all()
        assert all(row.status == ComparisonStatus.REVIEW for row in comparisons)
        assert all(row.benchmark_policy_version == "claimguard-v1.4" for row in comparisons)
        assert all(
            row.benchmark_formula_json["ontology_weight"] == "0.60"
            and row.benchmark_formula_json["historical_weight"] == "0.40"
            for row in comparisons
        )
        assert all(row.eligibility_flags_json["review_required"] is True for row in comparisons)

        challenges = session.scalars(select(ChallengeResult)).all()
        assert all(row.status == ChallengeStatus.REVIEW for row in challenges)
        assert all(row.reviewer_approved is False for row in challenges)
        assert all(Decimal(row.challenge_net) >= 0 for row in challenges)

        invoice = session.scalar(select(Invoice))
        assert invoice is not None
        invoice_challenge = session.scalar(
            select(ChallengeResult).where(ChallengeResult.invoice_id == invoice.id)
        )
        assert invoice_challenge is not None
        line_challenge_total = sum(
            (
                Decimal(row.challenge_net)
                for row in challenges
                if row.price_comparison_id is not None
            ),
            Decimal("0"),
        )
        assert Decimal(invoice_challenge.challenge_net) == line_challenge_total
        invoice_line_net = sum(
            (Decimal(row.invoice_line_net) for row in comparisons),
            Decimal("0"),
        )
        assert Decimal(invoice_challenge.recommended_payable_net) == (
            invoice_line_net - line_challenge_total
        )

        comparable_count = _count(session, ComparisonComparable)
        assert comparable_count > 0
        assert comparable_count == sum(row.n_comparables for row in comparisons)
        for comparison in comparisons:
            persisted_count = session.scalar(
                select(func.count())
                .select_from(ComparisonComparable)
                .where(ComparisonComparable.price_comparison_id == comparison.id)
            )
            assert persisted_count == comparison.n_comparables
            flags = comparison.eligibility_flags_json["flags"]
            if comparison.n_comparables >= 3 and "HISTORY_QUANTITY_NOT_VERIFIABLE" not in flags:
                assert comparison.selected_benchmark_source == "history"
            else:
                assert comparison.selected_benchmark_source == "none"

        assert comparable_count == 86
        serialized = build_case_result(session, case.case_reference)
        serialized_comparisons = serialized["comparisons"]
        assert sum(len(row["comparables"]) for row in serialized_comparisons) == 86
        assert all("difference_from_ontology_net" in row for row in serialized_comparisons)
        assert all("difference_from_history_net" in row for row in serialized_comparisons)
        workspace = build_claim_workspace(session, case.case_reference)
        high_confidence_line_ids = {
            mapping.invoice_line_item_id for mapping in high_confidence_mappings
        }
        assert all(
            row["mappingStatus"] == "MATCH"
            for row in workspace["lines"]
            if row["id"] in high_confidence_line_ids
        )
        air_filter_workspace = next(
            row for row in workspace["lines"] if row["description"] == "Air Filter"
        )
        assert air_filter_workspace["differenceFromOntology"] == 7.6
        assert air_filter_workspace["differenceFromHistory"] == 6.75
        assert len(air_filter_workspace["comparables"]) == 9
        assert {
            "priceNet",
            "observedDate",
            "settlementStatus",
            "approvalStatus",
            "vehicle",
            "comparabilityMetadata",
            "weight",
            "eligibilityReason",
        } <= air_filter_workspace["comparables"][0].keys()
        comparison_by_description = {
            row.invoice_line_item.raw_description: row for row in comparisons
        }
        challenge_by_comparison = {
            row.price_comparison_id: row
            for row in challenges
            if row.price_comparison_id is not None
        }
        oil_filter = comparison_by_description["Oil Filter"]
        assert oil_filter.benchmark_formula_json["difference_from_history"] == "2.85"
        assert Decimal(challenge_by_comparison[oil_filter.id].challenge_net) == Decimal("0.00")

        mot_result = session.scalar(
            select(ChallengeResult)
            .join(PriceComparison)
            .join(InvoiceLineItem)
            .where(func.lower(InvoiceLineItem.raw_description).contains("mot"))
        )
        assert mot_result is not None
        assert Decimal(mot_result.challenge_vat) == Decimal("0.00")
        assert Decimal(invoice_challenge.challenge_vat) == sum(
            (
                Decimal(row.challenge_vat)
                for row in challenges
                if row.price_comparison_id is not None
            ),
            Decimal("0"),
        )

        replay = run_case_comparison(session, case)
        assert replay == {
            "processing_run_id": extraction_run.id,
            "status": "already_compared",
            "line_count": 18,
        }
        assert _count(session, PriceComparison) == 18
        assert _count(session, ChallengeResult) == 19

        reprocessed = reprocess_case(
            session,
            case,
            actor="pytest.handler",
        )
        session.commit()
        assert reprocessed["previous_processing_run_id"] == extraction_run.id
        assert reprocessed["processing_run_id"] != extraction_run.id
        assert reprocessed["summary_delta"]["challenge_amount_net"]["change"] == "0.00"
        assert _count(session, ProcessingRun) == 2
        assert _count(session, PriceComparison) == 36
        assert _count(session, ChallengeResult) == 38


def test_comparison_workflow_persists_constrained_llm_adjudication(
    comparison_engine,
) -> None:
    with Session(comparison_engine, expire_on_commit=False) as session:
        import_seed_workbooks(session, ONTOLOGY_PATH, HISTORY_PATH)
        case = Case(case_reference="CG-LLM-BOUNDARY", created_by="pytest.handler")
        session.add(case)
        session.flush()
        document = document_processing.store_pdf(
            session,
            case=case,
            filename=INVOICE_PATH.name,
            content=INVOICE_PATH.read_bytes(),
            role=DocumentRole.CURRENT,
        )
        document_processing.process_document(session, document)

        result = run_case_comparison(
            session,
            case,
            llm_adjudicator=ConstrainedMappingAdjudicator(AllowListedMappingClient()),
        )
        session.commit()

        assert result["status"] == "succeeded"
        mapping_run = session.scalar(select(MappingRun))
        assert mapping_run is not None
        assert mapping_run.model_provider == "acceptance-stub"
        assert mapping_run.model_name == "mapping-v1"
        assert mapping_run.prompt_version == "constrained-mapping-v1"

        mappings = session.scalars(select(OntologyMapping)).all()
        adjudicated = [mapping for mapping in mappings if mapping.ai_output_json]
        assert len(adjudicated) == 18
        assert all(mapping.llm_confidence == 0.96 for mapping in adjudicated)
        assert all(
            mapping.ai_output_json["selected_ontology_id"] == mapping.selected_ontology_item_id
            for mapping in adjudicated
        )
        assert all(mapping.retrieval_similarity is not None for mapping in adjudicated)
        assert all(mapping.selected_ontology_item_id for mapping in mappings)
