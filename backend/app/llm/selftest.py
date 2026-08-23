"""One-command AI self-test: `uv run claimguard-probe`.

Reads the SAME backend/.env the application uses - no arguments, no JSON
files, no environment variables to set. Tests the configured AI provider on
ClaimGuard's three duties and prints a plain-language verdict for each.
"""

from __future__ import annotations

import time

from app.config import BACKEND_DIR, get_settings
from app.llm.base import LLMProviderError
from app.llm.factory import _build_client, llm_configuration_status
from app.llm.invoice_extraction import MultimodalInvoiceExtractor
from app.llm.mapping import ConstrainedMappingAdjudicator, MappingCandidate

FIXTURE_PDF = (
    BACKEND_DIR.parent / "sample-data" / "auda-style" / "Auda7_full_report.pdf"
)

FAILURE_ADVICE = {
    "LLM_AUTH_ERROR": (
        "The AI service rejected the key. Check CLAIM_GUARD_LLM_API_KEY and "
        "CLAIM_GUARD_LLM_BASE_URL in backend/.env - they must match your Azure "
        "resource exactly."
    ),
    "LLM_RATE_LIMITED": (
        "The AI service is rate limited right now. Wait a minute and run this "
        "again; if it persists, ask your Azure admin to raise the deployment's "
        "request limit."
    ),
    "LLM_TIMEOUT": (
        "The AI service took too long to answer. Run this again; if it always "
        "times out, the deployment may be in a distant region or scaled to zero."
    ),
    "LLM_HTTP_ERROR": (
        "The AI endpoint answered with an error - the details below show its "
        "exact words, which usually name the misconfiguration."
    ),
    "LLM_UNAVAILABLE": (
        "The AI service could not be reached at all. Check the base URL in "
        "backend/.env and that this machine has internet access to it."
    ),
    "LLM_INVALID_RESPONSE": (
        "The AI connected but its answer was not usable. This is a model-quality "
        "issue, not a configuration issue - documents will fall back to manual "
        "review when this happens."
    ),
    "LLM_INVALID_EXTRACTION": (
        "The AI connected but its extracted data failed validation. This is a "
        "model-quality issue - affected documents fall back to manual review."
    ),
}


def _advice(code: str) -> str:
    return FAILURE_ADVICE.get(code, "Unrecognised failure; share this output with support.")


def _fixture_pages():
    import fitz

    from app.extraction.schemas import PageAnalysis, PageType

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


def _print_http_diagnostics(client) -> None:
    """On an HTTP-level failure, show the exact URL and the provider's own
    error text - that message names the misconfiguration (wrong deployment
    name, bad api-version, wrong path) far better than a status code alone."""

    url = getattr(client, "_url", None)
    api_key = getattr(client, "_api_key", None)
    if not url or not api_key:
        return
    print(f"       Requested URL: {url}")
    try:
        import httpx

        response = httpx.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "api-key": api_key,
            },
            json={
                "model": getattr(client, "model_id", ""),
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 4,
            },
            timeout=30,
        )
        body = response.text[:400].replace(api_key, "***")
        print(f"       HTTP status:   {response.status_code}")
        print(f"       Provider says: {body}")
        hints = {
            404: (
                "A 404 usually means the URL path or deployment is wrong: "
                "CLAIM_GUARD_LLM_MODEL must be EXACTLY your Azure deployment "
                "name (check Azure AI Foundry > Deployments), and the base URL "
                "must be the resource endpoint with no extra path."
            ),
            400: (
                "A 400 usually means the model/deployment name or "
                "CLAIM_GUARD_LLM_API_VERSION is wrong for this endpoint."
            ),
            401: "A 401 means the key is wrong for this resource.",
            403: "A 403 means the key lacks permission for this deployment.",
        }
        hint = hints.get(response.status_code)
        if hint:
            print(f"       Hint: {hint}")
    except Exception as diagnostic_error:  # noqa: BLE001 - diagnostics must never crash
        print(f"       (Could not reach the endpoint at all: {diagnostic_error})")


def main() -> int:
    settings = get_settings()
    status = llm_configuration_status(settings)
    print("ClaimGuard AI self-test")
    print(f"  Provider: {settings.llm_provider}")
    print(f"  Model:    {settings.llm_model}")
    print()

    if status != "configured":
        print(f"[FAIL] AI is not configured (status: {status}).")
        print(
            "       Fill in the CLAIM_GUARD_LLM_* values in backend/.env and run "
            "this again. See docs/CLIENT_MACHINE_SETUP.md section 3."
        )
        return 1

    client = _build_client(settings, model_id=settings.llm_model)

    # 1. Connectivity
    try:
        started = time.perf_counter()
        result = client.complete_json(
            system_instruction="Reply with JSON only. Set field ok to the literal string yes.",
            payload={"instruction": "connectivity check"},
            schema={
                "type": "object",
                "properties": {"ok": {"type": "string"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        )
        elapsed = time.perf_counter() - started
        if str(result.get("ok", "")).strip().lower() == "yes":
            print(f"[OK]   1. Connection - the AI answered in {elapsed:.1f}s.")
        else:
            print(f"[WARN] 1. Connection - answered in {elapsed:.1f}s but oddly: {result!r}")
    except LLMProviderError as error:
        print(f"[FAIL] 1. Connection ({error.code})")
        print(f"       {error}")
        print(f"       {_advice(error.code)}")
        if error.code in {"LLM_HTTP_ERROR", "LLM_UNAVAILABLE"}:
            _print_http_diagnostics(client)
        print("\nFix the connection first; the remaining checks need it.")
        return 1

    # 2. Mapping trap
    try:
        adjudicator = ConstrainedMappingAdjudicator(client)
        outcome = adjudicator.adjudicate(
            invoice_description="Radiator grille remove and refit",
            candidates=[
                MappingCandidate(ontology_id="item-fan-belt", canonical_name="Auxiliary drive belt"),
                MappingCandidate(
                    ontology_id="item-radiator-grille",
                    canonical_name="Radiator grille remove and refit",
                ),
                MappingCandidate(ontology_id="item-oil-filter", canonical_name="Oil filter"),
            ],
        )
        chosen = outcome.selected_ontology_id or "NO_MATCH"
        if chosen in {"item-radiator-grille", "NO_MATCH"}:
            print(f"[OK]   2. Part matching - chose sensibly ({chosen}).")
        else:
            print(
                f"[FAIL] 2. Part matching - chose the WRONG part ({chosen}). "
                "Do not rely on this model for matching."
            )
    except LLMProviderError as error:
        print(f"[FAIL] 2. Part matching ({error.code})")
        print(f"       {_advice(error.code)}")

    # 3. Document extraction
    if not FIXTURE_PDF.exists():
        print("[SKIP] 3. Document reading - test file missing (sample-data/auda-style).")
    else:
        try:
            extractor = MultimodalInvoiceExtractor(
                client, max_attempts=settings.llm_max_attempts
            )
            invoice = extractor.extract_from_text(_fixture_pages(), role_hint="invoice")
            priced = (
                [line for line in invoice.line_items if line.line_total_net]
                if invoice
                else []
            )
            if len(priced) >= 5:
                print(
                    f"[OK]   3. Document reading - extracted {len(priced)} priced "
                    "lines from the Audatex test document."
                )
            elif priced:
                print(
                    f"[WARN] 3. Document reading - only {len(priced)} priced lines "
                    "extracted (expected 15+). The model works but misses lines; "
                    "more documents will need manual review."
                )
            elif invoice is None:
                print(
                    "[WARN] 3. Document reading - the model judged the test document "
                    "'not an invoice' and returned nothing. Documents it declines "
                    "will go to manual review."
                )
            else:
                print(
                    "[WARN] 3. Document reading - the model answered but every line "
                    "was empty or unpriced. Documents it cannot read will go to "
                    "manual review."
                )
        except LLMProviderError as error:
            print(f"[FAIL] 3. Document reading ({error.code})")
            print(f"       {_advice(error.code)}")

    print()
    print("Done. Share this output when reporting AI issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
