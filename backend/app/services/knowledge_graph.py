"""Challenge-outcome knowledge graph projection and optional Neo4j persistence."""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.config import Settings

LOGGER = logging.getLogger(__name__)


def _money(value: Any) -> float:
    try:
        return float(Decimal(str(value or 0)).quantize(Decimal("0.01")))
    except (ArithmeticError, ValueError):
        return 0.0


def build_challenge_knowledge_graph(result: dict[str, Any]) -> dict[str, Any]:
    """Project actual positive challenge decisions into repairer-item relationships."""

    invoices = {str(row["id"]): row for row in result.get("invoices", [])}
    lines = {str(row["id"]): row for row in result.get("lines", [])}
    mappings = {str(row["line_id"]): row for row in result.get("mappings", [])}
    relationships: dict[tuple[str, str], dict[str, Any]] = {}
    repairer_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"invoiceIds": set(), "challengeCount": 0, "totalChallenge": 0.0}
    )
    item_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "label": "",
            "invoiceIds": set(),
            "challengeCount": 0,
            "totalChallenge": 0.0,
        }
    )

    for challenge in result.get("challenges", []):
        amount = _money(challenge.get("challenge_amount_net"))
        if amount <= 0 or str(challenge.get("status") or "").casefold() == "rejected":
            continue
        line_id = str(challenge.get("line_id") or "")
        invoice_id = str(challenge.get("invoice_id") or lines.get(line_id, {}).get("invoice_id") or "")
        invoice = invoices.get(invoice_id, {})
        mapping = mappings.get(line_id, {})
        repairer = str(invoice.get("repairer") or "Unknown repairer").strip()
        item_id = str(
            challenge.get("ontology_item_id")
            or mapping.get("ontology_item_id")
            or f"unmapped:{line_id}"
        )
        item_label = str(
            mapping.get("ontology_item_name")
            or challenge.get("description")
            or lines.get(line_id, {}).get("description")
            or "Unmapped repair item"
        ).strip()
        invoice_number = str(invoice.get("invoice_number") or invoice_id)
        billed = _money(challenge.get("invoice_net") or lines.get(line_id, {}).get("invoice_net"))
        supported = _money(challenge.get("challenge_price_net"))
        evidence = {
            "lineId": line_id,
            "invoiceId": invoice_id,
            "invoiceNumber": invoice_number,
            "repairer": repairer,
            "description": str(challenge.get("description") or item_label),
            "billedPrice": billed,
            "supportedPrice": supported,
            "challengeAmount": amount,
            "inHouseP90": _money(challenge.get("in_house_p90_net")) or None,
            "historicalClaimsP90": _money(challenge.get("historical_claims_p90_net")) or None,
            "externalReferencePrice": _money(challenge.get("external_price_net")) or None,
            "status": challenge.get("status") or "review",
        }
        key = (repairer, item_id)
        relationship = relationships.setdefault(
            key,
            {
                "id": f"{repairer}::{item_id}",
                "repairer": repairer,
                "itemId": item_id,
                "item": item_label,
                "invoiceIds": set(),
                "challengeCount": 0,
                "totalChallenge": 0.0,
                "maximumChallenge": 0.0,
                "evidence": [],
            },
        )
        relationship["invoiceIds"].add(invoice_id)
        relationship["challengeCount"] += 1
        relationship["totalChallenge"] += amount
        relationship["maximumChallenge"] = max(relationship["maximumChallenge"], amount)
        relationship["evidence"].append(evidence)

        repairer_totals[repairer]["invoiceIds"].add(invoice_id)
        repairer_totals[repairer]["challengeCount"] += 1
        repairer_totals[repairer]["totalChallenge"] += amount
        item_totals[item_id]["label"] = item_label
        item_totals[item_id]["invoiceIds"].add(invoice_id)
        item_totals[item_id]["challengeCount"] += 1
        item_totals[item_id]["totalChallenge"] += amount

    edge_rows = []
    for row in relationships.values():
        edge_rows.append(
            {
                **row,
                "invoiceCount": len(row["invoiceIds"]),
                "invoiceIds": sorted(row["invoiceIds"]),
                "totalChallenge": round(row["totalChallenge"], 2),
                "maximumChallenge": round(row["maximumChallenge"], 2),
            }
        )
    edge_rows.sort(key=lambda row: (-row["totalChallenge"], row["repairer"], row["item"]))
    repairer_rows = sorted(
        (
            {
                "id": name,
                "name": name,
                "invoiceCount": len(values["invoiceIds"]),
                "challengeCount": values["challengeCount"],
                "totalChallenge": round(values["totalChallenge"], 2),
            }
            for name, values in repairer_totals.items()
        ),
        key=lambda row: (-row["invoiceCount"], -row["totalChallenge"], row["name"]),
    )
    item_rows = sorted(
        (
            {
                "id": item_id,
                "name": values["label"],
                "invoiceCount": len(values["invoiceIds"]),
                "challengeCount": values["challengeCount"],
                "totalChallenge": round(values["totalChallenge"], 2),
            }
            for item_id, values in item_totals.items()
        ),
        key=lambda row: (-row["invoiceCount"], -row["totalChallenge"], row["name"]),
    )
    challenged_invoice_ids = {
        invoice_id for row in edge_rows for invoice_id in row["invoiceIds"] if invoice_id
    }
    return {
        "caseReference": result.get("case", {}).get("case_reference"),
        "storage": "relational-fallback",
        "summary": {
            "mostChallengedRepairer": repairer_rows[0] if repairer_rows else None,
            "mostChallengedItem": item_rows[0] if item_rows else None,
            "challengedInvoiceCount": len(challenged_invoice_ids),
            "potentialReduction": round(sum(row["totalChallenge"] for row in edge_rows), 2),
        },
        "repairers": repairer_rows,
        "items": item_rows,
        "edges": edge_rows,
    }


def sync_to_neo4j(payload: dict[str, Any], settings: Settings) -> bool:
    """Mirror the governed projection to Neo4j when deployment credentials exist."""

    if not settings.neo4j_uri or not settings.neo4j_username or not settings.neo4j_password:
        return False
    try:
        from neo4j import GraphDatabase

        case_reference = str(payload.get("caseReference") or "")
        auth = (settings.neo4j_username, settings.neo4j_password.get_secret_value())
        with GraphDatabase.driver(settings.neo4j_uri, auth=auth) as driver:
            driver.execute_query(
                "MATCH (n {case_reference: $case_reference}) DETACH DELETE n",
                case_reference=case_reference,
                database_=settings.neo4j_database,
            )
            driver.execute_query(
                "MERGE (c:ClaimCase {case_reference: $case_reference})",
                case_reference=case_reference,
                database_=settings.neo4j_database,
            )
            for edge in payload.get("edges", []):
                driver.execute_query(
                    """
                    MATCH (c:ClaimCase {case_reference: $case_reference})
                    MERGE (r:Repairer {case_reference: $case_reference, name: $repairer})
                    MERGE (i:RepairItem {case_reference: $case_reference, item_id: $item_id})
                    SET i.name = $item_name
                    MERGE (c)-[:HAS_REPAIRER]->(r)
                    MERGE (c)-[:HAS_REPAIR_ITEM]->(i)
                    MERGE (r)-[x:CHALLENGED_FOR]->(i)
                    SET x.challenge_count = $challenge_count,
                        x.invoice_count = $invoice_count,
                        x.total_challenge = $total_challenge,
                        x.maximum_challenge = $maximum_challenge,
                        x.invoice_ids = $invoice_ids
                    """,
                    case_reference=case_reference,
                    repairer=edge["repairer"],
                    item_id=edge["itemId"],
                    item_name=edge["item"],
                    challenge_count=edge["challengeCount"],
                    invoice_count=edge["invoiceCount"],
                    total_challenge=edge["totalChallenge"],
                    maximum_challenge=edge["maximumChallenge"],
                    invoice_ids=edge["invoiceIds"],
                    database_=settings.neo4j_database,
                )
        payload["storage"] = "neo4j"
        return True
    except Exception:  # pragma: no cover - deployment fallback is deliberately defensive
        LOGGER.exception("Neo4j challenge graph sync failed; returning governed SQL projection")
        return False
