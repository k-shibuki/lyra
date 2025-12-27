"""
Ollama LLM provider implementation for Lyra.

Implements the LLMProvider interface for Ollama backend.

LLM processes are destroyed after task completion to prevent memory leaks.
"""

import time
from datetime import datetime
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from src.filter.provider import (
    BaseLLMProvider,
    ChatMessage,
    EmbeddingResponse,
    LLMHealthStatus,
    LLMOptions,
    LLMResponse,
    LLMResponseStatus,
    ModelCapability,
    ModelInfo,
)
from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OllamaProvider(BaseLLMProvider):
    """
    Ollama LLM provider.

    Implements the LLMProvider interface for local Ollama models.
    Supports:
    - Text generation (generate)
    - Chat completion (chat)
    - Embeddings (embed)
    - Model listing and info
    - Model unloading for VRAM management

    Supports task-scoped lifecycle management with model unloading.
    Per ADR-0004: Uses single 3B model for all LLM tasks.

    Example:
        provider = OllamaProvider()

        # Generate text
        response = await provider.generate("Hello, world!")

        # Chat
        messages = [ChatMessage(role="user", content="Hi")]
        response = await provider.chat(messages)

        # Cleanup
        await provider.unload_model()
        await provider.close()
    """

    DEFAULT_MODEL = "qwen2.5:3b"  # Single model per ADR-0004
    DEFAULT_EMBED_MODEL = "nomic-embed-text"

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        timeout: float = 120.0,
    ):
        """
        Initialize Ollama provider.

        Args:
            host: Ollama API host URL (default: from settings, respects execution_mode).
            model: Model name for all tasks (default: from settings).
            embed_model: Model for embeddings (default: nomic-embed-text).
            timeout: Default request timeout in seconds.
        """
        super().__init__("ollama")

        settings = get_settings()

        # Determine host: always use proxy URL in hybrid mode
        if host:
            self._host = host
        else:
            # Hybrid mode: use proxy URL
            self._host = f"{settings.general.proxy_url}/ollama"
            logger.debug("Using proxy for Ollama", proxy_url=self._host)

        self._model = model or settings.llm.model or self.DEFAULT_MODEL
        self._embed_model = embed_model or self.DEFAULT_EMBED_MODEL
        self._timeout = timeout
        self._default_temperature = settings.llm.temperature

        self._session: aiohttp.ClientSession | None = None
        self._current_model: str | None = None

        # Metrics tracking
        self._request_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            )
        return self._session

    def _get_model(self, options: LLMOptions | None) -> str:
        """Get model to use based on options."""
        if options and options.model:
            return options.model
        return self._model

    def _get_temperature(self, options: LLMOptions | None) -> float:
        """Get temperature from options or default."""
        if options and options.temperature is not None:
            return options.temperature
        return self._default_temperature

    async def generate(
        self,
        prompt: str,
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        """
        Generate text completion.

        Args:
            prompt: Input prompt text.
            options: Generation options.

        Returns:
            LLMResponse with generated text or error.
        """
        self._check_closed()

        session = await self._get_session()
        model = self._get_model(options)
        temperature = self._get_temperature(options)

        # Track current model for cleanup
        self._current_model = model

        url = f"{self._host}/api/generate"

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if options:
            if options.system:
                payload["system"] = options.system
            if options.response_format:
                # Ollama supports {"format":"json"} to force valid JSON output.
                # Keep this optional and provider-specific.
                payload["format"] = options.response_format
            if options.max_tokens:
                payload["options"]["num_predict"] = options.max_tokens
            if options.top_p is not None:
                payload["options"]["top_p"] = options.top_p
            if options.top_k is not None:
                payload["options"]["top_k"] = options.top_k
            if options.stop:
                # Ollama expects stop sequences under "options".
                payload["options"]["stop"] = options.stop

        start_time = time.perf_counter()
        self._request_count += 1

        try:
            timeout = aiohttp.ClientTimeout(
                total=options.timeout if options and options.timeout else self._timeout
            )

            async with session.post(url, json=payload, timeout=timeout) as response:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._total_latency_ms += elapsed_ms

                if response.status != 200:
                    self._error_count += 1
                    error_text = await response.text()
                    # Fallback: if response_format is rejected by the server/proxy, retry once without it.
                    if options and options.response_format and "format" in payload:
                        try:
                            logger.warning(
                                "Ollama generate rejected response_format; retrying without format",
                                status=response.status,
                                error=error_text[:200],
                                response_format=options.response_format,
                            )
                            payload.pop("format", None)
                            async with session.post(url, json=payload, timeout=timeout) as retry_resp:
                                if retry_resp.status == 200:
                                    data = await retry_resp.json()
                                    text = data.get("response", "")
                                    usage = {}
                                    if "prompt_eval_count" in data:
                                        usage["prompt_tokens"] = data["prompt_eval_count"]
                                    if "eval_count" in data:
                                        usage["completion_tokens"] = data["eval_count"]
                                    if usage:
                                        usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
                                            "completion_tokens", 0
                                        )
                                    return LLMResponse.success(
                                        text=text,
                                        model=model,
                                        provider=self._name,
                                        elapsed_ms=elapsed_ms,
                                        usage=usage,
                                    )
                                # If retry also fails, fall through to regular error.
                        except Exception:
                            pass
                    logger.error(
                        "Ollama generate error",
                        status=response.status,
                        error=error_text,
                    )
                    return LLMResponse.make_error(
                        error=f"Ollama error {response.status}: {error_text}",
                        model=model,
                        provider=self._name,
                    )

                data = await response.json()
                text = data.get("response", "")

                # Extract usage info
                usage = {}
                if "prompt_eval_count" in data:
                    usage["prompt_tokens"] = data["prompt_eval_count"]
                if "eval_count" in data:
                    usage["completion_tokens"] = data["eval_count"]
                if usage:
                    usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
                        "completion_tokens", 0
                    )

                return LLMResponse.success(
                    text=text,
                    model=model,
                    provider=self._name,
                    elapsed_ms=elapsed_ms,
                    usage=usage,
                )

        except aiohttp.ClientError as e:
            self._error_count += 1
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._total_latency_ms += elapsed_ms

            logger.error("Ollama request failed", error=str(e))

            if isinstance(e, aiohttp.ServerTimeoutError):
                return LLMResponse.make_error(
                    error=f"Request timeout after {timeout.total}s",
                    model=model,
                    provider=self._name,
                    status=LLMResponseStatus.TIMEOUT,
                )

            return LLMResponse.make_error(
                error=str(e),
                model=model,
                provider=self._name,
            )
        except Exception as e:
            self._error_count += 1
            logger.error("Ollama request failed", error=str(e))
            return LLMResponse.make_error(
                error=str(e),
                model=model,
                provider=self._name,
            )

    async def chat(
        self,
        messages: list[ChatMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        """
        Generate chat completion.

        Args:
            messages: List of chat messages.
            options: Generation options.

        Returns:
            LLMResponse with assistant response or error.
        """
        self._check_closed()

        session = await self._get_session()
        model = self._get_model(options)
        temperature = self._get_temperature(options)

        self._current_model = model

        url = f"{self._host}/api/chat"

        # Convert ChatMessage objects to dicts
        messages_dict = [m.to_dict() for m in messages]

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages_dict,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        if options:
            if options.response_format:
                payload["format"] = options.response_format
            if options.max_tokens:
                payload["options"]["num_predict"] = options.max_tokens
            if options.top_p is not None:
                payload["options"]["top_p"] = options.top_p
            if options.top_k is not None:
                payload["options"]["top_k"] = options.top_k
            if options.stop:
                payload["options"]["stop"] = options.stop

        start_time = time.perf_counter()
        self._request_count += 1

        try:
            timeout = aiohttp.ClientTimeout(
                total=options.timeout if options and options.timeout else self._timeout
            )

            async with session.post(url, json=payload, timeout=timeout) as response:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._total_latency_ms += elapsed_ms

                if response.status != 200:
                    self._error_count += 1
                    error_text = await response.text()
                    logger.error(
                        "Ollama chat error",
                        status=response.status,
                        error=error_text,
                    )
                    return LLMResponse.make_error(
                        error=f"Ollama error {response.status}: {error_text}",
                        model=model,
                        provider=self._name,
                    )

                data = await response.json()
                text = data.get("message", {}).get("content", "")

                usage = {}
                if "prompt_eval_count" in data:
                    usage["prompt_tokens"] = data["prompt_eval_count"]
                if "eval_count" in data:
                    usage["completion_tokens"] = data["eval_count"]
                if usage:
                    usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
                        "completion_tokens", 0
                    )

                return LLMResponse.success(
                    text=text,
                    model=model,
                    provider=self._name,
                    elapsed_ms=elapsed_ms,
                    usage=usage,
                )

        except aiohttp.ClientError as e:
            self._error_count += 1
            logger.error("Ollama chat request failed", error=str(e))

            if isinstance(e, aiohttp.ServerTimeoutError):
                return LLMResponse.make_error(
                    error="Request timeout",
                    model=model,
                    provider=self._name,
                    status=LLMResponseStatus.TIMEOUT,
                )

            return LLMResponse.make_error(
                error=str(e),
                model=model,
                provider=self._name,
            )
        except Exception as e:
            self._error_count += 1
            logger.error("Ollama chat request failed", error=str(e))
            return LLMResponse.make_error(
                error=str(e),
                model=model,
                provider=self._name,
            )

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> EmbeddingResponse:
        """
        Generate embeddings for texts.

        Args:
            texts: List of texts to embed.
            model: Model name for embedding.

        Returns:
            EmbeddingResponse with embedding vectors or error.
        """
        self._check_closed()

        session = await self._get_session()
        embed_model = model or self._embed_model

        url = f"{self._host}/api/embed"

        start_time = time.perf_counter()
        self._request_count += 1

        try:
            payload = {
                "model": embed_model,
                "input": texts,
            }

            async with session.post(url, json=payload) as response:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._total_latency_ms += elapsed_ms

                if response.status != 200:
                    self._error_count += 1
                    error_text = await response.text()
                    return EmbeddingResponse.error_response(
                        error=f"Ollama embed error {response.status}: {error_text}",
                        model=embed_model,
                        provider=self._name,
                    )

                data = await response.json()
                embeddings = data.get("embeddings", [])

                return EmbeddingResponse.success(
                    embeddings=embeddings,
                    model=embed_model,
                    provider=self._name,
                    elapsed_ms=elapsed_ms,
                )

        except Exception as e:
            self._error_count += 1
            logger.error("Ollama embed request failed", error=str(e))
            return EmbeddingResponse.error_response(
                error=str(e),
                model=embed_model,
                provider=self._name,
            )

    async def get_model_info(self, model: str) -> ModelInfo | None:
        """
        Get information about a specific model.

        Args:
            model: Model name.

        Returns:
            ModelInfo or None if model not found.
        """
        self._check_closed()

        session = await self._get_session()
        url = f"{self._host}/api/show"

        try:
            async with session.post(url, json={"name": model}) as response:
                if response.status != 200:
                    return None

                data = await response.json()

                # Parse model details
                details = data.get("details", {})
                parameter_size = details.get("parameter_size", "")
                quantization = details.get("quantization_level")

                # Determine capabilities
                capabilities = [ModelCapability.TEXT_GENERATION, ModelCapability.CHAT]
                families = details.get("families", [])
                if "embed" in model.lower() or "embedding" in families:
                    capabilities.append(ModelCapability.EMBEDDING)
                if "code" in model.lower():
                    capabilities.append(ModelCapability.CODE)

                # Parse modified_at
                modified_at = None
                if "modified_at" in data:
                    try:
                        modified_at = datetime.fromisoformat(
                            data["modified_at"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass

                return ModelInfo(
                    name=model,
                    size=parameter_size,
                    capabilities=capabilities,
                    quantization=quantization,
                    context_length=data.get("model_info", {}).get("context_length", 4096),
                    modified_at=modified_at,
                    details=details,
                )

        except Exception as e:
            logger.error("Failed to get model info", model=model, error=str(e))
            return None

    async def list_models(self) -> list[ModelInfo]:
        """
        List all available models.

        Returns:
            List of ModelInfo for available models.
        """
        self._check_closed()

        session = await self._get_session()
        url = f"{self._host}/api/tags"

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                models = []

                for model_data in data.get("models", []):
                    name = model_data.get("name", "")
                    details = model_data.get("details", {})

                    # Parse modified_at
                    modified_at = None
                    if "modified_at" in model_data:
                        try:
                            modified_at = datetime.fromisoformat(
                                model_data["modified_at"].replace("Z", "+00:00")
                            )
                        except (ValueError, AttributeError):
                            pass

                    models.append(
                        ModelInfo(
                            name=name,
                            size=details.get("parameter_size", ""),
                            capabilities=[ModelCapability.TEXT_GENERATION, ModelCapability.CHAT],
                            quantization=details.get("quantization_level"),
                            modified_at=modified_at,
                            details=details,
                        )
                    )

                return models

        except Exception as e:
            logger.error("Failed to list models", error=str(e))
            return []

    async def get_health(self) -> LLMHealthStatus:
        """
        Get current health status.

        Returns:
            LLMHealthStatus indicating provider health.
        """
        if self._is_closed:
            return LLMHealthStatus.unhealthy("Provider is closed")

        try:
            session = await self._get_session()

            # Check if Ollama is reachable
            start_time = time.perf_counter()
            async with session.get(
                f"{self._host}/api/tags", timeout=ClientTimeout(total=5)
            ) as response:
                latency_ms = (time.perf_counter() - start_time) * 1000

                if response.status != 200:
                    return LLMHealthStatus.unhealthy(f"API returned {response.status}")

                data = await response.json()
                available_models = [m.get("name", "") for m in data.get("models", [])]

                # Calculate success rate
                success_rate = 1.0
                if self._request_count > 0:
                    success_rate = 1.0 - (self._error_count / self._request_count)

                # Determine health state
                if success_rate < 0.5:
                    return LLMHealthStatus.degraded(
                        success_rate=success_rate,
                        message=f"High error rate: {self._error_count}/{self._request_count}",
                    )

                return LLMHealthStatus.healthy(
                    available_models=available_models,
                    loaded_models=[self._current_model] if self._current_model else [],
                    latency_ms=latency_ms,
                )

        except aiohttp.ClientError as e:
            return LLMHealthStatus.unhealthy(f"Connection failed: {str(e)}")
        except Exception as e:
            return LLMHealthStatus.unhealthy(str(e))

    async def unload_model(self, model: str | None = None) -> bool:
        """
        Unload model to free VRAM.

        LLM process context should be released after task completion.

        Args:
            model: Model name to unload (uses current model if not specified).

        Returns:
            True if unload was successful.
        """
        model = model or self._current_model
        if not model:
            return False

        try:
            session = await self._get_session()
            url = f"{self._host}/api/generate"

            # Ollama API: POST with keep_alive=0 unloads the model
            payload = {
                "model": model,
                "prompt": "",
                "keep_alive": 0,  # Unload immediately
            }

            async with session.post(url, json=payload, timeout=ClientTimeout(total=10)) as response:
                if response.status == 200:
                    logger.info("Ollama model unloaded", model=model)
                    self._current_model = None
                    return True
                else:
                    logger.debug(
                        "Ollama model unload returned non-200",
                        model=model,
                        status=response.status,
                    )
                    return False

        except Exception as e:
            logger.debug(
                "Ollama model unload failed (may be expected)",
                model=model,
                error=str(e),
            )
            return False

    async def close(self) -> None:
        """Close HTTP session and cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
        await super().close()

    # Convenience properties
    @property
    def model(self) -> str:
        """Get model name."""
        return self._model

    @property
    def host(self) -> str:
        """Get Ollama host URL."""
        return self._host


# Factory function for convenience
def create_ollama_provider(
    host: str | None = None,
    model: str | None = None,
) -> OllamaProvider:
    """
    Create an Ollama provider instance.

    Args:
        host: Ollama API host URL.
        model: Model name for all tasks.

    Returns:
        Configured OllamaProvider instance.
    """
    return OllamaProvider(
        host=host,
        model=model,
    )
