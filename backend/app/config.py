"""Application configuration sourced from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = (BACKEND_DIR / "data" / "claim_guard.db").resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", ".env"),
        env_prefix="CLAIM_GUARD_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app_name: str = "ClaimGuard API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = f"sqlite:///{DEFAULT_DATABASE_PATH}"
    storage_dir: Path = BACKEND_DIR / "data" / "storage"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(default=100, gt=0, le=1000)
    sqlite_timeout_seconds: float = Field(default=30.0, gt=0)
    sqlite_busy_timeout_ms: int = Field(default=30_000, gt=0)
    auto_create_schema: bool = True
    seed_default_config: bool = True
    extraction_review_threshold: float = Field(default=0.90, ge=0, le=1)
    auto_accept_confidence_threshold: float = Field(default=0.95, ge=0, le=1)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    document_ocr_provider: Literal["auto", "azure", "tesseract", "disabled"] = "auto"
    azure_document_endpoint: str | None = None
    azure_document_api_key: SecretStr | None = None
    azure_document_model: str = "prebuilt-layout"
    azure_document_timeout_seconds: float = Field(default=120, gt=0, le=300)

    # Pilot defaults fixed by the v1.4 product decision log.
    two_step_approval: bool = False
    auto_research: bool = False
    research_source_allowlists: dict[str, list[str]] = {
        # Local/pilot-safe placeholder hosts. Insurers replace this versioned
        # mapping through CLAIM_GUARD_RESEARCH_SOURCE_ALLOWLISTS.
        "pilot-manual-sources-v1": ["*.example.test"],
    }
    default_currency: str = "GBP"
    default_jurisdiction: str = "UK"

    # Mapping remains deterministic-first. Vision extraction is separately gated and
    # its output always passes through the existing schemas and arithmetic checks.
    llm_provider: Literal["disabled", "gemini", "azure_openai", "openai_compatible"] = (
        "gemini"
    )
    llm_model: str = "gemini-2.5-flash-lite"
    llm_vision_model: str | None = None
    llm_vision_enabled: bool = False
    llm_vision_max_pages: int = Field(default=8, ge=1, le=20)
    llm_vision_max_batches: int = Field(default=3, ge=1, le=10)
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    llm_api_version: str = "2024-10-21"
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_attempts: int = Field(default=2, ge=1, le=3)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
