"""
Tests for isolated DB utilities.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|--------------------------------------|-----------------|-------|
| TC-ISO-N-01 | No existing env override | Equivalence – normal | isolated_database_path sets env + creates usable DB + cleans up | Positive |
| TC-ISO-A-01 | Pre-existing env override present | Equivalence – negative | Env is restored after context | Negative (wiring/cleanup) |
| TC-ISO-A-02 | Exception inside context | Equivalence – negative | DB file is removed and env restored | Negative (finally path) |
| TC-ISO-B-01 | directory specified (tmp_path) | Boundary – empty/isolated dir | Uses provided dir and cleans up file | Boundary: directory override |
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.unit
class TestIsolatedDatabasePath:
    @pytest.mark.asyncio
    async def test_isolated_database_path_sets_env_and_cleans_up(self) -> None:
        """
        TC-ISO-N-01: isolated_database_path sets env and cleans up.

        // Given: No existing LYRA_STORAGE__DATABASE_PATH override
        // When:  Using isolated_database_path and initializing DB
        // Then:  Env points to isolated path inside context, and file is removed after
        """
        from src.storage.database import get_database
        from src.storage.isolation import isolated_database_path

        os.environ.pop("LYRA_STORAGE__DATABASE_PATH", None)

        isolated_path: Path | None = None

        async with isolated_database_path() as db_path:
            isolated_path = db_path
            assert os.environ.get("LYRA_STORAGE__DATABASE_PATH") == str(db_path)

            # Initialize schema by opening DB once.
            db = await get_database()
            assert db.db_path == db_path

        assert isolated_path is not None
        assert not isolated_path.exists()
        assert "LYRA_STORAGE__DATABASE_PATH" not in os.environ

    @pytest.mark.asyncio
    async def test_isolated_database_path_restores_previous_env(self) -> None:
        """
        TC-ISO-A-01: isolated_database_path restores env on exit.

        // Given: LYRA_STORAGE__DATABASE_PATH is already set
        // When:  Using isolated_database_path
        // Then:  The original env value is restored after context
        """
        from src.storage.isolation import isolated_database_path

        os.environ["LYRA_STORAGE__DATABASE_PATH"] = "/tmp/prev_lyra.db"

        async with isolated_database_path():
            assert os.environ.get("LYRA_STORAGE__DATABASE_PATH") != "/tmp/prev_lyra.db"

        assert os.environ.get("LYRA_STORAGE__DATABASE_PATH") == "/tmp/prev_lyra.db"

    @pytest.mark.asyncio
    async def test_isolated_database_path_cleans_up_on_exception(self) -> None:
        """
        TC-ISO-A-02: cleanup runs even if an exception happens.

        // Given: A block that raises an exception
        // When:  Running within isolated_database_path
        // Then:  DB file is removed and env is restored
        """
        from src.storage.isolation import isolated_database_path

        os.environ.pop("LYRA_STORAGE__DATABASE_PATH", None)

        isolated_path: Path | None = None

        with pytest.raises(ValueError, match="boom"):
            async with isolated_database_path() as db_path:
                isolated_path = db_path
                assert os.environ.get("LYRA_STORAGE__DATABASE_PATH") == str(db_path)
                raise ValueError("boom")

        assert isolated_path is not None
        assert not isolated_path.exists()
        assert "LYRA_STORAGE__DATABASE_PATH" not in os.environ

    @pytest.mark.asyncio
    async def test_isolated_database_path_with_directory_override(self, tmp_path: Path) -> None:
        """
        TC-ISO-B-01: directory override uses provided dir and cleans up file.

        // Given: A temp directory path
        // When:  Using isolated_database_path(directory=tmp_path)
        // Then:  DB file is created under tmp_path and removed afterwards
        """
        from src.storage.isolation import isolated_database_path

        target = tmp_path / "custom.db"
        assert not target.exists()

        async with isolated_database_path(directory=tmp_path, filename="custom.db") as db_path:
            assert db_path == target
            assert os.environ.get("LYRA_STORAGE__DATABASE_PATH") == str(target)

        assert not target.exists()
