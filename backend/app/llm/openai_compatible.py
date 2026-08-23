from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import SecretStr

from app.llm.base import LLMProviderError


def _completion_url(base_url: str, model_id: str, api_version: str) -> str:
    """Accept a full chat URL, an OpenAI base URL, or either Azure endpoint style."""

    value = base_url.rstrip("/")
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        target_path = path
    elif "/openai/deployments/" in path:
        target_path = f"{path}/chat/completions"
    elif path.endswith("/openai/v1"):
        target_path = f"{path}/chat/completions"
    elif parsed.hostname and parsed.hostname.endswith(".openai.azure.com"):
        deployment = quote(model_id, safe="")
        target_path = f"{path}/openai/deployments/{deployment}/chat/completions"
    elif parsed.hostname and parsed.hostname.endswith(".services.ai.azure.com"):
        target_path = (
            f"{path}/chat/completions"
            if path.endswith("/models")
            else f"{path}/models/chat/completions"
        )
    else:
        target_path = f"{path}/chat/completions"

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if (
        (parsed.hostname or "").endswith(".azure.com")
        or "/openai/deployments/" in target_path
    ) and api_version:
        query.setdefault("api-version", api_version)
    return urlunsplit((parsed.scheme, parsed.netloc, target_path, urlencode(query), ""))


def _first_json_object(text: str):
    """Parse the leading JSON value, tolerating trailing chatter some models append.

    Content safety is unaffected: every response is still schema-validated locally.
    """

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise
        value, _ = json.JSONDecoder().raw_decode(text, start)
        return value


class OpenAICompatibleStructuredLLMClient:
    """Schema-constrained adapter for Azure AI, Azure OpenAI and OpenAI-compatible APIs."""

    provider = "azure_openai"

    def __init__(
        self,
        *,
        api_key: SecretStr | str,
        model_id: str,
        base_url: str,
        timeout_seconds: float,
        api_version: str = "2024-10-21",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self._api_key = key.strip()
        if not self._api_key:
            raise ValueError("LLM API key must not be empty.")
        if not base_url.strip():
            raise ValueError("LLM base URL must not be empty.")
        self.model_id = model_id.strip()
        if not self.model_id:
            raise ValueError("LLM model/deployment must not be empty.")
        self._url = _completion_url(base_url.strip(), self.model_id, api_version.strip())
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def complete_json(
        self,
        *,
        system_instruction: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        image_data_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            }
        ]
        content.extend(
            {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}}
            for image_url in image_data_urls or []
        )
        # Some compatible gateways accept response_format but do not enforce it for
        # every model, so the schema is also stated in the instruction itself.
        schema_instruction = (
            f"{system_instruction}\n\n"
            "Reply with exactly one JSON object and nothing else. It must validate "
            "against this JSON Schema — use only the properties it defines, all "
            "required properties, and no extra keys:\n"
            f"{json.dumps(schema, separators=(',', ':'))}"
        )
        body = {
            "model": self.model_id,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": schema_instruction},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "claimguard_structured_result",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        response = self._post(body)
        # Some compatible endpoints support JSON mode but not json_schema. Validation
        # still happens locally, so retry without weakening the application boundary.
        if response.status_code == 400:
            body["response_format"] = {"type": "json_object"}
            response = self._post(body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            code = (
                "LLM_AUTH_ERROR"
                if status in {401, 403}
                else "LLM_RATE_LIMITED"
                if status == 429
                else "LLM_HTTP_ERROR"
            )
            raise LLMProviderError(code, f"LLM provider returned HTTP {status}.") from exc

        try:
            message = response.json()["choices"][0]["message"]
            raw_content = message["content"]
            if isinstance(raw_content, list):
                raw_content = "".join(
                    part.get("text", "") for part in raw_content if isinstance(part, dict)
                )
            text = str(raw_content).strip()
            if text.startswith("```"):
                text = text.removeprefix("```json").removeprefix("```")
                text = text.removesuffix("```").strip()
            result = _first_json_object(text)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE", "LLM provider returned no valid structured response."
            ) from exc
        if not isinstance(result, dict):
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE", "LLM structured response was not an object."
            )
        return result

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(
                self._url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                    "api-key": self._api_key,
                },
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderError("LLM_TIMEOUT", "LLM request timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("LLM_UNAVAILABLE", "LLM provider is unavailable.") from exc
