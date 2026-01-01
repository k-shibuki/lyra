"""
LLM-based extraction for Lyra.
Uses local Ollama models for fact/claim extraction and summarization.

LLM processes are destroyed after task completion to prevent memory leaks.
Per ADR-0005 L4: LLM output is validated for prompt leakage and suspicious content.

This module provides high-level LLM extraction functions that use the LLMProvider
abstraction layer. The provider can be configured or switched at runtime.
"""

from typing import Any

from src.filter.llm_output import parse_and_validate
from src.filter.llm_schemas import ExtractedClaim, ExtractedFact
from src.filter.llm_security import validate_llm_output
from src.filter.ollama_provider import create_ollama_provider
from src.filter.provider import (
    ChatMessage,
    LLMOptions,
    LLMProvider,
    get_llm_registry,
    reset_llm_registry,
)
from src.utils.logging import get_logger
from src.utils.prompt_manager import render_prompt
from src.utils.secure_logging import (
    get_audit_logger,
    get_secure_logger,
)

logger = get_logger(__name__)
secure_logger = get_secure_logger(__name__)
audit_logger = get_audit_logger()


# ============================================================================
# JSON Schema definitions for structured output
# ============================================================================

# Schema for extract_claims task - forces array output
EXTRACT_CLAIMS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "claim": {"type": "string"},
            "type": {"type": "string", "enum": ["fact", "opinion", "prediction"]},
            "relevance_to_query": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["claim"],
    },
}

# Schema for extract_facts task - forces array output
EXTRACT_FACTS_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "fact": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "evidence_type": {"type": "string", "enum": ["statistic", "citation", "observation"]},
        },
        "required": ["fact"],
    },
}


def _get_response_format_for_task(task: str) -> str | dict | None:
    """Get appropriate response format for task.

    Uses JSON Schema for array-output tasks to enforce correct structure.
    """
    if task == "extract_claims":
        return EXTRACT_CLAIMS_SCHEMA
    elif task == "extract_facts":
        return EXTRACT_FACTS_SCHEMA
    elif task in ("decompose",):
        return "json"  # Use simple json format for complex schemas
    return None




# ============================================================================
# Provider-based Functions (New API)
# ============================================================================


def _get_provider() -> LLMProvider:
    """
    Get the default LLM provider.

    Initializes the registry with Ollama provider if not already done.

    Returns:
        The default LLM provider.

    Raises:
        RuntimeError: If no provider is available.
    """
    registry = get_llm_registry()

    # Auto-register Ollama provider if registry is empty
    if not registry.list_providers():
        provider = create_ollama_provider()
        registry.register(provider, set_default=True)

    default = registry.get_default()
    if default is None:
        raise RuntimeError("No LLM provider available")

    return default


async def generate_with_provider(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: str | dict | None = None,
    provider_name: str | None = None,
) -> str:
    """
    Generate text using the LLM provider abstraction.

    Args:
        prompt: Input prompt.
        model: Model name (uses provider default if not specified).
        system: System prompt.
        temperature: Generation temperature.
        max_tokens: Maximum tokens to generate.
        response_format: Response format (e.g., "json" or JSON schema dict).
        provider_name: Specific provider to use (default provider if not specified).

    Returns:
        Generated text.

    Raises:
        RuntimeError: If generation fails.
    """
    registry = get_llm_registry()

    # Get provider
    if provider_name:
        provider = registry.get(provider_name)
        if provider is None:
            raise RuntimeError(f"Provider '{provider_name}' not found")
    else:
        provider = _get_provider()

    options = LLMOptions(
        model=model,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )

    response = await provider.generate(prompt, options)

    if not response.ok:
        raise RuntimeError(f"LLM generation failed: {response.error}")

    return response.text


async def chat_with_provider(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    provider_name: str | None = None,
) -> str:
    """
    Chat completion using the LLM provider abstraction.

    Args:
        messages: List of message dicts with 'role' and 'content'.
        model: Model name.
        temperature: Generation temperature.
        provider_name: Specific provider to use.

    Returns:
        Assistant response.
    """
    registry = get_llm_registry()

    if provider_name:
        provider = registry.get(provider_name)
        if provider is None:
            raise RuntimeError(f"Provider '{provider_name}' not found")
    else:
        provider = _get_provider()

    chat_messages = [
        ChatMessage(
            role=m.get("role", "user"),
            content=m.get("content", ""),
        )
        for m in messages
    ]

    options = LLMOptions(
        model=model,
        temperature=temperature,
    )

    response = await provider.chat(chat_messages, options)

    if not response.ok:
        raise RuntimeError(f"LLM chat failed: {response.error}")

    return response.text


# ============================================================================
# Prompt Templates (External)
# ============================================================================
# Prompt templates are externalized to config/prompts/*.j2
# Use render_prompt() to render templates with variables.
# Template names: extract_facts, extract_claims, summarize, translate

# Instruction-only templates for leakage detection (ADR-0005 L4)
# These exclude user-provided text to avoid false positive leakage detection
# Note: Use single braces here (not double) since these are NOT f-string templates.
# These templates are used for n-gram matching against LLM output.
EXTRACT_FACTS_INSTRUCTION = """You are an expert in information extraction. Extract objective facts from the following text.
Output the extracted facts in JSON array format. Each fact should follow this format:
{"fact": "fact content", "confidence": 0.0-1.0 confidence level}
Output only facts, do not include opinions or speculations."""

EXTRACT_CLAIMS_INSTRUCTION = """You are an expert in information analysis. Extract claims from the following text.
Output the extracted claims in JSON array format. Each claim should follow this format:
{"claim": "claim content", "type": "fact|opinion|prediction", "confidence": 0.0-1.0}"""

SUMMARIZE_INSTRUCTION = """Summarize the following text. Concisely summarize the key points."""

TRANSLATE_INSTRUCTION = """Translate the following text."""

# Mapping from task to instruction template for leakage detection
TASK_INSTRUCTIONS: dict[str, str] = {
    "extract_facts": EXTRACT_FACTS_INSTRUCTION,
    "extract_claims": EXTRACT_CLAIMS_INSTRUCTION,
    "summarize": SUMMARIZE_INSTRUCTION,
    "translate": TRANSLATE_INSTRUCTION,
}


# ============================================================================
# High-level Extraction Functions
# ============================================================================


async def llm_extract(
    passages: list[dict[str, Any]],
    task: str,
    context: str | None = None,
) -> dict[str, Any]:
    """
    Extract information using LLM.

    Args:
        passages: List of passage dicts with 'id' and 'text'.
        task: Task type (extract_facts, extract_claims, summarize, translate).
        context: Additional context (e.g., research question).

    Returns:
        Extraction result.

    Note:
        Per ADR-0004: Single 3B model is used for all LLM tasks.
    """
    # Use provider-based API
    registry = get_llm_registry()

    # Auto-register if needed
    if not registry.list_providers():
        provider = create_ollama_provider()
        registry.register(provider, set_default=True)

    default_provider = registry.get_default()
    if default_provider is None:
        raise RuntimeError("No LLM provider available")

    # Use single model (per ADR-0004)
    model = None
    if hasattr(default_provider, "model"):
        model = default_provider.model

    results = []

    for passage in passages:
        passage_id = passage.get("id", "unknown")
        text = passage.get("text", "")
        source_url = passage.get("source_url", "")

        # Select and render prompt template based on task
        if task == "extract_facts":
            prompt = render_prompt("extract_facts", text=text[:4000])
        elif task == "extract_claims":
            prompt = render_prompt(
                "extract_claims",
                text=text[:4000],
                context=context or "一般的な調査",
            )
        elif task == "summarize":
            prompt = render_prompt("summarize", text=text[:4000])
        elif task == "translate":
            target_lang = context or "英語"
            prompt = render_prompt(
                "translate",
                text=text[:4000],
                target_lang=target_lang,
            )
        else:
            raise ValueError(f"Unknown task: {task}")

        try:
            response_format = _get_response_format_for_task(task)
            options = LLMOptions(model=model, response_format=response_format)
            response = await default_provider.generate(prompt, options)

            if not response.ok:
                results.append(
                    {
                        "id": passage_id,
                        "error": response.error,
                    }
                )
                continue

            response_text = response.text

            # Validate LLM output per ADR-0005 L4
            # Use instruction-only template to avoid false positives from user text
            validation_result = validate_llm_output(
                response_text,
                system_prompt=TASK_INSTRUCTIONS.get(task),
                mask_leakage=True,
            )
            if validation_result.leakage_detected:
                # L8: Use audit logger for security events
                audit_logger.log_prompt_leakage(
                    source="llm_extract",
                    fragment_count=(
                        validation_result.leakage_result.total_leaks
                        if validation_result.leakage_result
                        else 1
                    ),
                )
            response_text = validation_result.validated_text

            # Parse response based on task
            if task in ("extract_facts", "extract_claims"):
                schema = ExtractedFact if task == "extract_facts" else ExtractedClaim

                async def _retry_llm_call(retry_prompt: str) -> str:
                    retry_response = await default_provider.generate(
                        retry_prompt,
                        LLMOptions(model=model, response_format="json"),
                    )
                    if not retry_response.ok:
                        raise RuntimeError(retry_response.error or "LLM retry failed")

                    retry_validation = validate_llm_output(
                        retry_response.text,
                        system_prompt=TASK_INSTRUCTIONS.get(task),
                        mask_leakage=True,
                    )
                    if retry_validation.leakage_detected:
                        audit_logger.log_prompt_leakage(
                            source="llm_extract_retry",
                            fragment_count=(
                                retry_validation.leakage_result.total_leaks
                                if retry_validation.leakage_result
                                else 1
                            ),
                        )
                    return retry_validation.validated_text

                validated = await parse_and_validate(
                    response=response_text,
                    schema=schema,
                    template_name=task,
                    expect_array=True,
                    llm_call=_retry_llm_call,
                    max_retries=1,
                    context={
                        "passage_id": passage_id,
                        "source_url": source_url,
                        "task": task,
                    },
                )

                if validated is None:
                    extracted = [{"raw_response": response_text}]
                else:
                    extracted = [m.model_dump() for m in validated]

                results.append(
                    {
                        "id": passage_id,
                        "source_url": source_url,
                        "extracted": extracted,
                    }
                )
            else:
                results.append(
                    {
                        "id": passage_id,
                        "source_url": source_url,
                        "result": response_text.strip(),
                    }
                )

        except Exception as e:
            # L8: Use secure logger for exception handling
            sanitized = secure_logger.log_exception(
                e,
                context={"passage_id": passage_id, "task": task},
            )
            results.append(
                {
                    "id": passage_id,
                    "error": sanitized.sanitized_message,
                }
            )

    # Aggregate results
    if task == "extract_facts":
        all_facts = []
        for r in results:
            for fact in r.get("extracted", []):
                if isinstance(fact, dict):
                    fact["source_passage_id"] = r["id"]
                    fact["source_url"] = r.get("source_url", "")
                    all_facts.append(fact)

        return {
            "ok": True,
            "task": task,
            "facts": all_facts,
            "passage_results": results,
        }

    elif task == "extract_claims":
        all_claims = []
        for r in results:
            for claim in r.get("extracted", []):
                if isinstance(claim, dict):
                    claim["source_passage_id"] = r["id"]
                    claim["source_url"] = r.get("source_url", "")
                    all_claims.append(claim)

        return {
            "ok": True,
            "task": task,
            "claims": all_claims,
            "passage_results": results,
        }

    else:
        return {
            "ok": True,
            "task": task,
            "results": results,
        }


# ============================================================================
# Module-level Cleanup
# ============================================================================


async def cleanup_all_providers() -> None:
    """
    Cleanup all LLM providers and the global registry.

    Should be called during application shutdown.
    """
    # Cleanup registry
    from src.filter.provider import cleanup_llm_registry

    await cleanup_llm_registry()


def reset_for_testing() -> None:
    """
    Reset module state for testing.

    For testing purposes only.
    """
    reset_llm_registry()
