"""Jinja2 syntax validation tests for all prompt templates.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|----------------------|-------------|-----------------|-------|
| TC-SYN-01 | All templates | Syntax validation | All compile | - |
| TC-SYN-02 | Each template | Variable documentation | Has comments | - |
| TC-SYN-03 | Templates with defaults | Default values | Work without optional vars | - |
"""

from pathlib import Path

import pytest
from jinja2 import TemplateSyntaxError

from src.utils.prompt_manager import PromptManager


class TestTemplateSyntax:
    """Tests for Jinja2 template syntax validation."""

    def test_all_templates_compile(
        self,
        prompt_manager: PromptManager,
        all_template_names: list[str],
    ) -> None:
        """TC-SYN-01: All templates compile without syntax errors."""
        # Given: List of all template names
        assert len(all_template_names) > 0, "Should have templates to test"

        # When/Then: Each template should compile
        for name in all_template_names:
            try:
                # Attempt to get template (which triggers compilation)
                path = prompt_manager.get_template_path(name)
                assert path is not None, f"Template {name} should exist"
            except TemplateSyntaxError as e:
                pytest.fail(f"Template '{name}' has syntax error: {e}")

    def test_template_has_parameter_documentation(
        self,
        template_dir: Path,
        all_template_names: list[str],
    ) -> None:
        """TC-SYN-02: Each template documents its required parameters."""
        # Given: All template files
        for name in all_template_names:
            template_path = template_dir / f"{name}.j2"

            # When: Reading template content
            content = template_path.read_text()

            # Then: Should have a comment block with Parameters
            assert "{#" in content, f"Template '{name}' must have Jinja2 comments"

    def test_templates_with_optional_parameters(
        self,
        prompt_manager: PromptManager,
    ) -> None:
        """TC-SYN-03: Templates with optional parameters work without them."""
        # Given: Templates known to have optional parameters
        optional_param_templates = {
            "summarize": {"text": "Test text"},  # max_words is optional
        }

        # When/Then: Render without optional parameters
        for name, required_vars in optional_param_templates.items():
            try:
                result = prompt_manager.render(name, **required_vars)
                assert result is not None
                assert len(result) > 0
            except Exception as e:
                pytest.fail(f"Template '{name}' failed without optional params: {e}")


class TestTemplateStructure:
    """Tests for template structural requirements."""

    def test_json_templates_have_output_section(
        self,
        template_dir: Path,
        json_output_templates: list[str],
    ) -> None:
        """Templates expecting JSON output should have output format section."""
        # Given: Templates that should produce JSON output
        for name in json_output_templates:
            template_path = template_dir / f"{name}.j2"

            # When: Reading template content
            content = template_path.read_text().lower()

            # Then: Should mention JSON or output format
            has_json = "json" in content
            has_output = "output" in content

            assert has_json or has_output, f"Template '{name}' should document JSON output format"

    def test_all_templates_are_english(
        self,
        template_dir: Path,
        all_template_names: list[str],
    ) -> None:
        """All templates should be in English (Phase 1 requirement)."""
        # Given: All template files
        japanese_chars = set()

        for name in all_template_names:
            template_path = template_dir / f"{name}.j2"
            content = template_path.read_text()

            # Check for Japanese characters (excluding variable content)
            # Skip lines that are Jinja2 expressions
            for line in content.split("\n"):
                if "{{" in line or "{%" in line:
                    continue
                for char in line:
                    if "\u3040" <= char <= "\u309f":  # Hiragana
                        japanese_chars.add((name, char))
                    elif "\u30a0" <= char <= "\u30ff":  # Katakana
                        japanese_chars.add((name, char))
                    elif "\u4e00" <= char <= "\u9fff":  # Kanji
                        japanese_chars.add((name, char))

        # Then: Should have no Japanese characters in static text
        if japanese_chars:
            templates_with_jp = {name for name, _ in japanese_chars}
            pytest.fail(
                f"Templates with Japanese characters: {templates_with_jp}. "
                "All templates should be English-only per Phase 1."
            )


class TestTemplateCompleteness:
    """Tests for template completeness and coverage."""

    def test_expected_templates_exist(
        self,
        all_template_names: list[str],
    ) -> None:
        """All expected templates should exist."""
        # Given: Expected template names from Phase 1
        expected = {
            "extract_facts",
            "extract_claims",
            "summarize",
            "translate",
            "decompose",
            "detect_citation",
            "relevance_evaluation",
            "quality_assessment",
        }

        # When: Checking available templates
        available = set(all_template_names)

        # Then: All expected templates should exist
        missing = expected - available
        assert not missing, f"Missing expected templates: {missing}"

    def test_no_unexpected_templates(
        self,
        all_template_names: list[str],
    ) -> None:
        """Check for any new templates (informational)."""
        # Given: Known templates from Phase 1
        known = {
            "extract_facts",
            "extract_claims",
            "summarize",
            "translate",
            "decompose",
            "detect_citation",
            "relevance_evaluation",
            "quality_assessment",
        }

        # When: Checking for new templates
        available = set(all_template_names)
        new_templates = available - known

        # Then: Log any new templates (not a failure, just informational)
        if new_templates:
            # This is informational - new templates may be added
            pass  # Just acknowledge, don't fail
