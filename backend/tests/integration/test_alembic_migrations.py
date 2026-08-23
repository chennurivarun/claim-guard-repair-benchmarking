from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("CLAIM_GUARD_DATABASE_URL", database_url)
    get_settings.cache_clear()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_upgrade_head_creates_review_briefing_column(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    database_url = alembic_config.get_main_option("sqlalchemy.url")
    engine = sa.create_engine(database_url)
    try:
        columns = {column["name"] for column in sa.inspect(engine).get_columns("documents")}
        assert "review_briefing_json" in columns
    finally:
        engine.dispose()
        get_settings.cache_clear()
