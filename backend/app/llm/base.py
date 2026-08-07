from __future__ import annotations

from typing import Any, Protocol


class LLMProviderError(RuntimeError):
    """Safe provider failure that can be recorded without exposing response bodies or keys."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StructuredLLMClient(Protocol):
    """Minimal provider contract; implementations must request JSON-schema output."""

    provider: str
    model_id: str

    def complete_json(
        self,
        *,
        system_instruction: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]: ...


class DisabledLLMClient:
    provider = "disabled"
    model_id = "none"

    def complete_json(
        self,
        *,
        system_instruction: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        raise LLMProviderError(
            "LLM_DISABLED",
            "No LLM provider is configured; deterministic mapping remains active.",
        )
