from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import SecretStr

from app.llm.base import LLMProviderError


class GeminiStructuredLLMClient:
    """Small Gemini REST adapter with JSON-schema constrained output."""

    provider = "gemini"

    def __init__(
        self,
        *,
        api_key: SecretStr | str,
        model_id: str,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = (
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        ).strip()
        if not self._api_key:
            raise ValueError("Gemini API key must not be empty.")
        self.model_id = model_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
        )

    def complete_json(
        self,
        *,
        system_instruction: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        request_body = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                payload,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        try:
            response = self._client.post(
                f"/models/{self.model_id}:generateContent",
                json=request_body,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMProviderError("LLM_TIMEOUT", "Gemini request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            code = "LLM_RATE_LIMITED" if exc.response.status_code == 429 else "LLM_HTTP_ERROR"
            raise LLMProviderError(
                code,
                f"Gemini returned HTTP {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError("LLM_UNAVAILABLE", "Gemini is unavailable.") from exc

        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts).strip()
            if text.startswith("```"):
                text = text.removeprefix("```json").removeprefix("```")
                text = text.removesuffix("```").strip()
            result = json.loads(text)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE",
                "Gemini returned no valid structured response.",
            ) from exc
        if not isinstance(result, dict):
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE",
                "Gemini structured response was not an object.",
            )
        return result
