"""
LLM-based extraction for Lyra.
Uses local Ollama models for fact/claim extraction and summarization.

LLM processes are destroyed after task completion to prevent memory leaks.
Per ADR-0005 L4: LLM output is validated for prompt leakage and suspicious content.

This module provides high-level LLM extraction functions that use the LLMProvider
abstraction layer. The provider can be configured or switched at runtime.
"""

import json
import re
from typing import Any

from src.filter.llm_security import validate_llm_output
from src.filter.ollama_provider import OllamaProvider, create_ollama_provider
from src.filter.provider import (
    ChatMessage,
    LLMOptions,
    LLMProvider,
    get_llm_registry,
    reset_llm_registry,
)
from src.utils.config import get_settings
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
# OllamaClient Facade
# ============================================================================


class OllamaClient:
    """
    Thin facade for OllamaProvider.

    Per , LLM processes should be released after task completion.
    Prefer LLMProvider directly for new code.
    """

    def __init__(self) -> None:
        self._provider: OllamaProvider | None = None
        self._settings = get_settings()

    def _get_provider(self) -> OllamaProvider:
        """Get or create Ollama provider."""
        if self._provider is None:
            self._provider = create_ollama_provider()
        return self._provider

    @property
    def _current_task_id(self) -> str | None:
        """Get current task ID from provider."""
        if self._provider is None:
            return None
        return self._provider._current_task_id

    @_current_task_id.setter
    def _current_task_id(self, value: str | None) -> None:
        """Set current task ID on provider."""
        provider = self._get_provider()
        provider._current_task_id = value

    @property
    def _current_model(self) -> str | None:
        """Get current model from provider."""
        if self._provider is None:
            return None
        return self._provider._current_model

    @_current_model.setter
    def _current_model(self, value: str | None) -> None:
        """Set current model on provider."""
        provider = self._get_provider()
        provider._current_model = value

    def set_task_id(self, task_id: str | None) -> None:
        """Set current task ID for lifecycle tracking."""
        provider = self._get_provider()
        provider.set_task_id(task_id)

    async def close(self) -> None:
        """Close HTTP session."""
        if self._provider is not None:
            await self._provider.close()

    async def unload_model(self, model: str | None = None) -> bool:
        """Unload model to free VRAM."""
        if self._provider is None:
            return False
        return await self._provider.unload_model(model)

    async def cleanup_for_task(self, unload_model: bool = True) -> None:
        """Cleanup resources after task completion."""
        if unload_model and self._settings.llm.unload_on_task_complete:
            await self.unload_model()
        if self._provider:
            self._provider.set_task_id(None)

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate completion from Ollama."""
        provider = self._get_provider()

        options = LLMOptions(
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        response = await provider.generate(prompt, options)

        if not response.ok:
            raise RuntimeError(f"Ollama error: {response.error}")

        return response.text

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Chat completion from Ollama."""
        provider = self._get_provider()

        # Convert dict messages to ChatMessage objects
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
            raise RuntimeError(f"Ollama error: {response.error}")

        return response.text


# Global client (module-level singleton)
_client: OllamaClient | None = None


def _get_client() -> OllamaClient:
    """Get or create Ollama client (legacy)."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


async def _cleanup_client() -> None:
    """Close and cleanup the global Ollama client."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def cleanup_llm_for_task(task_id: str | None = None) -> None:
    """
    Cleanup LLM resources after task completion.

    LLM processes should be released after task completion.
    """
    global _client
    if _client is not None:
        logger.info("Cleaning up LLM resources for task", task_id=task_id)
        await _client.cleanup_for_task(unload_model=True)


def set_llm_task_id(task_id: str | None) -> None:
    """Set current task ID for LLM lifecycle tracking."""
    global _client
    if _client is not None:
        _client.set_task_id(task_id)


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
EXTRACT_FACTS_INSTRUCTION = """あなたは情報抽出の専門家です。以下のテキストから客観的な事実を抽出してください。
抽出した事実をJSON配列形式で出力してください。各事実は以下の形式で:
{"fact": "事実の内容", "confidence": 0.0-1.0の信頼度}
事実のみを出力し、意見や推測は含めないでください。"""

EXTRACT_CLAIMS_INSTRUCTION = """あなたは情報分析の専門家です。以下のテキストから主張を抽出してください。
抽出した主張をJSON配列形式で出力してください。各主張は以下の形式で:
{"claim": "主張の内容", "type": "fact|opinion|prediction", "confidence": 0.0-1.0}"""

SUMMARIZE_INSTRUCTION = (
    """以下のテキストを要約してください。重要なポイントを簡潔にまとめてください。"""
)

TRANSLATE_INSTRUCTION = """以下のテキストを翻訳してください。"""

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
    use_provider: bool = True,
) -> dict[str, Any]:
    """
    Extract information using LLM.

    Args:
        passages: List of passage dicts with 'id' and 'text'.
        task: Task type (extract_facts, extract_claims, summarize, translate).
        context: Additional context (e.g., research question).
        use_provider: Whether to use the new provider API (default: True).

    Returns:
        Extraction result.

    Note:
        Per ADR-0004: Single 3B model is used for all LLM tasks.
    """
    settings = get_settings()

    if use_provider:
        # Use new provider-based API
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
                options = LLMOptions(model=model)
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
                        fragment_count=validation_result.leakage_result.total_leaks
                        if validation_result.leakage_result
                        else 1,
                    )
                response_text = validation_result.validated_text

                # Parse response based on task
                if task in ("extract_facts", "extract_claims"):
                    try:
                        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                        if json_match:
                            extracted = json.loads(json_match.group())
                        else:
                            extracted = []
                    except json.JSONDecodeError:
                        extracted = [{"raw_response": response_text}]

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
    else:
        # Legacy path using OllamaClient
        client = _get_client()
        model = settings.llm.model

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
                response_text = await client.generate(prompt, model=model)

                # Validate LLM output per ADR-0005 L4
                # Use instruction-only template to avoid false positives from user text
                validation_result = validate_llm_output(
                    response_text,
                    system_prompt=TASK_INSTRUCTIONS.get(task),
                    mask_leakage=True,
                )
                if validation_result.leakage_detected:
                    # L8: Use audit logger for security events (legacy path)
                    audit_logger.log_prompt_leakage(
                        source="llm_extract_legacy",
                        fragment_count=validation_result.leakage_result.total_leaks
                        if validation_result.leakage_result
                        else 1,
                    )
                response_text = validation_result.validated_text

                if task in ("extract_facts", "extract_claims"):
                    try:
                        json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                        if json_match:
                            extracted = json.loads(json_match.group())
                        else:
                            extracted = []
                    except json.JSONDecodeError:
                        extracted = [{"raw_response": response_text}]

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
    # Cleanup legacy client
    await _cleanup_client()

    # Cleanup registry
    from src.filter.provider import cleanup_llm_registry

    await cleanup_llm_registry()


def reset_for_testing() -> None:
    """
    Reset module state for testing.

    For testing purposes only.
    """
    global _client
    _client = None
    reset_llm_registry()
