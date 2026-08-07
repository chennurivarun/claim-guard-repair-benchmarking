"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.router import router as api_router
from app.config import get_settings
from app.database import get_db
from app.db_types import utc_now
from app.init_db import initialize_database
from app.llm.factory import llm_configuration_status
from app.schemas import HealthResponse

settings = get_settings()
DatabaseSession = Annotated[Session, Depends(get_db)]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if settings.auto_create_schema:
        initialize_database(seed_defaults=settings.seed_default_config)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


def _health_response(db: Session) -> HealthResponse:
    try:
        db.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DATABASE_UNAVAILABLE", "message": "Database check failed."},
        ) from exc
    azure_configured = bool(
        (settings.azure_document_endpoint or "").strip()
        and settings.azure_document_api_key
        and settings.azure_document_api_key.get_secret_value().strip()
    )
    ocr_status = (
        "disabled"
        if settings.document_ocr_provider == "disabled"
        else "azure_configured"
        if azure_configured
        else "configuration_required"
        if settings.document_ocr_provider == "azure"
        else "native_pdf_only"
    )
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database="ok",
        ai_provider=settings.llm_provider,
        ai_model=settings.llm_model,
        ai_status=llm_configuration_status(settings),
        ocr_provider=settings.document_ocr_provider,
        ocr_status=ocr_status,
        timestamp=utc_now(),
    )


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health(db: DatabaseSession) -> HealthResponse:
    return _health_response(db)


@app.get(
    f"{settings.api_prefix}/health",
    response_model=HealthResponse,
    tags=["system"],
    include_in_schema=False,
)
def versioned_health(db: DatabaseSession) -> HealthResponse:
    return _health_response(db)
