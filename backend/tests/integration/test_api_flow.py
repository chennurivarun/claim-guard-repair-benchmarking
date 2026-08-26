from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import app.api.router as api_router_module
from app.database import get_db
from app.init_db import initialize_database
from app.main import app
from app.services import document_processing
from app.services.research_workflow import ResearchWorkflowError


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    initialize_database(engine, seed_defaults=True)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(document_processing.settings, "storage_dir", tmp_path / "storage")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def _claim_payload() -> dict:
    return {
        "case_reference": "CG-API-91283",
        "claim_number": "CLM-91283",
        "paying_insurer_name": "Insurance Company A",
        "claiming_insurer_name": "Insurance Company B",
        "accident_at": "2025-11-01T10:00:00Z",
        "accident_location": "St Albans",
        "accident_description": "Rear-end collision",
        "damage_description": "Front impact",
        "created_by": "pytest.handler",
        "vehicles": [
            {
                "role": "insured_vehicle",
                "registration": "AB12 CDE",
                "make": "Ford",
                "model": "Focus",
            },
            {
                "role": "claimant_vehicle",
                "registration": "PX64 XCU",
                "make": "Vauxhall",
                "model": "Adam Jam",
                "damage_description": "Front impact",
            },
        ],
    }


def test_claim_liability_pdf_correction_and_settlement_flow(client: TestClient) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data/1643919_doc_16439191.pdf.pdf"
    if not source.exists():
        pytest.skip("Supplied native PDF is not available")

    created = client.post("/api/v1/claims", json=_claim_payload())
    assert created.status_code == 201
    decision = client.post(
        "/api/v1/claims/CG-API-91283/liability/confirm",
        json={
            "status": "ADMITTED",
            "confirmed_by": "pytest.handler",
            "rationale": "Admission correspondence checked by handler.",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["challenge_issue_allowed"] is True

    with source.open("rb") as handle:
        uploaded = client.post(
            "/api/v1/claims/CG-API-91283/documents",
            files={"file": (source.name, handle, "application/pdf")},
            data={"role": "current"},
        )
    assert uploaded.status_code == 200
    documents = client.get("/api/v1/claims/CG-API-91283/documents")
    assert documents.status_code == 200
    assert documents.json()[0]["filename"] == source.name
    processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
    assert processed.status_code == 200
    assert processed.json()["metrics"] == {
        "page_count": 2,
        "invoice_units": 1,
        "extracted_lines": 18,
    }

    invoices = client.get("/api/v1/claims/CG-API-91283/invoices")
    assert invoices.status_code == 200
    invoice = invoices.json()[0]
    assert invoice["invoice_number"] == "91283"
    assert invoice["totals"] == {
        "labour_net": "335.00",
        "parts_net": "253.41",
        "subtotal_net": "588.41",
        "vat": "117.68",
        "non_vat": "54.85",
        "gross": "760.94",
    }
    assert len(invoice["lines"]) == 18
    assert invoice["lines"][0]["source_regions"]["row"]

    workspace = client.get("/api/v1/claims/CG-API-91283/workspace")
    assert workspace.status_code == 200
    workspace_payload = workspace.json()
    assert workspace_payload["invoice"]["documentId"] == uploaded.json()["id"]
    assert workspace_payload["invoice"]["pageNumbers"] == [1, 2]
    assert workspace_payload["checks"]
    assert workspace_payload["lines"][0]["source"]["regions"]["row"]
    assert all(
        0 <= value <= 1 for value in workspace_payload["lines"][0]["source"]["regions"]["row"]
    )

    reviewed_line = invoice["lines"][1]
    missing_reason = client.post(
        f"/api/v1/invoice-lines/{reviewed_line['id']}/extraction-decision",
        json={"decision": "rejected", "actor": "pytest.handler"},
    )
    assert missing_reason.status_code == 422
    rejected = client.post(
        f"/api/v1/invoice-lines/{reviewed_line['id']}/extraction-decision",
        json={
            "decision": "rejected",
            "actor": "pytest.handler",
            "reason": "Duplicate row in source invoice.",
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    rejected_workspace = client.get("/api/v1/claims/CG-API-91283/workspace").json()
    rejected_row = next(
        row for row in rejected_workspace["lines"] if row["id"] == reviewed_line["id"]
    )
    assert rejected_row["comparisonStatus"] == "EXCLUDED"
    restored = client.post(
        f"/api/v1/invoice-lines/{reviewed_line['id']}/extraction-decision",
        json={"decision": "undo", "actor": "pytest.handler"},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "approved"

    line = invoice["lines"][0]
    corrected = client.patch(
        f"/api/v1/invoice-lines/{line['id']}",
        json={
            "actor": "pytest.handler",
            "reason": "Verified against source region.",
            "part_number": "OIL",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["user_corrected"] is True

    settlement = client.post(
        f"/api/v1/invoices/{invoice['id']}/settlements",
        json={
            "agreed_amount_net": "600.00",
            "agreed_vat": "117.68",
            "agreed_at": "2026-07-17T10:00:00Z",
            "recorded_by": "pytest.handler",
            "note": "Invoice-level settlement; line allocation omitted.",
        },
    )
    assert settlement.status_code == 200
    assert settlement.json()["agreed_amount_net"] == "600.00"
    assert settlement.json()["line_allocations"] == 0

    claim = client.get("/api/v1/claims/CG-API-91283").json()
    codes = {finding["code"] for finding in claim["claim"]["consistency_findings"]}
    assert {
        "CLAIM_INVOICE_VRM_MATCH",
        "INVOICE_AFTER_ACCIDENT",
        "DAMAGE_REPAIR_CAUSATION_REVIEW",
    } <= codes


def test_invalid_pdf_signature_is_rejected(client: TestClient) -> None:
    assert client.post("/api/v1/claims", json=_claim_payload()).status_code == 201
    response = client.post(
        "/api/v1/claims/CG-API-91283/documents",
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        data={"role": "current"},
    )
    assert response.status_code == 422


def test_handler_mapping_decisions_and_bundle_allocations_are_governed(
    client: TestClient,
) -> None:
    sample_data = Path(__file__).resolve().parents[3] / "sample-data"
    source = sample_data / "1643919_doc_16439191.pdf.pdf"
    ontology = sample_data / "ontology_seed.xlsx"
    history = sample_data / "historical_claims_seed.xlsx"
    if not all(path.exists() for path in (source, ontology, history)):
        pytest.skip("Supplied mapping pilot files are not available")

    payload = _claim_payload()
    payload["case_reference"] = "CG-MAPPING-91283"
    assert client.post("/api/v1/claims", json=payload).status_code == 201
    seeds = client.post(
        "/api/v1/admin/seeds/import",
        json={"ontology_path": str(ontology), "historical_path": str(history)},
    )
    assert seeds.status_code == 200
    with source.open("rb") as handle:
        uploaded = client.post(
            "/api/v1/claims/CG-MAPPING-91283/documents",
            files={"file": (source.name, handle, "application/pdf")},
            data={"role": "current"},
        )
    assert uploaded.status_code == 200
    assert client.post(f"/api/v1/documents/{uploaded.json()['id']}/process").status_code == 200
    assert client.post("/api/v1/claims/CG-MAPPING-91283/compare").status_code == 200

    invoice = client.get("/api/v1/claims/CG-MAPPING-91283/invoices").json()[0]
    lines = {line["description"]: line for line in invoice["lines"]}
    air_filter = lines["Air Filter"]
    oil_filter = lines["Oil Filter"]
    service = lines["Carried Out Full Service"]
    air_item_id = air_filter["mapping"]["ontology_item_id"]
    oil_item_id = oil_filter["mapping"]["ontology_item_id"]
    assert air_item_id and oil_item_id and air_item_id != oil_item_id

    extraction_rejected = client.post(
        f"/api/v1/invoice-lines/{oil_filter['id']}/extraction-decision",
        json={
            "decision": "rejected",
            "actor": "pytest.handler",
            "reason": "Not a genuine invoice line.",
        },
    )
    assert extraction_rejected.status_code == 200
    blocked_mapping = client.post(
        f"/api/v1/claims/CG-MAPPING-91283/invoice-lines/{oil_filter['id']}/mapping-decision",
        json={
            "actor": "pytest.handler",
            "decision": "approve",
            "rationale": "This must be blocked while extraction is rejected.",
        },
    )
    assert blocked_mapping.status_code == 422
    assert blocked_mapping.json()["detail"]["code"] == "EXTRACTION_LINE_REJECTED"
    assert (
        client.post(
            f"/api/v1/invoice-lines/{oil_filter['id']}/extraction-decision",
            json={"decision": "undo", "actor": "pytest.handler"},
        ).status_code
        == 200
    )

    initial_result = client.get("/api/v1/claims/CG-MAPPING-91283/result").json()
    air_challenge = next(
        row for row in initial_result["challenges"] if row["description"] == "Air Filter"
    )
    prior_approval = client.post(
        f"/api/v1/challenge-results/{air_challenge['id']}/decision",
        json={
            "actor": "pytest.handler",
            "approved": True,
            "rationale": "Nine historic comparables support the initial result.",
        },
    )
    assert prior_approval.status_code == 200
    assert prior_approval.json()["reviewer_approved"] is True

    route = f"/api/v1/claims/CG-MAPPING-91283/invoice-lines/{air_filter['id']}/mapping-decision"
    approved = client.post(
        route,
        json={
            "actor": "pytest.handler",
            "decision": "approve",
            "rationale": "Part description and fitment verified against the invoice.",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["mapping"]["status"] == "approved"
    assert approved.json()["mapping"]["reviewed_by"] == "pytest.handler"
    assert approved.json()["challenge"]["status"] == "review"
    assert approved.json()["challenge"]["reviewer_approved"] is False

    changed = client.post(
        route,
        json={
            "actor": "pytest.handler",
            "decision": "change",
            "ontology_item_id": oil_item_id,
            "rationale": "Handler selected the correct compatible parts-bank item.",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["mapping"]["status"] == "edited"
    assert changed.json()["mapping"]["ontology_item_id"] == oil_item_id
    assert changed.json()["source_description"] == "Air Filter"

    rejected = client.post(
        route,
        json={
            "actor": "pytest.handler",
            "decision": "reject",
            "rationale": "No ontology item is sufficiently equivalent.",
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["mapping"]["status"] == "rejected"
    assert rejected.json()["comparison"]["benchmark_source"] == "none"
    assert rejected.json()["challenge"]["challenge_net"] == "0.00"
    assert rejected.json()["source_description"] == "Air Filter"

    bundle_route = f"/api/v1/claims/CG-MAPPING-91283/invoice-lines/{service['id']}/mapping-decision"
    quantities_only = client.post(
        bundle_route,
        json={
            "actor": "pytest.handler",
            "decision": "bundle",
            "rationale": "Invoice combines service operations; allocation is not yet evidenced.",
            "bundle_components": [
                {"ontology_item_id": air_item_id, "quantity": "1", "unit": "each"},
                {"ontology_item_id": oil_item_id, "quantity": "1", "unit": "each"},
            ],
        },
    )
    assert quantities_only.status_code == 200
    assert quantities_only.json()["mapping"]["is_bundled"] is True
    assert quantities_only.json()["mapping"]["flags"]["bundle_allocation_resolved"] is False
    assert quantities_only.json()["comparison"]["status"] == "review"
    assert quantities_only.json()["challenge"]["challenge_net"] == "0.00"

    mismatch = client.post(
        bundle_route,
        json={
            "actor": "pytest.handler",
            "decision": "bundle",
            "rationale": "Deliberately invalid allocation for route validation.",
            "bundle_components": [
                {
                    "ontology_item_id": air_item_id,
                    "allocated_net": "1.00",
                    "quantity": "1",
                },
                {
                    "ontology_item_id": oil_item_id,
                    "allocated_net": "1.00",
                    "quantity": "1",
                },
            ],
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "BUNDLE_ALLOCATION_MISMATCH"

    service_net = Decimal(service["line_total_net"])
    rounded_mismatch = client.post(
        bundle_route,
        json={
            "actor": "pytest.handler",
            "decision": "bundle",
            "rationale": "Sub-penny inputs must balance after each component is rounded.",
            "bundle_components": [
                {"ontology_item_id": air_item_id, "allocated_net": "82.505"},
                {"ontology_item_id": oil_item_id, "allocated_net": "82.495"},
            ],
        },
    )
    assert rounded_mismatch.status_code == 422
    assert rounded_mismatch.json()["detail"]["code"] == "BUNDLE_ALLOCATION_MISMATCH"

    first_allocation = (service_net / Decimal("2")).quantize(Decimal("0.01"))
    second_allocation = service_net - first_allocation
    allocated = client.post(
        bundle_route,
        json={
            "actor": "pytest.handler",
            "decision": "bundle",
            "rationale": "Handler allocated the full source net using worksheet evidence.",
            "bundle_components": [
                {
                    "ontology_item_id": air_item_id,
                    "allocated_net": str(first_allocation),
                    "quantity": "1",
                    "unit": "each",
                },
                {
                    "ontology_item_id": oil_item_id,
                    "allocated_net": str(second_allocation),
                    "quantity": "1",
                    "unit": "each",
                },
            ],
        },
    )
    assert allocated.status_code == 200
    body = allocated.json()
    assert body["mapping"]["status"] == "approved"
    assert body["mapping"]["flags"]["bundle_allocation_resolved"] is True
    assert (
        sum(
            Decimal(component["allocated_net"])
            for component in body["mapping"]["bundle_components"]
        )
        == service_net
    )
    assert body["source_description"] == "Carried Out Full Service"
    assert body["source_line_net"] == service["line_total_net"]

    refreshed_workspace = client.get("/api/v1/claims/CG-MAPPING-91283/workspace").json()
    refreshed_service = next(
        row for row in refreshed_workspace["lines"] if row["id"] == service["id"]
    )
    assert refreshed_service["mappingReviewStatus"] == "approved"
    assert refreshed_service["mappingReviewedBy"] == "pytest.handler"
    assert refreshed_service["isBundled"] is True
    assert len(refreshed_service["bundleComponents"]) == 2

    result = client.get("/api/v1/claims/CG-MAPPING-91283/result").json()
    service_mapping = next(row for row in result["mappings"] if row["line_id"] == service["id"])
    assert service_mapping["is_bundled"] is True
    assert len(service_mapping["bundle_components"]) == 2
    actions = [row["action"] for row in result["audit"]]
    assert actions.count("MAPPING_APPROVE") == 1
    assert actions.count("MAPPING_CHANGE") == 1
    assert actions.count("MAPPING_REJECT") == 1
    # The mismatched attempt rolled back, so only the two valid bundle decisions are immutable.
    assert actions.count("MAPPING_BUNDLE") == 2
    approval_audit = next(row for row in result["audit"] if row["action"] == "MAPPING_APPROVE")
    assert approval_audit["payload"]["previous_challenge_approval_invalidated"] is True
    assert approval_audit["payload"]["source_line_preserved"] is True


def test_research_conflicts_are_409_but_allow_list_errors_are_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post("/api/v1/claims", json=_claim_payload()).status_code == 201
    request = {
        "requested_by": "pytest.handler",
        "query_text": "Research missing item",
        "suggestion": {
            "canonical_name": "Front bumper reinforcement",
            "item_type": "part",
            "category": "Body",
            "unit": "each",
            "price_net": "100.00",
            "date_checked": "2026-07-17",
            "rationale": "Manual evidence reviewed.",
        },
        "evidence": [
            {
                "source_uri": "https://parts.example.test/item",
                "title": "Approved source",
                "price_net": "100.00",
            }
        ],
    }
    expected_statuses = {
        "RESEARCH_ALREADY_OPEN": 409,
        "RESEARCH_ALREADY_APPROVED_FOR_LINE": 409,
        "ONTOLOGY_ITEM_ALREADY_APPROVED": 409,
        "RESEARCH_IDENTITY_ALREADY_OPEN": 409,
        "EVIDENCE_CONTENT_ALREADY_RESEARCHED": 409,
        "DUPLICATE_EVIDENCE_IN_REQUEST": 409,
        "SOURCE_HOST_NOT_ALLOWED": 422,
        "SOURCE_ALLOW_LIST_NOT_CONFIGURED": 422,
    }
    for code, expected_status in expected_statuses.items():

        def reject_research(*args, _code=code, **kwargs):
            raise ResearchWorkflowError(_code, "governance test")

        monkeypatch.setattr(
            api_router_module,
            "trigger_manual_research",
            reject_research,
        )
        response = client.post(
            "/api/v1/claims/CG-API-91283/invoice-lines/test-line/research",
            json=request,
        )
        assert response.status_code == expected_status
        assert response.json()["detail"]["code"] == code


def test_governed_finalisation_and_report_routes(client: TestClient) -> None:
    source = Path(__file__).resolve().parents[3] / "sample-data/1643919_doc_16439191.pdf.pdf"
    if not source.exists():
        pytest.skip("Supplied native PDF is not available")

    payload = _claim_payload()
    payload["case_reference"] = "CG-GOVERNANCE-91283"
    assert client.post("/api/v1/claims", json=payload).status_code == 201
    liability = client.post(
        "/api/v1/claims/CG-GOVERNANCE-91283/liability/confirm",
        json={
            "status": "ADMITTED",
            "confirmed_by": "pytest.handler",
            "rationale": "Admission correspondence checked by handler.",
        },
    )
    assert liability.status_code == 200

    unready = client.post(
        "/api/v1/claims/CG-GOVERNANCE-91283/finalise",
        json={"finalised_by": "pytest.handler"},
    )
    assert unready.status_code == 409
    assert unready.json()["detail"]["code"] == "COMPARISON_NOT_READY"

    seeds = client.post(
        "/api/v1/admin/seeds/import",
        json={
            "ontology_path": str(
                Path(__file__).resolve().parents[3] / "sample-data/ontology_seed.xlsx"
            ),
            "historical_path": str(
                Path(__file__).resolve().parents[3] / "sample-data/historical_claims_seed.xlsx"
            ),
        },
    )
    assert seeds.status_code == 200
    with source.open("rb") as handle:
        uploaded = client.post(
            "/api/v1/claims/CG-GOVERNANCE-91283/documents",
            files={"file": (source.name, handle, "application/pdf")},
            data={"role": "current"},
        )
    assert uploaded.status_code == 200
    processed = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process")
    assert processed.status_code == 200
    compared = client.post("/api/v1/claims/CG-GOVERNANCE-91283/compare")
    assert compared.status_code == 200
    first_run_id = compared.json()["processing_run_id"]

    # Explicitly running comparison again must refresh stale handover results
    # instead of preserving an earlier NO_MATCH/old-policy run forever.
    refreshed = client.post("/api/v1/claims/CG-GOVERNANCE-91283/compare")
    assert refreshed.status_code == 200
    assert refreshed.json()["processing_run_id"] != first_run_id
    assert refreshed.json()["comparison"]["status"] == "succeeded"

    workspace = client.get("/api/v1/claims/CG-GOVERNANCE-91283/workspace")
    assert workspace.status_code == 200
    workspace_payload = workspace.json()
    assert workspace_payload["liability"] == {
        "status": "ADMITTED",
        "humanConfirmed": True,
        "confirmedBy": "pytest.handler",
        "rationale": "Admission correspondence checked by handler.",
        "splitLiabilityPercentage": None,
    }
    assert workspace_payload["claim"]["status"] == "comparison_review"
    assert workspace_payload["invoice"]["id"]
    assert workspace_payload["summary"] == {
        "challengePrice": 629.56,
        "challengeAmount": 13.7,
        "vatImpact": 2.74,
        "grossEffect": 16.44,
        "challengePercentage": 2.13,
        "challengeStrength": 78,
    }
    challenged_lines = [line for line in workspace_payload["lines"] if line.get("challenge", 0) > 0]
    assert len(challenged_lines) == 1
    assert sum(Decimal(str(row["challenge"])) for row in challenged_lines) == Decimal("13.70")
    assert len(workspace_payload["ontologyBank"]["items"]) == 72
    assert workspace_payload["versions"]["policy"] == "claimguard-v1.4"
    assert workspace_payload["versions"]["ontology"] == "ontology-v0-bootstrap"
    assert workspace_payload["researchItems"] == []
    assert workspace_payload["auditEvents"]

    in_house_dashboard = client.get("/api/v1/benchmarks/dashboard?source_group=in_house")
    assert in_house_dashboard.status_code == 200
    in_house_payload = in_house_dashboard.json()
    assert in_house_payload["summary"]["observationCount"] == 432
    assert len(in_house_payload["filterOptions"]["repairItems"]) == 72

    claims_dashboard = client.get("/api/v1/benchmarks/dashboard?source_group=historical_claim")
    assert claims_dashboard.status_code == 200
    claims_payload = claims_dashboard.json()
    assert claims_payload["dataQuality"]["invoiceObservationCount"] == 188
    assert claims_payload["summary"]["observationCount"] == 187

    synthetic_csv = client.get("/api/v1/admin/in-house-repair-data.csv")
    assert synthetic_csv.status_code == 200
    assert synthetic_csv.text.count("\n") == 433
    first_in_house_benchmark = in_house_payload["benchmarks"][0]
    source_rows = client.get(
        f"/api/v1/benchmarks/{first_in_house_benchmark['ontologyItemId']}/observations",
        params={
            "vehicle_class": first_in_house_benchmark["vehicleClass"],
            "source_group": "in_house",
        },
    )
    assert source_rows.status_code == 200
    assert source_rows.json()["observations"]
    assert {row["sourceGroup"] for row in source_rows.json()["observations"]} == {"in_house"}

    workspace_challenges = [row for row in workspace_payload["lines"] if row["challenge"] > 0]
    assert all(row["challengeResultId"] for row in workspace_challenges)
    assert all(row["challengeStatus"] == "review" for row in workspace_challenges)
    assert all(row["challengeApproved"] is False for row in workspace_challenges)
    result_response = client.get("/api/v1/claims/CG-GOVERNANCE-91283/result")
    assert result_response.status_code == 200
    result = result_response.json()
    assert len(result["lines"]) == 18
    assert result["summary"] == {
        "invoice_price_net": "643.26",
        "challenge_price_net": "629.56",
        "challenge_amount_net": "13.70",
        "vat_impact": "2.74",
        "gross_effect": "16.44",
        "challenge_percentage": "2.1298",
        "challenge_strength": 78,
    }

    for report_format in ("json", "xlsx", "sqlite"):
        draft_report = client.get(f"/api/v1/claims/CG-GOVERNANCE-91283/reports/{report_format}")
        assert draft_report.status_code == 200
    for report_format in ("docx", "pdf"):
        blocked_report = client.get(f"/api/v1/claims/CG-GOVERNANCE-91283/reports/{report_format}")
        assert blocked_report.status_code == 409
        assert blocked_report.json()["detail"]["code"] == "REPORT_BLOCKED"

    positive = {
        row["description"]: row
        for row in result["challenges"]
        if Decimal(row["challenge_amount_net"]) > 0
    }
    assert len(positive) == 1
    assert sum(Decimal(row["challenge_amount_net"]) for row in positive.values()) == Decimal(
        "13.70"
    )

    for row in workspace_challenges:
        rejected = client.post(
            f"/api/v1/challenge-results/{row['challengeResultId']}/decision",
            json={
                "actor": "pytest.handler",
                "approved": False,
                "rationale": "Governance test closes each proposed challenge before finalisation.",
            },
        )
        assert rejected.status_code == 200

    finalised = client.post(
        "/api/v1/claims/CG-GOVERNANCE-91283/finalise",
        json={"finalised_by": "pytest.handler", "note": "Review complete."},
    )
    assert finalised.status_code == 200, finalised.json()
    assert finalised.json()["status"] == "finalised"

    final_result = client.get("/api/v1/claims/CG-GOVERNANCE-91283/result").json()
    assert final_result["summary"] == {
        "invoice_price_net": "643.26",
        "challenge_price_net": "643.26",
        "challenge_amount_net": "0.00",
        "vat_impact": "0.00",
        "gross_effect": "0.00",
        "challenge_percentage": "0.0000",
        "challenge_strength": 0,
    }
    final_workspace = client.get("/api/v1/claims/CG-GOVERNANCE-91283/workspace").json()
    assert final_workspace["claim"]["status"] == "finalised"
    final_decisions = {
        row["description"]: (row["challengeStatus"], row["challengeApproved"])
        for row in final_workspace["lines"]
        if row["challenge"] > 0
    }
    assert set(final_decisions.values()) == {("rejected", False)}
    assert len(final_decisions) == 1
    invoice_reviews = client.get("/api/v1/claims/CG-GOVERNANCE-91283/invoices").json()
    assert invoice_reviews[0]["challenge_review"] == {
        "positive": 1,
        "approved": 0,
        "rejected": 1,
        "unresolved": 0,
    }
    assert len(invoice_reviews[0]["challenge_lines"]) == 1
    assert all(
        {
            "in_house_p90_net",
            "historical_claims_p90_net",
            "external_price_net",
        }.issubset(line)
        for line in invoice_reviews[0]["challenge_lines"]
    )
    for report_format in ("docx", "pdf"):
        report = client.get(f"/api/v1/claims/CG-GOVERNANCE-91283/reports/{report_format}")
        assert report.status_code == 409
        assert report.json()["detail"]["code"] == "REPORT_BLOCKED"

    repeated_finalise = client.post(
        "/api/v1/claims/CG-GOVERNANCE-91283/finalise",
        json={"finalised_by": "pytest.handler"},
    )
    assert repeated_finalise.status_code == 409
    assert repeated_finalise.json()["detail"]["code"] == "CASE_ALREADY_FINALISED"
    with source.open("rb") as handle:
        blocked_upload = client.post(
            "/api/v1/claims/CG-GOVERNANCE-91283/documents",
            files={"file": (source.name, handle, "application/pdf")},
            data={"role": "current"},
        )
    assert blocked_upload.status_code == 409
    assert blocked_upload.json()["detail"]["code"] == "CASE_ALREADY_FINALISED"
    blocked_reprocess = client.post(f"/api/v1/documents/{uploaded.json()['id']}/process?force=true")
    assert blocked_reprocess.status_code == 409
    assert blocked_reprocess.json()["detail"]["code"] == "CASE_ALREADY_FINALISED"
