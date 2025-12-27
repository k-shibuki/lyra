"""Shared fixtures for prompt template tests.

Provides common fixtures for testing Jinja2 templates:
- prompt_manager: Real PromptManager instance
- template_names: List of all template names
- sample_inputs: Sample input data for each template
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from src.utils.prompt_manager import PromptManager


@pytest.fixture
def prompt_manager() -> Generator[PromptManager]:
    """Provide a PromptManager instance for testing."""
    manager = PromptManager()
    yield manager


@pytest.fixture
def template_dir() -> Path:
    """Return the path to the prompts directory."""
    return Path("config/prompts")


@pytest.fixture
def all_template_names(prompt_manager: PromptManager) -> list[str]:
    """Return list of all available template names."""
    return prompt_manager.list_templates()


@pytest.fixture
def sample_inputs() -> dict[str, dict]:
    """Provide sample input data for each template.

    Returns a dict mapping template name to required input variables.
    """
    return {
        "extract_facts": {
            "text": "DPP-4 inhibitors reduced HbA1c by 0.5-1.0% in clinical trials.",
        },
        "extract_claims": {
            "text": "Studies show that regular exercise improves cardiovascular health.",
            "context": "What are the health benefits of exercise?",
        },
        "summarize": {
            "text": "This is a long document that needs to be summarized. "
            "It contains multiple sentences and paragraphs with various information.",
            "max_words": 50,
        },
        "translate": {
            "text": "Hello, world!",
            "target_lang": "Japanese",
        },
        "decompose": {
            "question": "What are the effects of climate change on biodiversity?",
        },
        "detect_citation": {
            "context": "According to Smith et al. (2023), the study found...",
            "url": "https://doi.org/10.1234/example",
            "link_text": "Smith et al., 2023",
        },
        "relevance_evaluation": {
            "query": "What is the effect of drug X on blood pressure?",
            "source_abstract": "This study examines the pharmacokinetics of drug X...",
            "target_abstract": "A meta-analysis of blood pressure treatments...",
        },
        "densify": {
            "current_summary": "Initial summary of the research findings.",
            "original_content": "Full original content with detailed information.",
            "missing_entities": "Entity1, Entity2, Entity3",
        },
        "initial_summary": {
            "content": "Research content to be summarized for evidence graph.",
        },
        "quality_assessment": {
            "text": "Sample web content to assess for quality and credibility.",
        },
    }


@pytest.fixture
def json_output_templates() -> list[str]:
    """Return list of templates that should produce JSON output."""
    return [
        "extract_facts",
        "extract_claims",
        "decompose",
        "densify",
        "initial_summary",
        "quality_assessment",
    ]
