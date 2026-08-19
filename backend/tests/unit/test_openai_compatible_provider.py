from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.base import LLMProviderError
from app.llm.factory import build_invoice_vision_extractor, build_mapping_adjudicator
from app.llm.openai_compatible import OpenAICompatibleStructuredLLMClient


def _client(handler) -> OpenAICompatibleStructuredLLMClient:
    return OpenAICompatibleStructuredLLMClient(
        api_key=SecretStr("rotated-test-key"),
        model_id="vision-deployment",
        base_url="https://example.services.ai.azure.com",
        api_version="2024-05-01-preview",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )


def test_azure_ai_request_supports_images_and_schema_without_leaking_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/models/chat/completions"
        assert request.url.params["api-version"] == "2024-05-01-preview"
        assert request.headers["api-key"] == "rotated-test-key"
        body = json.loads(request.content)
        assert body["model"] == "vision-deployment"
        assert body["response_format"]["type"] == "json_schema"
        assert body["messages"][1]["content"][1]["type"] == "image_url"
        assert "rotated-test-key" not in request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"document_role":"other"}'}}]},
        )

    result = _client(handler).complete_json(
        system_instruction="Return visible values only.",
        payload={"page_number": 1},
        schema={"type": "object"},
        image_data_urls=["data:image/jpeg;base64,ZmFrZQ=="],
    )
    assert result == {"document_role": "other"}


def test_provider_auth_failure_is_safe() -> None:
    client = _client(lambda request: httpx.Response(401, request=request))
    with pytest.raises(LLMProviderError) as error:
        client.complete_json(
            system_instruction="Return JSON.", payload={}, schema={"type": "object"}
        )
    assert error.value.code == "LLM_AUTH_ERROR"
    assert "rotated-test-key" not in str(error.value)


def test_json_schema_unsupported_retries_in_json_object_mode() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        attempts.append(body["response_format"]["type"])
        if len(attempts) == 1:
            return httpx.Response(400, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    assert _client(handler).complete_json(
        system_instruction="Return JSON.", payload={}, schema={"type": "object"}
    ) == {}
    assert attempts == ["json_schema", "json_object"]


def test_factory_reuses_azure_client_for_mapping_and_opt_in_vision() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="azure_openai",
        llm_model="text-deployment",
        llm_vision_model="vision-deployment",
        llm_vision_enabled=True,
        llm_api_key="rotated-test-key",
        llm_base_url="https://example.services.ai.azure.com",
    )
    mapping = build_mapping_adjudicator(settings)
    vision = build_invoice_vision_extractor(settings)
    assert mapping is not None
    assert mapping.client.provider == "azure_openai"
    assert mapping.client.model_id == "text-deployment"
    assert vision is not None
    assert vision.client.model_id == "vision-deployment"


def test_vision_stays_disabled_unless_explicitly_enabled() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="azure_openai",
        llm_model="vision-deployment",
        llm_api_key="rotated-test-key",
        llm_base_url="https://example.services.ai.azure.com",
    )
    assert build_invoice_vision_extractor(settings) is None


def test_bare_azure_openai_endpoint_inserts_deployment_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == (
            "/openai/deployments/vision-deployment/chat/completions"
        )
        assert request.url.params["api-version"] == "2024-10-21"
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = OpenAICompatibleStructuredLLMClient(
        api_key="rotated-test-key",
        model_id="vision-deployment",
        base_url="https://example.openai.azure.com",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )
    assert client.complete_json(
        system_instruction="Return JSON.", payload={}, schema={"type": "object"}
    ) == {}
