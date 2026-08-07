"""Consistent SQLite online-backup helper."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile


def backup_sqlite(source_path: str | Path, output_path: str | Path) -> Path:
    """Create an atomic, transaction-consistent SQLite backup.

    The SQLite backup API includes committed WAL content and avoids copying a
    live database file byte-for-byte.  The resulting database is integrity
    checked before it replaces the destination.
    """

    source = Path(source_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source}")
    if source == destination:
        raise ValueError("SQLite backup destination must differ from the source")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile(
        prefix=f".{destination.stem}-", suffix=".sqlite3", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        source_uri = f"file:{source.as_posix()}?mode=ro"
        with sqlite3.connect(source_uri, uri=True) as source_connection:
            with sqlite3.connect(temporary) as destination_connection:
                source_connection.backup(destination_connection)
                destination_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
                if not integrity or str(integrity[0]).lower() != "ok":
                    raise sqlite3.DatabaseError(
                        f"SQLite backup integrity check failed: {integrity!r}"
                    )
                destination_connection.commit()
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
