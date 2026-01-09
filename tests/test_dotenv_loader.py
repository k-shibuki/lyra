from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.unit
class TestDotenvLoader:
    """Tests for minimal dotenv loader.

    Test Perspectives Table:
    | Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
    |--------:|----------------------|---------------------------------------|-----------------|-------|
    | TC-DOT-01 | .env with key=value | Equivalence – normal                  | sets os.environ | - |
    | TC-DOT-02 | existing env var set | Equivalence – abnormal                | does not override | - |
    | TC-DOT-03 | quotes + comments    | Boundary – empty/comment              | parsed correctly | - |
    """

    def test_load_dotenv_sets_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        TC-DOT-01: load_dotenv_if_present loads key=value into os.environ.

        // Given: dotenv file with a key
        // When:  load_dotenv_if_present(dotenv_path=...) is called
        // Then:  os.environ has the key/value
        """
        # Given
        from src.utils.dotenv import load_dotenv_if_present

        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("FOO=bar\n", encoding="utf-8")
        monkeypatch.delenv("FOO", raising=False)

        # When
        loaded = load_dotenv_if_present(dotenv_path=dotenv_path)

        # Then
        assert loaded is True
        assert os.environ["FOO"] == "bar"

    def test_load_dotenv_does_not_override_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        TC-DOT-02: existing os.environ is not overridden.

        // Given: dotenv file sets FOO=bar, but os.environ already has FOO=baz
        // When:  load_dotenv_if_present(dotenv_path=...) is called
        // Then:  os.environ["FOO"] remains "baz"
        """
        # Given
        from src.utils.dotenv import load_dotenv_if_present

        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text("FOO=bar\n", encoding="utf-8")
        monkeypatch.setenv("FOO", "baz")

        # When
        loaded = load_dotenv_if_present(dotenv_path=dotenv_path)

        # Then
        assert loaded is True
        assert os.environ["FOO"] == "baz"

    def test_load_dotenv_parses_quotes_and_ignores_comments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        TC-DOT-03: quotes are stripped and comments/empty lines ignored.

        // Given: dotenv file with comments, empty line, and quoted values
        // When:  load_dotenv_if_present(dotenv_path=...) is called
        // Then:  values are loaded with quotes removed
        """
        # Given
        from src.utils.dotenv import load_dotenv_if_present

        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text(
            "# comment\n\nexport A='x'\nB=\"y\"\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("A", raising=False)
        monkeypatch.delenv("B", raising=False)

        # When
        loaded = load_dotenv_if_present(dotenv_path=dotenv_path)

        # Then
        assert loaded is True
        assert os.environ["A"] == "x"
        assert os.environ["B"] == "y"
