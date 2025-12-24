"""
Isolated database utilities for debugging/scripts/tests.

This module provides an async context manager that:
- Creates an isolated SQLite database file (by default under /tmp)
- Forces Lyra to use it via environment variable override
- Clears cached settings and resets the global DB singleton
- Cleans up the database file on exit (best-effort, even on exceptions)

Use this when you want reproducible DB behavior without touching data/lyra.db.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path


@asynccontextmanager
async def isolated_database_path(
    *,
    directory: str | Path | None = None,
    filename: str = "lyra_isolated.db",
    set_env: bool = True,
) -> AsyncIterator[Path]:
    """
    Create an isolated SQLite database file and clean it up automatically.

    This is designed for scripts/debug flows that need a fresh schema without
    mutating the main development DB.

    Args:
        directory: Parent directory for the DB file. If None, a temp directory is used.
        filename: DB filename within the directory.
        set_env: When True, sets LYRA_STORAGE__DATABASE_PATH to the isolated path.

    Yields:
        Path to the isolated SQLite DB file.
    """
    from src.storage.database import close_database
    from src.utils import config as config_module

    prev_db_path = os.environ.get("LYRA_STORAGE__DATABASE_PATH")

    if directory is None:
        tmpdir_obj = tempfile.TemporaryDirectory(prefix="lyra_isolated_db_")
        base_dir = Path(tmpdir_obj.name)
    else:
        tmpdir_obj = None
        base_dir = Path(directory)
        base_dir.mkdir(parents=True, exist_ok=True)

    db_path = base_dir / filename

    # Ensure we start from a clean file
    db_path.unlink(missing_ok=True)

    try:
        if set_env:
            os.environ["LYRA_STORAGE__DATABASE_PATH"] = str(db_path)

        # Clear cached settings so the env override is picked up.
        config_module.get_settings.cache_clear()

        # Reset/close any global DB singleton that might have been initialized.
        await close_database()

        yield db_path
    finally:
        # Close DB again (best effort) before deleting file.
        try:
            await close_database()
        except Exception:
            pass

        # Restore env var
        if set_env:
            if prev_db_path is None:
                os.environ.pop("LYRA_STORAGE__DATABASE_PATH", None)
            else:
                os.environ["LYRA_STORAGE__DATABASE_PATH"] = prev_db_path

        # Clear settings cache again for subsequent code.
        try:
            config_module.get_settings.cache_clear()
        except Exception:
            pass

        # Remove file and tempdir if we created them
        try:
            db_path.unlink(missing_ok=True)
        except Exception:
            pass
        if tmpdir_obj is not None:
            try:
                tmpdir_obj.cleanup()
            except Exception:
                pass
