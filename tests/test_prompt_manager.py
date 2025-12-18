"""
Tests for PromptManager (Phase K.2).

Verifies:
- Template loading and caching
- Variable injection
- Error handling
- Backward compatibility with original prompts
"""

import pytest
from pathlib import Path
from unittest.mock import patch
import tempfile
import os

from src.utils.prompt_manager import (
    PromptManager,
    PromptTemplateError,
    TemplateNotFoundError,
    TemplateRenderError,
    get_prompt_manager,
    reset_prompt_manager,
    render_prompt,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_prompts_dir():
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
def manager(temp_prompts_dir):
    """Create a PromptManager with temporary templates."""
    return PromptManager(prompts_dir=temp_prompts_dir)


@pytest.fixture
def real_manager():
    """Create a PromptManager with real config/prompts/ templates."""
    reset_prompt_manager()
    return get_prompt_manager()


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_prompt_manager()
    yield
    reset_prompt_manager()


# ============================================================================
# Basic Functionality Tests
# ============================================================================

class TestPromptManagerInit:
    """Tests for PromptManager initialization."""
    
    def test_init_with_custom_dir(self, temp_prompts_dir):
        """Test initialization with custom prompts directory."""
        manager = PromptManager(prompts_dir=temp_prompts_dir)
        assert manager.prompts_dir == temp_prompts_dir
    
    def test_init_default_dir(self):
        """Test initialization with default prompts directory."""
        manager = PromptManager()
        # Should point to config/prompts/
        assert manager.prompts_dir.name == "prompts"
        assert manager.prompts_dir.parent.name == "config"
    
    def test_init_with_env_var(self, temp_prompts_dir):
        """Test initialization respects LANCET_CONFIG_DIR env var."""
        with patch.dict(os.environ, {"LANCET_CONFIG_DIR": str(temp_prompts_dir.parent)}):
            reset_prompt_manager()
            manager = PromptManager()
            # Should use the env var path
            assert str(temp_prompts_dir.parent) in str(manager.prompts_dir)


class TestTemplateLoading:
    """Tests for template loading."""
    
    def test_template_exists_true(self, manager, temp_prompts_dir):
        """Test template_exists returns True for existing template."""
        assert manager.template_exists("simple")
    
    def test_template_exists_false(self, manager):
        """Test template_exists returns False for non-existing template."""
        assert not manager.template_exists("nonexistent")
    
    def test_list_templates(self, manager):
        """Test listing all available templates."""
        templates = manager.list_templates()
        assert "simple" in templates
        assert "multi_var" in templates
        assert "no_vars" in templates
    
    def test_list_templates_empty_dir(self):
        """Test listing templates from empty/non-existent directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir) / "empty"
            manager = PromptManager(prompts_dir=empty_dir)
            assert manager.list_templates() == []
    
    def test_get_template_path(self, manager, temp_prompts_dir):
        """Test getting template path."""
        path = manager.get_template_path("simple")
        assert path == temp_prompts_dir / "simple.j2"


# ============================================================================
# Rendering Tests
# ============================================================================

class TestRendering:
    """Tests for template rendering."""
    
    def test_render_simple_template(self, manager):
        """Test rendering a simple template with one variable."""
        result = manager.render("simple", name="World")
        assert result == "Hello, World!"
    
    def test_render_multiple_variables(self, manager):
        """Test rendering with multiple variables."""
        result = manager.render("multi_var", greeting="Hi", name="Alice")
        assert result == "Hi, Alice!"
    
    def test_render_no_variables(self, manager):
        """Test rendering template without variables."""
        result = manager.render("no_vars")
        assert result == "Static template content."
    
    def test_render_with_extra_variables(self, manager):
        """Test that extra variables are ignored."""
        result = manager.render("simple", name="World", extra="ignored")
        assert result == "Hello, World!"
    
    def test_render_with_unicode(self, manager):
        """Test rendering with unicode characters."""
        result = manager.render("simple", name="世界")
        assert result == "Hello, 世界!"


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Tests for error handling."""
    
    def test_render_nonexistent_template(self, manager):
        """Test rendering non-existent template raises TemplateNotFoundError."""
        with pytest.raises(TemplateNotFoundError) as exc_info:
            manager.render("nonexistent")
        assert "nonexistent.j2" in str(exc_info.value)
    
    def test_render_missing_variable(self, manager):
        """Test rendering with missing required variable raises TemplateRenderError."""
        with pytest.raises(TemplateRenderError) as exc_info:
            manager.render("simple")  # Missing 'name' variable
        assert "simple" in str(exc_info.value)
    
    def test_nonexistent_prompts_dir(self):
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
    
    def test_environment_cached(self, manager):
        """Test that Jinja2 environment is cached."""
        manager.render("simple", name="A")
        env1 = manager._env
        manager.render("simple", name="B")
        env2 = manager._env
        assert env1 is env2
    
    def test_clear_cache(self, manager):
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
    
    def test_get_prompt_manager_singleton(self):
        """Test that get_prompt_manager returns the same instance."""
        manager1 = get_prompt_manager()
        manager2 = get_prompt_manager()
        assert manager1 is manager2
    
    def test_reset_prompt_manager(self):
        """Test that reset_prompt_manager clears the singleton."""
        manager1 = get_prompt_manager()
        reset_prompt_manager()
        manager2 = get_prompt_manager()
        assert manager1 is not manager2
    
    def test_render_prompt_convenience(self, temp_prompts_dir):
        """Test render_prompt convenience function."""
        # Use a custom manager for this test
        reset_prompt_manager()
        with patch.dict(os.environ, {"LANCET_CONFIG_DIR": str(temp_prompts_dir.parent)}):
            reset_prompt_manager()
            result = render_prompt("simple", name="Test")
            assert result == "Hello, Test!"


# ============================================================================
# Real Template Tests (Regression)
# ============================================================================

class TestRealTemplates:
    """Tests for actual prompt templates in config/prompts/."""
    
    def test_extract_facts_template_exists(self, real_manager):
        """Test extract_facts template exists."""
        assert real_manager.template_exists("extract_facts")
    
    def test_extract_claims_template_exists(self, real_manager):
        """Test extract_claims template exists."""
        assert real_manager.template_exists("extract_claims")
    
    def test_summarize_template_exists(self, real_manager):
        """Test summarize template exists."""
        assert real_manager.template_exists("summarize")
    
    def test_translate_template_exists(self, real_manager):
        """Test translate template exists."""
        assert real_manager.template_exists("translate")
    
    def test_decompose_template_exists(self, real_manager):
        """Test decompose template exists."""
        assert real_manager.template_exists("decompose")
    
    def test_extract_facts_renders(self, real_manager):
        """Test extract_facts template renders correctly."""
        result = real_manager.render("extract_facts", text="Sample text for testing.")
        assert "Sample text for testing." in result
        assert "情報抽出" in result or "事実" in result
    
    def test_extract_claims_renders(self, real_manager):
        """Test extract_claims template renders correctly."""
        result = real_manager.render(
            "extract_claims",
            text="Sample text",
            context="Research question"
        )
        assert "Sample text" in result
        assert "Research question" in result
    
    def test_summarize_renders(self, real_manager):
        """Test summarize template renders correctly."""
        result = real_manager.render("summarize", text="Long text to summarize.")
        assert "Long text to summarize." in result
        assert "要約" in result
    
    def test_translate_renders(self, real_manager):
        """Test translate template renders correctly."""
        result = real_manager.render("translate", text="Hello", target_lang="日本語")
        assert "Hello" in result
        assert "日本語" in result
    
    def test_decompose_renders(self, real_manager):
        """Test decompose template renders correctly."""
        result = real_manager.render("decompose", question="What is AI?")
        assert "What is AI?" in result
        assert "atomic" in result.lower() or "原子" in result


# ============================================================================
# Backward Compatibility Tests
# ============================================================================

class TestBackwardCompatibility:
    """Tests to verify output matches original hardcoded prompts."""
    
    def test_extract_facts_output_structure(self, real_manager):
        """Test extract_facts output has expected structure."""
        result = real_manager.render("extract_facts", text="TEST_TEXT")
        
        # Should contain the key phrases from original prompt
        assert "情報抽出の専門家" in result
        assert "TEST_TEXT" in result
        assert "JSON配列" in result
        assert "fact" in result
        assert "confidence" in result
    
    def test_extract_claims_output_structure(self, real_manager):
        """Test extract_claims output has expected structure."""
        result = real_manager.render(
            "extract_claims",
            text="TEST_TEXT",
            context="TEST_CONTEXT"
        )
        
        # Should contain the key phrases from original prompt
        assert "情報分析の専門家" in result
        assert "TEST_TEXT" in result
        assert "TEST_CONTEXT" in result
        assert "JSON配列" in result
        assert "claim" in result
    
    def test_summarize_output_structure(self, real_manager):
        """Test summarize output has expected structure."""
        result = real_manager.render("summarize", text="TEST_TEXT")
        
        # Should contain the key phrases from original prompt
        assert "要約" in result
        assert "TEST_TEXT" in result
    
    def test_translate_output_structure(self, real_manager):
        """Test translate output has expected structure."""
        result = real_manager.render(
            "translate",
            text="TEST_TEXT",
            target_lang="TEST_LANG"
        )
        
        # Should contain the key phrases from original prompt
        assert "翻訳" in result
        assert "TEST_TEXT" in result
        assert "TEST_LANG" in result
    
    def test_decompose_output_structure(self, real_manager):
        """Test decompose output has expected structure."""
        result = real_manager.render("decompose", question="TEST_QUESTION")
        
        # Should contain the key phrases from original prompt
        assert "情報分析の専門家" in result
        assert "TEST_QUESTION" in result
        assert "atomic" in result.lower() or "原子主張" in result
        assert "polarity" in result
        assert "granularity" in result
