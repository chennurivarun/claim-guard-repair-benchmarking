"""The documented clean install: reference library in, demo corpus out.

Cloning the repo and following ``RUN_ME.md`` used to rebuild the demo case
``CG-2026-0048`` -- its fabricated claim context, its four demo parties, its two
demo vehicles and a processed demo invoice -- because ``claimguard-bootstrap``
was simultaneously the only documented way to import the reference banks and the
builder of the demo. Skipping the step was not an option either: without the
banks, ``POST /claims/{ref}/compare`` refuses with "the ontology bank is empty".

So these tests do what a new user does. They run the documented command in a
subprocess, against a throwaway database named by ``CLAIM_GUARD_DATABASE_URL``,
and assert against the SQLite file it leaves behind -- not against in-process
objects, which would not catch the command itself changing.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
SAMPLE_DATA = BACKEND_DIR.parent / "sample-data"

DEMO_CASE_REFERENCE = "CG-2026-0048"
CLEAN_CASE_REFERENCE = "CG-CLIENT-001"

# What the supplied workbooks actually yield. The 623 historical rows a demo
# bootstrap leaves behind are 191 seed rows plus 432 minted from the demo
# invoice during comparison -- case-derived data the clean install must not have.
EXPECTED_ONTOLOGY_ITEMS = 72
EXPECTED_HISTORICAL_OBSERVATIONS = 191
EXPECTED_PRICE_OBSERVATIONS = 65

# Tables that must be empty on a clean install: every one of them is
# case-scoped, and every one of them was populated by the old documented path.
CASE_SCOPED_TABLES = (
    "documents",
    "invoices",
    "invoice_line_items",
    "challenge_results",
    "claim_vehicles",
    "claim_parties",
    "liability_assessments",
    "vehicles",
    "price_comparisons",
    "processing_runs",
)

_RUNNER = "import sys; from app.bootstrap import setup_main; sys.exit(setup_main(sys.argv[1:]))"


@pytest.fixture(autouse=True)
def _require_sample_data() -> None:
    for name in ("ontology_seed.xlsx", "historical_claims_seed.xlsx"):
        if not (SAMPLE_DATA / name).is_file():
            pytest.skip("Supplied seed workbooks are not available")


def _run_setup(tmp_path: Path, *args: str) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """Run ``claimguard-setup`` the way the instructions tell a user to run it."""

    database = tmp_path / "clean_install.db"
    environment = {
        **os.environ,
        "CLAIM_GUARD_DATABASE_URL": f"sqlite:///{database}",
        "CLAIM_GUARD_STORAGE_DIR": str(tmp_path / "storage"),
        # Nothing here processes a document, but an inherited key must never
        # turn a test run into a network call.
        "CLAIM_GUARD_LLM_PROVIDER": "disabled",
        "CLAIM_GUARD_LLM_API_KEY": "",
    }
    completed = subprocess.run(
        [sys.executable, "-c", _RUNNER, *args],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # If the environment override were ignored the command would have written to
    # the checked-in database instead, and this file would not exist.
    assert database.is_file(), completed.stdout
    return database, completed


def _counts(database: Path, tables: tuple[str, ...]) -> dict[str, int]:
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }


def _case_references(database: Path) -> list[str]:
    with sqlite3.connect(database) as connection:
        return [row[0] for row in connection.execute("SELECT case_reference FROM cases")]


def test_documented_setup_builds_the_reference_library_without_the_demo_corpus(
    tmp_path: Path,
) -> None:
    database, completed = _run_setup(tmp_path)

    assert _case_references(database) == [CLEAN_CASE_REFERENCE]
    assert DEMO_CASE_REFERENCE not in completed.stdout

    empty = _counts(database, CASE_SCOPED_TABLES)
    assert empty == dict.fromkeys(CASE_SCOPED_TABLES, 0)

    # The one row beyond ``cases``: the liability gate lives on the context, so
    # an empty case cannot exist without one. It carries no invented identity.
    with sqlite3.connect(database) as connection:
        contexts = connection.execute(
            "SELECT claim_number, liability_gate_status, human_confirmed, "
            "paying_insurer_name, third_party_name FROM claim_contexts"
        ).fetchall()
        status = connection.execute("SELECT status FROM cases").fetchone()[0]
    assert contexts == [(CLEAN_CASE_REFERENCE, "awaiting_human_review", 0, None, None)]
    assert status == "claim_review"

    # The banks ``POST /claims/{ref}/compare`` counts before it will run.
    banks = _counts(
        database, ("ontology_items", "historical_observations", "price_observations")
    )
    assert banks == {
        "ontology_items": EXPECTED_ONTOLOGY_ITEMS,
        "historical_observations": EXPECTED_HISTORICAL_OBSERVATIONS,
        "price_observations": EXPECTED_PRICE_OBSERVATIONS,
    }
    assert banks["ontology_items"] > 0 and banks["historical_observations"] > 0


def test_running_the_documented_setup_twice_changes_nothing(tmp_path: Path) -> None:
    """A user who re-runs step 1 must not end up with a second case or double banks."""

    database, _ = _run_setup(tmp_path)
    tracked = CASE_SCOPED_TABLES + (
        "cases",
        "claim_contexts",
        "ontology_items",
        "historical_observations",
        "price_observations",
    )
    before = _counts(database, tracked)

    _run_setup(tmp_path)

    assert _counts(database, tracked) == before
    assert _case_references(database) == [CLEAN_CASE_REFERENCE]


def test_seeds_only_creates_no_case_at_all(tmp_path: Path) -> None:
    database, _ = _run_setup(tmp_path, "--no-case")

    assert _case_references(database) == []
    empty = _counts(database, CASE_SCOPED_TABLES + ("cases", "claim_contexts"))
    assert empty == dict.fromkeys(CASE_SCOPED_TABLES + ("cases", "claim_contexts"), 0)

    banks = _counts(database, ("ontology_items", "historical_observations"))
    assert banks["ontology_items"] == EXPECTED_ONTOLOGY_ITEMS
    assert banks["historical_observations"] == EXPECTED_HISTORICAL_OBSERVATIONS


def test_a_chosen_case_reference_is_the_only_case(tmp_path: Path) -> None:
    database, _ = _run_setup(tmp_path, "--case-reference", "CG-HANDOVER-7")

    assert _case_references(database) == ["CG-HANDOVER-7"]
    assert _counts(database, ("claim_contexts",))["claim_contexts"] == 1
    # Renaming the demo case is not the same as not building it: the chosen
    # reference must be an empty case, not the demo corpus under a new label.
    assert _counts(database, CASE_SCOPED_TABLES) == dict.fromkeys(CASE_SCOPED_TABLES, 0)
