from __future__ import annotations

from typing import Literal

from app.config import Settings
from app.llm.gemini import GeminiStructuredLLMClient
from app.llm.mapping import ConstrainedMappingAdjudicator


def llm_configuration_status(
    settings: Settings,
) -> Literal["disabled", "configuration_required", "configured"]:
    if settings.llm_provider == "disabled":
        return "disabled"
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        return "configuration_required"
    return "configured"


def build_mapping_adjudicator(settings: Settings) -> ConstrainedMappingAdjudicator | None:
    """Build the optional mapping model; missing config safely means deterministic mode."""

    if llm_configuration_status(settings) != "configured":
        return None
    if settings.llm_provider == "gemini":
        return ConstrainedMappingAdjudicator(
            GeminiStructuredLLMClient(
                api_key=settings.llm_api_key,
                model_id=settings.llm_model,
                base_url=settings.llm_base_url,
                timeout_seconds=settings.llm_timeout_seconds,
            ),
            max_attempts=settings.llm_max_attempts,
        )
    return None
