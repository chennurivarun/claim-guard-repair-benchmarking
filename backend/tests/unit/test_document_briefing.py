from __future__ import annotations

from typing import Any

from app.config import Settings
from app.llm.base import LLMProviderError
from app.llm.document_briefing import (
    DocumentBriefingPage,
    build_document_briefing,
    build_document_briefing_generator,
    build_fallback_briefing,
)


class StubClient:
    provider = "stub"
    model_id = "stub-v1"

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _pages() -> list[DocumentBriefingPage]:
    return [
        DocumentBriefingPage(
            page_number=1,
            page_type="invoice",
            text="Repair invoice for AB12 CDE, contact test@example.com, total rolled up.",
            classification_confidence=0.55,
        ),
        DocumentBriefingPage(
            page_number=2,
            page_type="photo",
            text="Photograph of vehicle damage.",
            classification_confidence=0.91,
        ),
    ]


def _valid_response() -> dict[str, Any]:
    return {
        "document_summary": "A rolled-up repair invoice with a damage photo attached.",
        "content_found": ["1 invoice page", "1 damage photo"],
        "why_manual_review": "The invoice totals are rolled up with no priced part lines.",
        "recommended_action": "Enter the billable lines by hand from the invoice page.",
    }


def test_generate_redacts_pii_and_flags_injection_before_calling_the_model() -> None:
    client = StubClient([_valid_response()])
    from app.llm.document_briefing import DocumentBriefingGenerator

    generator = DocumentBriefingGenerator(client)
    briefing, meta = generator.generate(
        pages=_pages(), manual_review_reason="No benchmarkable lines were found."
    )
    assert briefing.document_summary == _valid_response()["document_summary"]
    assert len(client.calls) == 1
    payload = client.calls[0]["payload"]
    assert "test@example.com" not in payload["untrusted_document_text"]
    assert "REDACTED_EMAIL" in payload["untrusted_document_text"]
    assert payload["redaction_counts"].get("EMAIL") == 1
    assert meta["redaction_counts"].get("EMAIL") == 1


def test_llm_failure_falls_back_to_deterministic_briefing() -> None:
    client = StubClient([LLMProviderError("LLM_TIMEOUT", "boom")])
    generator = build_document_briefing_generator_with_stub(client)
    result = build_document_briefing(
        generator,
        pages=_pages(),
        manual_review_reason="No benchmarkable invoice line items were detected.",
    )
    assert result["fallback"] is True
    assert result["model"] == "fallback"
    assert "No benchmarkable invoice line items were detected." in result["why_manual_review"]
    assert result["content_found"]
    assert len(client.calls) == 1


def test_no_generator_configured_uses_fallback_and_never_raises() -> None:
    result = build_document_briefing(
        None,
        pages=_pages(),
        manual_review_reason="No benchmarkable invoice line items were detected.",
    )
    assert result["fallback"] is True
    assert result["prompt_version"]
    assert result["generated_at"]


def test_successful_generation_is_not_marked_fallback() -> None:
    client = StubClient([_valid_response()])
    generator = build_document_briefing_generator_with_stub(client)
    result = build_document_briefing(
        generator, pages=_pages(), manual_review_reason="No benchmarkable lines."
    )
    assert result["fallback"] is False
    assert result["model"] == "stub:stub-v1"
    assert result["document_summary"] == _valid_response()["document_summary"]


def test_invalid_schema_response_retries_then_falls_back() -> None:
    client = StubClient([{"document_summary": ""}, {"document_summary": ""}])
    generator = build_document_briefing_generator_with_stub(client, max_attempts=2)
    result = build_document_briefing(
        generator, pages=_pages(), manual_review_reason="No benchmarkable lines."
    )
    assert result["fallback"] is True
    assert len(client.calls) == 2


def test_fallback_briefing_summarises_page_classification_counts() -> None:
    briefing = build_fallback_briefing(
        manual_review_reason="No benchmarkable invoice line items were detected.",
        pages=_pages(),
    )
    assert "invoice" in " ".join(briefing.content_found)
    assert "photo" in " ".join(briefing.content_found)
    assert briefing.why_manual_review == "No benchmarkable invoice line items were detected."


def test_factory_returns_none_when_briefing_disabled() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_api_key="secret",
        llm_briefing_enabled=False,
    )
    assert build_document_briefing_generator(settings) is None


def test_factory_returns_none_when_llm_not_configured() -> None:
    settings = Settings(_env_file=None, llm_provider="disabled")
    assert build_document_briefing_generator(settings) is None


def test_factory_builds_generator_when_configured() -> None:
    settings = Settings(_env_file=None, llm_provider="gemini", llm_api_key="secret")
    generator = build_document_briefing_generator(settings)
    assert generator is not None
    assert generator.max_attempts == settings.llm_max_attempts


def build_document_briefing_generator_with_stub(client: StubClient, *, max_attempts: int = 2):
    from app.llm.document_briefing import DocumentBriefingGenerator

    return DocumentBriefingGenerator(client, max_attempts=max_attempts)
