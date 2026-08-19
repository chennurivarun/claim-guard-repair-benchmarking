from __future__ import annotations

from typing import Literal

from app.config import Settings
from app.llm.base import StructuredLLMClient
from app.llm.gemini import GeminiStructuredLLMClient
from app.llm.invoice_extraction import MultimodalInvoiceExtractor
from app.llm.mapping import ConstrainedMappingAdjudicator
from app.llm.openai_compatible import OpenAICompatibleStructuredLLMClient


def llm_configuration_status(
    settings: Settings,
) -> Literal["disabled", "configuration_required", "configured"]:
    if settings.llm_provider == "disabled":
        return "disabled"
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        return "configuration_required"
    if not settings.llm_model.strip() or not settings.llm_base_url.strip():
        return "configuration_required"
    if settings.llm_provider != "gemini" and "generativelanguage.googleapis.com" in settings.llm_base_url:
        return "configuration_required"
    return "configured"


def _build_client(settings: Settings, *, model_id: str) -> StructuredLLMClient:
    if settings.llm_provider == "gemini":
        return GeminiStructuredLLMClient(
            api_key=settings.llm_api_key,
            model_id=model_id,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if settings.llm_provider in {"azure_openai", "openai_compatible"}:
        return OpenAICompatibleStructuredLLMClient(
            api_key=settings.llm_api_key,
            model_id=model_id,
            base_url=settings.llm_base_url,
            api_version=settings.llm_api_version,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ValueError("No enabled LLM provider is configured.")


def build_mapping_adjudicator(settings: Settings) -> ConstrainedMappingAdjudicator | None:
    """Build the optional mapping model; missing config safely means deterministic mode."""

    if llm_configuration_status(settings) != "configured":
        return None
    return ConstrainedMappingAdjudicator(
        _build_client(settings, model_id=settings.llm_model),
        max_attempts=settings.llm_max_attempts,
    )


def build_invoice_vision_extractor(settings: Settings) -> MultimodalInvoiceExtractor | None:
    """Build the opt-in fallback without changing deterministic-only deployments."""

    if not settings.llm_vision_enabled or llm_configuration_status(settings) != "configured":
        return None
    model_id = (settings.llm_vision_model or settings.llm_model).strip()
    if not model_id:
        return None
    return MultimodalInvoiceExtractor(
        _build_client(settings, model_id=model_id),
        max_pages=settings.llm_vision_max_pages,
    )
