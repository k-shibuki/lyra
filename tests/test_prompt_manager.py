"""
Tests for PromptManager (Prompt template management).

Verifies:
- Template loading and caching
- Variable injection
- Error handling
- Jinja2 template validation (JSON format, edge cases)
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.prompt_manager import (
    PromptManager,
    TemplateNotFoundError,
    TemplateRenderError,
    get_prompt_manager,
    render_prompt,
    reset_prompt_manager,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_prompts_dir() -> Generator[Path]:
    """Create a temporary prompts directory with test templates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        prompts_dir = Path(tmpdir) / "prompts"
        prompts_dir.mkdir()

        # Create test templates
        (prompts_dir / "simple.j2").write_text("Hello, {{ name }}!")
        (prompts_dir / "multi_var.j2").write_text("{{ greeting }}, {{ name }}!")
        (prompts_dir / "no_vars.j2").write_text("Static template content.")

        yield prompts_dir


@pytest.fixture
def manager(temp_prompts_dir: Path) -> PromptManager:
    """Create a PromptManager with temporary templates."""
    return PromptManager(prompts_dir=temp_prompts_dir)


@pytest.fixture
def real_manager() -> PromptManager:
    """Create a PromptManager with real config/prompts/ templates."""
    reset_prompt_manager()
    return get_prompt_manager()


@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None]:
    """Reset the global singleton before and after each test."""
    reset_prompt_manager()
    yield
    reset_prompt_manager()


# ============================================================================
# Basic Functionality Tests
# ============================================================================


class TestPromptManagerInit:
    """Tests for PromptManager initialization."""

    def test_init_with_custom_dir(self, temp_prompts_dir: Path) -> None:
        """Test initialization with custom prompts directory."""
        manager = PromptManager(prompts_dir=temp_prompts_dir)
        assert manager.prompts_dir == temp_prompts_dir

    def test_init_default_dir(self) -> None:
        """Test initialization with default prompts directory."""
        manager = PromptManager()
        # Should point to config/prompts/
        assert manager.prompts_dir.name == "prompts"
        assert manager.prompts_dir.parent.name == "config"

    def test_init_with_env_var(self, temp_prompts_dir: Path) -> None:
        """Test initialization respects LYRA_CONFIG_DIR env var."""
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_prompts_dir.parent)}):
            reset_prompt_manager()
            manager = PromptManager()
            # Should use the env var path
            assert str(temp_prompts_dir.parent) in str(manager.prompts_dir)


class TestTemplateLoading:
    """Tests for template loading."""

    def test_template_exists_true(self, manager: PromptManager, temp_prompts_dir: Path) -> None:
        """Test template_exists returns True for existing template."""
        assert manager.template_exists("simple")

    def test_template_exists_false(self, manager: PromptManager) -> None:
        """Test template_exists returns False for non-existing template."""
        assert not manager.template_exists("nonexistent")

    def test_list_templates(self, manager: PromptManager) -> None:
        """Test listing all available templates."""
        templates = manager.list_templates()
        assert "simple" in templates
        assert "multi_var" in templates
        assert "no_vars" in templates

    def test_list_templates_empty_dir(self) -> None:
        """Test listing templates from empty/non-existent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir) / "empty"
            manager = PromptManager(prompts_dir=empty_dir)
            assert manager.list_templates() == []

    def test_get_template_path(self, manager: PromptManager, temp_prompts_dir: Path) -> None:
        """Test getting template path."""
        path = manager.get_template_path("simple")
        assert path == temp_prompts_dir / "simple.j2"


# ============================================================================
# Rendering Tests
# ============================================================================


class TestRendering:
    """Tests for template rendering."""

    def test_render_simple_template(self, manager: PromptManager) -> None:
        """Test rendering a simple template with one variable."""
        result = manager.render("simple", name="World")
        assert result == "Hello, World!"

    def test_render_multiple_variables(self, manager: PromptManager) -> None:
        """Test rendering with multiple variables."""
        result = manager.render("multi_var", greeting="Hi", name="Alice")
        assert result == "Hi, Alice!"

    def test_render_no_variables(self, manager: PromptManager) -> None:
        """Test rendering template without variables."""
        result = manager.render("no_vars")
        assert result == "Static template content."

    def test_render_with_extra_variables(self, manager: PromptManager) -> None:
        """Test that extra variables are ignored."""
        result = manager.render("simple", name="World", extra="ignored")
        assert result == "Hello, World!"

    def test_render_with_unicode(self, manager: PromptManager) -> None:
        """Test rendering with unicode characters."""
        result = manager.render("simple", name="世界")
        assert result == "Hello, 世界!"


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_render_nonexistent_template(self, manager: PromptManager) -> None:
        """Test rendering non-existent template raises TemplateNotFoundError."""
        with pytest.raises(TemplateNotFoundError) as exc_info:
            manager.render("nonexistent")
        assert "nonexistent.j2" in str(exc_info.value)

    def test_render_missing_variable(self, manager: PromptManager) -> None:
        """Test rendering with missing required variable raises TemplateRenderError."""
        with pytest.raises(TemplateRenderError) as exc_info:
            manager.render("simple")  # Missing 'name' variable
        assert "simple" in str(exc_info.value)

    def test_nonexistent_prompts_dir(self) -> None:
        """Test that accessing non-existent prompts dir raises TemplateNotFoundError."""
        manager = PromptManager(prompts_dir=Path("/nonexistent/path"))
        with pytest.raises(TemplateNotFoundError) as exc_info:
            manager.render("any_template")
        # The error message contains the path
        assert "/nonexistent/path" in str(exc_info.value)


# ============================================================================
# Cache Tests
# ============================================================================


class TestCaching:
    """Tests for template caching."""

    def test_environment_cached(self, manager: PromptManager) -> None:
        """Test that Jinja2 environment is cached."""
        manager.render("simple", name="A")
        env1 = manager._env
        manager.render("simple", name="B")
        env2 = manager._env
        assert env1 is env2

    def test_clear_cache(self, manager: PromptManager) -> None:
        """Test clearing the cache."""
        manager.render("simple", name="A")
        assert manager._env is not None
        manager.clear_cache()
        assert manager._env is None


# ============================================================================
# Singleton Tests
# ============================================================================


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_prompt_manager_singleton(self) -> None:
        """Test that get_prompt_manager returns the same instance."""
        manager1 = get_prompt_manager()
        manager2 = get_prompt_manager()
        assert manager1 is manager2

    def test_reset_prompt_manager(self) -> None:
        """Test that reset_prompt_manager clears the singleton."""
        manager1 = get_prompt_manager()
        reset_prompt_manager()
        manager2 = get_prompt_manager()
        assert manager1 is not manager2

    def test_render_prompt_convenience(self, temp_prompts_dir: Path) -> None:
        """Test render_prompt convenience function."""
        # Use a custom manager for this test
        reset_prompt_manager()
        with patch.dict(os.environ, {"LYRA_CONFIG_DIR": str(temp_prompts_dir.parent)}):
            reset_prompt_manager()
            result = render_prompt("simple", name="Test")
            assert result == "Hello, Test!"


# ============================================================================
# Real Template Tests (Regression)
# ============================================================================


class TestRealTemplates:
    """Tests for actual prompt templates in config/prompts/."""

    def test_extract_facts_template_exists(self, real_manager: PromptManager) -> None:
        """Test extract_facts template exists."""
        assert real_manager.template_exists("extract_facts")

    def test_extract_claims_template_exists(self, real_manager: PromptManager) -> None:
        """Test extract_claims template exists."""
        assert real_manager.template_exists("extract_claims")

    def test_summarize_template_exists(self, real_manager: PromptManager) -> None:
        """Test summarize template exists."""
        assert real_manager.template_exists("summarize")

    def test_translate_template_exists(self, real_manager: PromptManager) -> None:
        """Test translate template exists."""
        assert real_manager.template_exists("translate")

    def test_decompose_template_exists(self, real_manager: PromptManager) -> None:
        """Test decompose template exists."""
        assert real_manager.template_exists("decompose")

    def test_extract_facts_renders(self, real_manager: PromptManager) -> None:
        """Test extract_facts template renders correctly."""
        result = real_manager.render("extract_facts", text="Sample text for testing.")
        assert "Sample text for testing." in result
        assert "fact" in result.lower()

    def test_extract_claims_renders(self, real_manager: PromptManager) -> None:
        """Test extract_claims template renders correctly."""
        result = real_manager.render(
            "extract_claims", text="Sample text", context="Research question"
        )
        assert "Sample text" in result
        assert "Research question" in result

    def test_summarize_renders(self, real_manager: PromptManager) -> None:
        """Test summarize template renders correctly."""
        result = real_manager.render("summarize", text="Long text to summarize.")
        assert "Long text to summarize." in result
        assert "summary" in result.lower()

    def test_translate_renders(self, real_manager: PromptManager) -> None:
        """Test translate template renders correctly."""
        result = real_manager.render("translate", text="Hello", target_lang="日本語")
        assert "Hello" in result
        assert "日本語" in result

    def test_decompose_renders(self, real_manager: PromptManager) -> None:
        """Test decompose template renders correctly."""
        result = real_manager.render("decompose", question="What is AI?")
        assert "What is AI?" in result
        assert "atomic" in result.lower()

    def test_quality_assessment_template_exists(self, real_manager: PromptManager) -> None:
        """Test quality_assessment template exists."""
        assert real_manager.template_exists("quality_assessment")

    def test_quality_assessment_renders(self, real_manager: PromptManager) -> None:
        """Test quality_assessment template renders correctly."""
        result = real_manager.render(
            "quality_assessment", text="Sample content for quality analysis.", lang="en"
        )
        assert "Sample content for quality analysis." in result
        assert "quality_score" in result
        assert "is_ai_generated" in result


# ============================================================================
# Template Validation Tests
# ============================================================================
#
# Test Perspective Table:
# | Case ID | Input / Precondition | Perspective | Expected Result | Notes |
# |---------|---------------------|-------------|-----------------|-------|
# | TC-N-01 | extract_facts with valid text | Equivalence - normal | Renders correctly, JSON uses single braces | - |
# | TC-N-02 | extract_claims with valid text/context | Equivalence - normal | Renders correctly, JSON uses single braces | - |
# | TC-N-03 | decompose with valid question | Equivalence - normal | Renders correctly, JSON uses single braces | - |
# | TC-N-04 | summarize with valid text | Equivalence - normal | Renders correctly | - |
# | TC-N-05 | translate with valid text/target_lang | Equivalence - normal | Renders correctly | - |
# | TC-B-01 | Empty string for text | Boundary - empty | Renders correctly (empty string is valid) | - |
# | TC-B-02 | Very long text (4000+ chars) | Boundary - max length | Renders correctly | - |
# | TC-B-03 | Text with special chars (JSON, braces) | Boundary - special chars | Renders correctly, JSON example unchanged | - |
# | TC-B-04 | Text with unicode/emoji | Boundary - unicode | Renders correctly | - |
# | TC-A-01 | Missing required variable (text) | Boundary - missing var | Raises TemplateRenderError | - |
# | TC-A-02 | Missing context for extract_claims | Boundary - missing var | Raises TemplateRenderError | - |
# | TC-V-01 | JSON format check (extract_facts) | Validation - format | Single `{` not double `{{` | - |
# | TC-V-02 | JSON format check (extract_claims) | Validation - format | Single `{` not double `{{` | - |
# | TC-V-03 | JSON format check (decompose) | Validation - format | Single `{` not double `{{` | - |


class TestTemplateValidation:
    """Tests to validate Jinja2 template correctness, JSON format, and edge cases."""

    # -------------------------------------------------------------------------
    # TC-N-01 to TC-N-05: Normal cases - template rendering
    # -------------------------------------------------------------------------

    def test_extract_facts_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-01: Test extract_facts template renders with valid input."""
        # Given: Valid text input
        text = "This is a sample text for testing."

        # When: Rendering the template
        result = real_manager.render("extract_facts", text=text)

        # Then: Template renders correctly with injected variable
        assert text in result
        assert "fact" in result.lower()
        assert "JSON" in result

    def test_extract_claims_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-02: Test extract_claims template renders with valid input."""
        # Given: Valid text and context input
        text = "Sample claim text."
        context = "Research question about AI"

        # When: Rendering the template
        result = real_manager.render("extract_claims", text=text, context=context)

        # Then: Template renders correctly with both variables injected
        assert text in result
        assert context in result
        assert "claim" in result.lower()

    def test_decompose_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-03: Test decompose template renders with valid input."""
        # Given: Valid question input
        question = "What are the benefits of renewable energy?"

        # When: Rendering the template
        result = real_manager.render("decompose", question=question)

        # Then: Template renders correctly with question injected
        assert question in result
        assert "atomic" in result.lower()

    def test_summarize_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-04: Test summarize template renders with valid input."""
        # Given: Valid text input
        text = "Long document text that needs summarization."

        # When: Rendering the template
        result = real_manager.render("summarize", text=text)

        # Then: Template renders correctly
        assert text in result
        assert "summary" in result.lower()

    def test_translate_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-05: Test translate template renders with valid input."""
        # Given: Valid text and target language
        text = "Hello, world!"
        target_lang = "日本語"

        # When: Rendering the template
        result = real_manager.render("translate", text=text, target_lang=target_lang)

        # Then: Template renders correctly with both variables
        assert text in result
        assert target_lang in result
        assert "translat" in result.lower()

    # -------------------------------------------------------------------------
    # TC-B-01 to TC-B-04: Boundary cases
    # -------------------------------------------------------------------------

    def test_empty_string_input(self, real_manager: PromptManager) -> None:
        """TC-B-01: Test template renders with empty string input."""
        # Given: Empty string for text
        text = ""

        # When: Rendering the template
        result = real_manager.render("extract_facts", text=text)

        # Then: Template renders correctly (empty input is valid)
        # Template should contain core instruction text
        assert "Extract" in result
        assert "Text:" in result

    def test_very_long_text_input(self, real_manager: PromptManager) -> None:
        """TC-B-02: Test template renders with very long text (4000+ chars)."""
        # Given: Very long text input
        text = "A" * 5000  # 5000 characters

        # When: Rendering the template
        result = real_manager.render("extract_facts", text=text)

        # Then: Template renders correctly with the long text
        assert text in result
        assert len(result) > 5000

    def test_special_characters_in_input(self, real_manager: PromptManager) -> None:
        """TC-B-03: Test template renders with special characters (JSON, braces)."""
        # Given: Text containing JSON-like content and special characters
        text = '{"key": "value"} and {braces} and {{double_braces}}'

        # When: Rendering the template
        result = real_manager.render("extract_facts", text=text)

        # Then: Template renders correctly, input preserved as-is
        assert text in result
        # JSON example in template should still use single braces
        assert '{"fact":' in result

    def test_unicode_and_emoji_input(self, real_manager: PromptManager) -> None:
        """TC-B-04: Test template renders with unicode and emoji."""
        # Given: Text with unicode characters and emoji
        text = "日本語テスト 🎉 émojis и кириллица"

        # When: Rendering the template
        result = real_manager.render("extract_facts", text=text)

        # Then: Template renders correctly with unicode preserved
        assert text in result

    # -------------------------------------------------------------------------
    # TC-A-01 to TC-A-02: Error cases - missing variables
    # -------------------------------------------------------------------------

    def test_missing_required_variable_extract_facts(self, real_manager: PromptManager) -> None:
        """TC-A-01: Test extract_facts raises error when 'text' is missing."""
        # Given: No text variable provided
        # When: Attempting to render without required variable
        # Then: Should raise TemplateRenderError
        with pytest.raises(TemplateRenderError) as exc_info:
            real_manager.render("extract_facts")

        assert "extract_facts" in str(exc_info.value)
        assert "text" in str(exc_info.value).lower() or "undefined" in str(exc_info.value).lower()

    def test_missing_required_variable_extract_claims(self, real_manager: PromptManager) -> None:
        """TC-A-02: Test extract_claims raises error when 'context' is missing."""
        # Given: Only text provided, context missing
        # When: Attempting to render without context variable
        # Then: Should raise TemplateRenderError
        with pytest.raises(TemplateRenderError) as exc_info:
            real_manager.render("extract_claims", text="some text")

        assert "extract_claims" in str(exc_info.value)

    # -------------------------------------------------------------------------
    # TC-V-01 to TC-V-03: JSON format validation (single braces, not double)
    # -------------------------------------------------------------------------

    def test_json_format_extract_facts(self, real_manager: PromptManager) -> None:
        """TC-V-01: Verify extract_facts JSON example uses single braces."""
        # Given: Valid input
        result = real_manager.render("extract_facts", text="test")

        # When: Checking the JSON example format
        # Then: Should use single braces {, not double {{
        assert '{"fact":' in result, "JSON example should use single braces"
        assert '{{"fact":' not in result, "JSON example should NOT use double braces"

    def test_json_format_extract_claims(self, real_manager: PromptManager) -> None:
        """TC-V-02: Verify extract_claims JSON example uses single braces."""
        # Given: Valid input
        result = real_manager.render("extract_claims", text="test", context="context")

        # When: Checking the JSON example format
        # Then: Should use single braces {, not double {{
        assert '"claim":' in result, "JSON example should use single braces"
        assert '{{"claim":' not in result, "JSON example should NOT use double braces"

    def test_json_format_decompose(self, real_manager: PromptManager) -> None:
        """TC-V-03: Verify decompose JSON example uses single braces."""
        # Given: Valid input
        result = real_manager.render("decompose", question="test question")

        # When: Checking the JSON example format
        # Then: Should use single braces {, not double {{
        # JSON example is inline (not multi-line), so check for {"text":
        assert '{"text":' in result, "JSON example should use single braces"
        assert '{{"text":' not in result, "JSON example should NOT use double braces"
        # Verify specific JSON structure
        assert '"polarity":' in result

    # -------------------------------------------------------------------------
    # TC-N-06 to TC-N-10: New/updated templates (Phase 1 additions)
    # -------------------------------------------------------------------------

    def test_quality_assessment_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-09: Test quality_assessment template renders with valid input."""
        # Given: Valid text input
        text = "Content to analyze for quality."

        # When: Rendering the template
        result = real_manager.render("quality_assessment", text=text)

        # Then: Template renders correctly
        assert text in result
        assert "quality" in result.lower()
        assert "academic" in result.lower()

    def test_detect_citation_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-10: Test detect_citation template renders with valid input."""
        # Given: Valid input parameters
        context = "According to the study..."
        url = "https://example.com/paper"
        link_text = "Smith et al., 2023"

        # When: Rendering the template
        result = real_manager.render(
            "detect_citation", context=context, url=url, link_text=link_text
        )

        # Then: Template renders correctly with all variables
        assert context in result
        assert url in result
        assert link_text in result
        assert "citation" in result.lower()

    def test_relevance_evaluation_renders_correctly(self, real_manager: PromptManager) -> None:
        """TC-N-11: Test relevance_evaluation template renders with valid input."""
        # Given: Valid input parameters
        query = "What is the effect of drug X?"
        source_abstract = "This study examines drug X..."
        target_abstract = "A related study on drug X..."

        # When: Rendering the template
        result = real_manager.render(
            "relevance_evaluation",
            query=query,
            source_abstract=source_abstract,
            target_abstract=target_abstract,
        )

        # Then: Template renders correctly with all variables
        assert query in result
        assert source_abstract in result
        assert target_abstract in result
        assert "0-10" in result

    # -------------------------------------------------------------------------
    # TC-V-04 to TC-V-07: JSON format validation for new templates
    # -------------------------------------------------------------------------

    def test_json_format_quality_assessment(self, real_manager: PromptManager) -> None:
        """TC-V-06: Verify quality_assessment JSON example uses single braces."""
        # Given: Valid input
        result = real_manager.render("quality_assessment", text="test")

        # Then: Should use single braces
        assert '"quality_score":' in result
        assert '{{"quality_score":' not in result

    def test_summarize_with_max_words(self, real_manager: PromptManager) -> None:
        """TC-V-07: Verify summarize template supports max_words parameter."""
        # Given: Text with custom max_words
        text = "Test content"
        max_words = 50

        # When: Rendering with max_words
        result = real_manager.render("summarize", text=text, max_words=max_words)

        # Then: max_words is included
        assert "50" in result
        assert "words" in result.lower()
