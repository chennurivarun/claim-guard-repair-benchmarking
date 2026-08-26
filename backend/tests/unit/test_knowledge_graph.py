from app.config import Settings
from app.services.knowledge_graph import build_challenge_knowledge_graph, sync_to_neo4j


def test_graph_uses_actual_positive_challenge_outcomes() -> None:
    payload = build_challenge_knowledge_graph(
        {
            "case": {"case_reference": "CG-1"},
            "invoices": [
                {"id": "inv-1", "invoice_number": "A-1", "repairer": "Repairer A"},
                {"id": "inv-2", "invoice_number": "A-2", "repairer": "Repairer A"},
            ],
            "lines": [
                {"id": "line-1", "invoice_id": "inv-1", "description": "Rear bumper"},
                {"id": "line-2", "invoice_id": "inv-2", "description": "Rear bumper"},
            ],
            "mappings": [
                {"line_id": "line-1", "ontology_item_id": "bumper", "ontology_item_name": "Rear bumper"},
                {"line_id": "line-2", "ontology_item_id": "bumper", "ontology_item_name": "Rear bumper"},
            ],
            "challenges": [
                {
                    "line_id": "line-1",
                    "invoice_id": "inv-1",
                    "invoice_net": 200,
                    "challenge_price_net": 150,
                    "challenge_amount_net": 50,
                },
                {
                    "line_id": "line-2",
                    "invoice_id": "inv-2",
                    "invoice_net": 220,
                    "challenge_price_net": 160,
                    "challenge_amount_net": 60,
                },
                {"line_id": "ignored", "invoice_id": "inv-1", "challenge_amount_net": 0},
            ],
        }
    )

    assert payload["summary"]["challengedInvoiceCount"] == 2
    assert payload["summary"]["potentialReduction"] == 110
    assert payload["summary"]["mostChallengedRepairer"]["name"] == "Repairer A"
    assert payload["summary"]["mostChallengedItem"]["name"] == "Rear bumper"
    assert payload["edges"][0]["challengeCount"] == 2
    assert len(payload["edges"][0]["evidence"]) == 2


def test_neo4j_is_optional_for_local_operation() -> None:
    payload = {"caseReference": "CG-1", "edges": []}
    assert sync_to_neo4j(payload, Settings(neo4j_uri=None)) is False
    assert payload.get("storage") is None
