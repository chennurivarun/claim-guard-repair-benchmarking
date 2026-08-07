from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.base import LLMProviderError
from app.llm.factory import build_mapping_adjudicator, llm_configuration_status
from app.llm.gemini import GeminiStructuredLLMClient


def _client(handler: Any) -> GeminiStructuredLLMClient:
    return GeminiStructuredLLMClient(
        api_key=SecretStr("test-secret-key"),
        model_id="gemini-2.5-flash-lite",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )


def test_gemini_requests_schema_constrained_json_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models/gemini-2.5-flash-lite:generateContent")
        assert request.headers["x-goog-api-key"] == "test-secret-key"
        body = json.loads(request.content)
        assert body["generationConfig"]["temperature"] == 0
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["type"] == "object"
        assert "test-secret-key" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "selected_ontology_id": "PART-0002",
                                            "confidence": 0.96,
                                            "rationale": "Exact description match",
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    result = _client(handler).complete_json(
        system_instruction="Select a supplied candidate.",
        payload={"candidate_options": [{"ontology_id": "PART-0002"}]},
        schema={"type": "object", "properties": {}},
    )
    assert result["selected_ontology_id"] == "PART-0002"


def test_gemini_rate_limit_returns_safe_provider_error() -> None:
    client = _client(lambda request: httpx.Response(429, request=request))

    with pytest.raises(LLMProviderError) as error:
        client.complete_json(
            system_instruction="Return JSON.",
            payload={},
            schema={"type": "object"},
        )

    assert error.value.code == "LLM_RATE_LIMITED"
    assert "test-secret-key" not in str(error.value)


def test_factory_requires_key_and_builds_gemini_when_configured() -> None:
    missing = Settings(_env_file=None, llm_provider="gemini", llm_api_key=None)
    configured = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_api_key="free-tier-test-key",
    )

    assert llm_configuration_status(missing) == "configuration_required"
    assert build_mapping_adjudicator(missing) is None
    assert llm_configuration_status(configured) == "configured"
    adjudicator = build_mapping_adjudicator(configured)
    assert adjudicator is not None
    assert adjudicator.client.provider == "gemini"
