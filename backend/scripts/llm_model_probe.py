"""Compare LLM models on ClaimGuard's three AI duties, side by side.

Runs each configured model through: (1) a structured-output connectivity check,
(2) a mapping adjudication that must NOT pick the wrong part (the fan-belt
trap), and (3) text extraction of the Audatex-style full-report fixture.
Prints a comparison table. Nothing here touches the database or the app config.

Usage (from backend/):
    uv run python scripts/llm_model_probe.py --models scripts/probe_models.example.json

Model file format — a JSON list; keys come from environment variables so
secrets never live in the file:
    [
      {"name": "gemini-flash-lite", "provider": "gemini",
       "model": "gemini-2.5-flash-lite", "api_key_env": "GEMINI_API_KEY"},
      {"name": "openrouter-free-alpha", "provider": "openai_compatible",
       "model": "openrouter/some-alpha-model", "api_key_env": "OPENROUTER_API_KEY",
       "base_url": "https://openrouter.ai/api/v1"}
    ]

Data note: probes send only the synthetic fixture text below and in
sample-data/auda-style/. Never point this at real claim documents when testing
third-party or free-tier models.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import fitz  # noqa: E402

from app.extraction.schemas import PageAnalysis, PageType  # noqa: E402
from app.llm.base import LLMProviderError, StructuredLLMClient  # noqa: E402
from app.llm.gemini import GeminiStructuredLLMClient  # noqa: E402
from app.llm.invoice_extraction import MultimodalInvoiceExtractor  # noqa: E402
from app.llm.mapping import ConstrainedMappingAdjudicator, MappingCandidate  # noqa: E402
from app.llm.openai_compatible import OpenAICompatibleStructuredLLMClient  # noqa: E402

FIXTURE_PDF = BACKEND_DIR.parent / "sample-data" / "auda-style" / "Auda7_full_report.pdf"

MAPPING_TRAP = {
    "description": "Radiator grille remove and refit",
    "candidates": [
        MappingCandidate(ontology_id="item-fan-belt", canonical_name="Auxiliary drive belt"),
        MappingCandidate(
            ontology_id="item-radiator-grille",
            canonical_name="Radiator grille remove and refit",
        ),
        MappingCandidate(ontology_id="item-oil-filter", canonical_name="Oil filter"),
    ],
    "correct": "item-radiator-grille",
}


def build_client(entry: dict) -> StructuredLLMClient:
    key_env = entry.get("api_key_env", "")
    api_key = os.environ.get(key_env, "") if key_env else entry.get("api_key", "")
    if not api_key:
        raise ValueError(f"No API key: set {key_env or 'api_key'} for '{entry['name']}'.")
    timeout = float(entry.get("timeout_seconds", 60))
    if entry["provider"] == "gemini":
        return GeminiStructuredLLMClient(
            api_key=api_key, model_id=entry["model"], timeout_seconds=timeout
        )
    if entry["provider"] in {"openai_compatible", "azure_openai"}:
        default_base = (
            "" if entry["provider"] == "azure_openai" else "https://openrouter.ai/api/v1"
        )
        base_url = entry.get("base_url", default_base)
        if not base_url:
            raise ValueError(f"'{entry['name']}' needs base_url for {entry['provider']}.")
        return OpenAICompatibleStructuredLLMClient(
            api_key=api_key,
            model_id=entry["model"],
            base_url=base_url,
            api_version=entry.get("api_version", "2024-05-01-preview"),
            timeout_seconds=timeout,
        )
    raise ValueError(f"Unknown provider '{entry['provider']}' for '{entry['name']}'.")


def probe_connectivity(client: StructuredLLMClient) -> float:
    started = time.perf_counter()
    result = client.complete_json(
        system_instruction=(
            "Reply with JSON only. Set field ok to the literal string yes."
        ),
        payload={"instruction": "connectivity check"},
        schema={
            "type": "object",
            "properties": {"ok": {"type": "string"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    )
    elapsed = time.perf_counter() - started
    if str(result.get("ok", "")).strip().lower() != "yes":
        raise LLMProviderError("LLM_INVALID_RESPONSE", f"Unexpected reply: {result!r}")
    return elapsed


def probe_mapping(client: StructuredLLMClient) -> tuple[str, bool]:
    adjudicator = ConstrainedMappingAdjudicator(client)
    outcome = adjudicator.adjudicate(
        invoice_description=MAPPING_TRAP["description"],
        candidates=MAPPING_TRAP["candidates"],
    )
    chosen = outcome.selected_ontology_id or "NO_MATCH"
    acceptable = chosen in {MAPPING_TRAP["correct"], "NO_MATCH"}
    return chosen, acceptable


def fixture_pages() -> list[PageAnalysis]:
    document = fitz.open(FIXTURE_PDF)
    pages = []
    for index, page in enumerate(document, start=1):
        text = page.get_text("text")
        pages.append(
            PageAnalysis(
                page_number=index,
                width=page.rect.width,
                height=page.rect.height,
                rotation=0,
                native_character_count=len(text),
                positioned_word_count=len(text.split()),
                image_count=0,
                extraction_method="native",
                extraction_confidence=0.95,
                text=text,
                page_type=PageType.INVOICE,
                classification_confidence=0.9,
            )
        )
    document.close()
    return pages


def probe_extraction(client: StructuredLLMClient) -> tuple[int, str]:
    extractor = MultimodalInvoiceExtractor(client)
    invoice = extractor.extract_from_text(fixture_pages(), role_hint="invoice")
    if invoice is None:
        return 0, "no invoice returned"
    priced = [line for line in invoice.line_items if line.line_total_net]
    sample = priced[0].raw_description[:40] if priced else "-"
    return len(priced), sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="Path to the models JSON file")
    parser.add_argument(
        "--skip-extraction", action="store_true", help="Run only connectivity + mapping"
    )
    arguments = parser.parse_args()
    entries = json.loads(Path(arguments.models).read_text())

    rows = []
    for entry in entries:
        name = entry.get("name", entry.get("model", "?"))
        row = {"model": name, "connect": "-", "mapping": "-", "lines": "-", "note": ""}
        try:
            client = build_client(entry)
            row["connect"] = f"{probe_connectivity(client):.1f}s"
            chosen, acceptable = probe_mapping(client)
            row["mapping"] = f"{chosen} {'OK' if acceptable else 'WRONG-PART'}"
            if not arguments.skip_extraction:
                count, sample = probe_extraction(client)
                row["lines"] = str(count)
                row["note"] = sample
        except (LLMProviderError, ValueError) as error:
            row["note"] = str(error)[:70]
        rows.append(row)
        print(
            f"{row['model'][:28]:28} connect={row['connect']:>7} "
            f"mapping={row['mapping']:<32} lines={row['lines']:>3}  {row['note']}"
        )

    failures = [r for r in rows if "WRONG-PART" in r["mapping"]]
    print(
        f"\n{len(rows)} model(s) probed. "
        f"{len(failures)} picked the wrong part — do not use those for mapping."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
