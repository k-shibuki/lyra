"""
Prompt template manager for Lancet.

Manages LLM prompt templates using Jinja2, providing:
- Template loading and caching
- Variable injection and validation
- Consistent error handling

Per Phase K.2: External prompt template management for improved maintainability.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound, UndefinedError

from src.utils.logging import get_logger

logger = get_logger(__name__)


class PromptTemplateError(Exception):
    """Base exception for prompt template errors."""
    pass


class TemplateNotFoundError(PromptTemplateError):
    """Raised when a template file is not found."""
    pass


class TemplateRenderError(PromptTemplateError):
    """Raised when template rendering fails."""
    pass


class PromptManager:
    """
    Manager for LLM prompt templates.

    Loads Jinja2 templates from config/prompts/ and provides
    a simple API for rendering prompts with variables.

    Usage:
        manager = get_prompt_manager()
        prompt = manager.render("extract_facts", text="...")
    """

    def __init__(self, prompts_dir: Path | None = None):
        """
        Initialize the prompt manager.

        Args:
            prompts_dir: Path to prompts directory. 
                        Defaults to config/prompts/ relative to project root.
        """
        if prompts_dir is None:
            # Use LANCET_CONFIG_DIR if set, otherwise default to config/
            config_dir = Path(os.environ.get("LANCET_CONFIG_DIR", "config"))
            if not config_dir.is_absolute():
                from src.utils.config import get_project_root
                config_dir = get_project_root() / config_dir
            prompts_dir = config_dir / "prompts"

        self._prompts_dir = prompts_dir
        self._env: Environment | None = None

        logger.debug(
            "PromptManager initialized",
            prompts_dir=str(self._prompts_dir),
        )

    @property
    def prompts_dir(self) -> Path:
        """Get the prompts directory path."""
        return self._prompts_dir

    def _get_environment(self) -> Environment:
        """
        Get or create the Jinja2 environment.

        Returns:
            Configured Jinja2 Environment.

        Raises:
            TemplateNotFoundError: If prompts directory doesn't exist.
        """
        if self._env is None:
            if not self._prompts_dir.exists():
                raise TemplateNotFoundError(
                    f"Prompts directory not found: {self._prompts_dir}"
                )

            self._env = Environment(
                loader=FileSystemLoader(str(self._prompts_dir)),
                # Keep whitespace as-is for prompt formatting
                trim_blocks=False,
                lstrip_blocks=False,
                # Auto-escape disabled (prompts are not HTML)
                autoescape=False,
                # Raise error on undefined variables
                undefined=StrictUndefined,
            )

            logger.debug(
                "Jinja2 environment created",
                prompts_dir=str(self._prompts_dir),
            )

        return self._env

    def get_template_path(self, template_name: str) -> Path:
        """
        Get the path to a template file.

        Args:
            template_name: Template name (without .j2 extension).

        Returns:
            Full path to the template file.
        """
        return self._prompts_dir / f"{template_name}.j2"

    def template_exists(self, template_name: str) -> bool:
        """
        Check if a template exists.

        Args:
            template_name: Template name (without .j2 extension).

        Returns:
            True if template exists, False otherwise.
        """
        return self.get_template_path(template_name).exists()

    def list_templates(self) -> list[str]:
        """
        List all available templates.

        Returns:
            List of template names (without .j2 extension).
        """
        if not self._prompts_dir.exists():
            return []

        return [
            p.stem for p in self._prompts_dir.glob("*.j2")
        ]

    def render(self, template_name: str, **kwargs: Any) -> str:
        """
        Render a prompt template with given variables.

        Args:
            template_name: Template name (without .j2 extension).
            **kwargs: Variables to inject into the template.

        Returns:
            Rendered prompt string.

        Raises:
            TemplateNotFoundError: If template doesn't exist.
            TemplateRenderError: If rendering fails (e.g., missing variables).
        """
        try:
            env = self._get_environment()
            template = env.get_template(f"{template_name}.j2")

            rendered = template.render(**kwargs)

            logger.debug(
                "Template rendered",
                template=template_name,
                vars=list(kwargs.keys()),
                length=len(rendered),
            )

            return rendered

        except TemplateNotFound:
            raise TemplateNotFoundError(
                f"Template not found: {template_name}.j2 "
                f"(searched in {self._prompts_dir})"
            )
        except TemplateNotFoundError:
            # Re-raise our own TemplateNotFoundError (from _get_environment)
            raise
        except UndefinedError as e:
            raise TemplateRenderError(
                f"Template '{template_name}' rendering failed: {e}"
            )
        except Exception as e:
            raise TemplateRenderError(
                f"Template '{template_name}' rendering failed: {e}"
            )

    def clear_cache(self) -> None:
        """Clear the template cache."""
        if self._env is not None:
            # Reset environment to clear cached templates
            self._env = None
            logger.debug("Template cache cleared")


# ============================================================================
# Module-level singleton
# ============================================================================

_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """
    Get the global PromptManager instance.

    Returns:
        PromptManager singleton instance.
    """
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


def reset_prompt_manager() -> None:
    """Reset the global PromptManager instance (for testing)."""
    global _prompt_manager
    _prompt_manager = None


# ============================================================================
# Convenience function
# ============================================================================

def render_prompt(template_name: str, **kwargs: Any) -> str:
    """
    Render a prompt template using the global PromptManager.

    Convenience function equivalent to:
        get_prompt_manager().render(template_name, **kwargs)

    Args:
        template_name: Template name (without .j2 extension).
        **kwargs: Variables to inject into the template.

    Returns:
        Rendered prompt string.

    Raises:
        TemplateNotFoundError: If template doesn't exist.
        TemplateRenderError: If rendering fails.
    """
    return get_prompt_manager().render(template_name, **kwargs)
