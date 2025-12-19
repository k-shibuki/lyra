"""
LLM provider abstraction layer for Lancet.

Provides a unified interface for LLM providers, enabling easy switching
between different backends (Ollama, future providers like llama.cpp, vLLM).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from src.utils.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Data Classes for LLM Operations
# ============================================================================


class ModelCapability(str, Enum):
    """Model capabilities."""
    TEXT_GENERATION = "text_generation"
    CHAT = "chat"
    EMBEDDING = "embedding"
    CODE = "code"
    VISION = "vision"


class LLMResponseStatus(str, Enum):
    """Response status."""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


@dataclass
class LLMOptions:
    """
    Options for LLM generation requests.
    
    Attributes:
        model: Model name to use.
        temperature: Generation temperature (0.0-2.0).
        max_tokens: Maximum tokens to generate.
        top_p: Top-p sampling parameter.
        top_k: Top-k sampling parameter.
        stop: Stop sequences.
        system: System prompt.
        timeout: Request timeout in seconds.
    """
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop: list[str] | None = None
    system: str | None = None
    timeout: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "stop": self.stop,
            "system": self.system,
            "timeout": self.timeout,
        }.items() if v is not None}


@dataclass
class ChatMessage:
    """
    A single message in a chat conversation.
    
    Attributes:
        role: Message role (system, user, assistant).
        content: Message content.
        name: Optional name for the message author.
    """
    role: str
    content: str
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {"role": self.role, "content": self.content}
        if self.name:
            result["name"] = self.name
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatMessage":
        """Create from dictionary."""
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            name=data.get("name"),
        )


@dataclass
class LLMResponse:
    """
    Response from an LLM provider.
    
    Attributes:
        text: Generated text.
        status: Response status.
        model: Model that generated the response.
        provider: Provider name.
        usage: Token usage statistics.
        elapsed_ms: Time taken for generation in milliseconds.
        error_message: Error message if generation failed.
        raw_response: Optional raw response from provider.
    """
    text: str
    status: LLMResponseStatus
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        """Check if generation was successful."""
        return self.status == LLMResponseStatus.SUCCESS

    @property
    def error(self) -> str | None:
        """Get error message (alias for error_message for compatibility)."""
        return self.error_message

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "text": self.text,
            "status": self.status.value,
            "model": self.model,
            "provider": self.provider,
            "usage": self.usage,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error_message,
            "ok": self.ok,
        }

    @classmethod
    def success(
        cls,
        text: str,
        model: str,
        provider: str,
        elapsed_ms: float = 0.0,
        usage: dict[str, int] | None = None,
    ) -> "LLMResponse":
        """Create a successful response."""
        return cls(
            text=text,
            status=LLMResponseStatus.SUCCESS,
            model=model,
            provider=provider,
            usage=usage or {},
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def make_error(
        cls,
        error: str,
        model: str,
        provider: str,
        status: LLMResponseStatus = LLMResponseStatus.ERROR,
    ) -> "LLMResponse":
        """Create an error response."""
        return cls(
            text="",
            status=status,
            model=model,
            provider=provider,
            error_message=error,
        )


@dataclass
class EmbeddingResponse:
    """
    Response from an embedding request.
    
    Attributes:
        embeddings: List of embedding vectors.
        status: Response status.
        model: Model that generated the embeddings.
        provider: Provider name.
        elapsed_ms: Time taken for embedding in milliseconds.
        error: Error message if embedding failed.
    """
    embeddings: list[list[float]]
    status: LLMResponseStatus
    model: str
    provider: str
    elapsed_ms: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Check if embedding was successful."""
        return self.status == LLMResponseStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "embeddings_count": len(self.embeddings),
            "status": self.status.value,
            "model": self.model,
            "provider": self.provider,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "ok": self.ok,
        }

    @classmethod
    def success(
        cls,
        embeddings: list[list[float]],
        model: str,
        provider: str,
        elapsed_ms: float = 0.0,
    ) -> "EmbeddingResponse":
        """Create a successful response."""
        return cls(
            embeddings=embeddings,
            status=LLMResponseStatus.SUCCESS,
            model=model,
            provider=provider,
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def error(
        cls,
        error: str,
        model: str,
        provider: str,
    ) -> "EmbeddingResponse":
        """Create an error response."""
        return cls(
            embeddings=[],
            status=LLMResponseStatus.ERROR,
            model=model,
            provider=provider,
            error=error,
        )


# ============================================================================
# Model Info and Health Status
# ============================================================================


@dataclass
class ModelInfo:
    """
    Information about an available model.
    
    Attributes:
        name: Model name.
        size: Model size description (e.g., "3B", "7B").
        capabilities: List of model capabilities.
        quantization: Quantization method if applicable.
        context_length: Maximum context length.
        modified_at: Last modification time.
        details: Additional model details.
    """
    name: str
    size: str = ""
    capabilities: list[ModelCapability] = field(default_factory=list)
    quantization: str | None = None
    context_length: int = 4096
    modified_at: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "size": self.size,
            "capabilities": [c.value for c in self.capabilities],
            "quantization": self.quantization,
            "context_length": self.context_length,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "details": self.details,
        }


class LLMHealthState(str, Enum):
    """Provider health states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class LLMHealthStatus:
    """
    Health status of an LLM provider.
    
    Attributes:
        state: Current health state.
        available_models: List of available model names.
        loaded_models: List of currently loaded models.
        success_rate: Recent success rate (0.0 to 1.0).
        latency_ms: Average latency in milliseconds.
        last_check: Last health check time.
        message: Optional status message.
        details: Additional health details.
    """
    state: LLMHealthState
    available_models: list[str] = field(default_factory=list)
    loaded_models: list[str] = field(default_factory=list)
    success_rate: float = 1.0
    latency_ms: float = 0.0
    last_check: datetime | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def healthy(
        cls,
        available_models: list[str] | None = None,
        loaded_models: list[str] | None = None,
        latency_ms: float = 0.0,
    ) -> "LLMHealthStatus":
        """Create a healthy status."""
        return cls(
            state=LLMHealthState.HEALTHY,
            available_models=available_models or [],
            loaded_models=loaded_models or [],
            success_rate=1.0,
            latency_ms=latency_ms,
            last_check=datetime.now(UTC),
        )

    @classmethod
    def degraded(
        cls,
        success_rate: float,
        message: str | None = None,
    ) -> "LLMHealthStatus":
        """Create a degraded status."""
        return cls(
            state=LLMHealthState.DEGRADED,
            success_rate=success_rate,
            message=message,
            last_check=datetime.now(UTC),
        )

    @classmethod
    def unhealthy(cls, message: str | None = None) -> "LLMHealthStatus":
        """Create an unhealthy status."""
        return cls(
            state=LLMHealthState.UNHEALTHY,
            success_rate=0.0,
            message=message,
            last_check=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state.value,
            "available_models": self.available_models,
            "loaded_models": self.loaded_models,
            "success_rate": self.success_rate,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "message": self.message,
            "details": self.details,
        }


# ============================================================================
# LLM Provider Protocol
# ============================================================================


@runtime_checkable
class LLMProvider(Protocol):
    """
    Protocol for LLM providers.
    
    Defines the interface that all LLM providers must implement.
    Uses Python's Protocol for structural subtyping, allowing duck typing
    while maintaining type safety.
    
    Example implementation:
        class MyProvider:
            @property
            def name(self) -> str:
                return "my_provider"
            
            async def generate(self, prompt: str, options: LLMOptions | None = None) -> LLMResponse:
                # Implementation
                ...
            
            async def chat(self, messages: list[ChatMessage], options: LLMOptions | None = None) -> LLMResponse:
                # Implementation
                ...
            
            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()
            
            async def close(self) -> None:
                # Cleanup
                ...
    """

    @property
    def name(self) -> str:
        """Unique name of the provider."""
        ...

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
        ...

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
        ...

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> EmbeddingResponse:
        """
        Generate embeddings for texts.
        
        Args:
            texts: List of texts to embed.
            model: Model name for embedding (optional).
            
        Returns:
            EmbeddingResponse with embedding vectors or error.
        """
        ...

    async def get_model_info(self, model: str) -> ModelInfo | None:
        """
        Get information about a specific model.
        
        Args:
            model: Model name.
            
        Returns:
            ModelInfo or None if model not found.
        """
        ...

    async def list_models(self) -> list[ModelInfo]:
        """
        List all available models.
        
        Returns:
            List of ModelInfo for available models.
        """
        ...

    async def get_health(self) -> LLMHealthStatus:
        """
        Get current health status.
        
        Returns:
            LLMHealthStatus indicating provider health.
        """
        ...

    async def unload_model(self, model: str | None = None) -> bool:
        """
        Unload a model to free resources.
        
        Per §4.2: LLM processes should be released after task completion.
        
        Args:
            model: Model name to unload (provider-specific default if not specified).
            
        Returns:
            True if unload was successful.
        """
        ...

    async def close(self) -> None:
        """
        Close and cleanup provider resources.
        
        Should be called when the provider is no longer needed.
        """
        ...


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Provides common functionality and enforces the interface contract.
    Subclasses should implement the abstract methods.
    """

    def __init__(self, provider_name: str):
        """
        Initialize base provider.
        
        Args:
            provider_name: Unique name for this provider.
        """
        self._name = provider_name
        self._is_closed = False
        self._current_task_id: str | None = None

    @property
    def name(self) -> str:
        """Unique name of the provider."""
        return self._name

    @property
    def is_closed(self) -> bool:
        """Check if provider is closed."""
        return self._is_closed

    def set_task_id(self, task_id: str | None) -> None:
        """Set current task ID for lifecycle tracking."""
        self._current_task_id = task_id

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        """Generate text completion."""
        pass

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        """Generate chat completion."""
        pass

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> EmbeddingResponse:
        """Generate embeddings (default: not implemented)."""
        return EmbeddingResponse.error(
            error=f"Embedding not supported by provider '{self._name}'",
            model=model or "unknown",
            provider=self._name,
        )

    @abstractmethod
    async def get_model_info(self, model: str) -> ModelInfo | None:
        """Get information about a specific model."""
        pass

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """List all available models."""
        pass

    @abstractmethod
    async def get_health(self) -> LLMHealthStatus:
        """Get current health status."""
        pass

    async def unload_model(self, model: str | None = None) -> bool:
        """Unload a model (default: no-op)."""
        return True

    async def close(self) -> None:
        """Close and cleanup provider resources."""
        self._is_closed = True
        logger.debug("LLM provider closed", provider=self._name)

    def _check_closed(self) -> None:
        """Raise error if provider is closed."""
        if self._is_closed:
            raise RuntimeError(f"Provider '{self._name}' is closed")


# ============================================================================
# Provider Registry
# ============================================================================


class LLMProviderRegistry:
    """
    Registry for LLM providers.
    
    Manages registration, retrieval, and lifecycle of LLM providers.
    Supports multiple providers with fallback selection.
    
    Example usage:
        registry = LLMProviderRegistry()
        registry.register(OllamaProvider())
        
        # Get specific provider
        provider = registry.get("ollama")
        
        # Get default provider
        provider = registry.get_default()
        
        # Generate with fallback
        response = await registry.generate_with_fallback(prompt)
    """

    def __init__(self):
        """Initialize empty registry."""
        self._providers: dict[str, LLMProvider] = {}
        self._default_name: str | None = None

    def register(
        self,
        provider: LLMProvider,
        set_default: bool = False,
    ) -> None:
        """
        Register an LLM provider.
        
        Args:
            provider: Provider instance to register.
            set_default: Whether to set as default provider.
        
        Raises:
            ValueError: If provider with same name already registered.
        """
        name = provider.name

        if name in self._providers:
            raise ValueError(f"Provider '{name}' already registered")

        self._providers[name] = provider

        if set_default or self._default_name is None:
            self._default_name = name

        logger.info(
            "LLM provider registered",
            provider=name,
            is_default=set_default or self._default_name == name,
        )

    def unregister(self, name: str) -> LLMProvider | None:
        """
        Unregister a provider by name.
        
        Args:
            name: Provider name to unregister.
            
        Returns:
            The unregistered provider, or None if not found.
        """
        provider = self._providers.pop(name, None)

        if provider is not None:
            logger.info("LLM provider unregistered", provider=name)

            # Update default if needed
            if self._default_name == name:
                self._default_name = next(iter(self._providers), None)

        return provider

    def get(self, name: str) -> LLMProvider | None:
        """
        Get a provider by name.
        
        Args:
            name: Provider name.
            
        Returns:
            Provider instance or None if not found.
        """
        return self._providers.get(name)

    def get_default(self) -> LLMProvider | None:
        """
        Get the default provider.
        
        Returns:
            Default provider or None if no providers registered.
        """
        if self._default_name is None:
            return None
        return self._providers.get(self._default_name)

    def set_default(self, name: str) -> None:
        """
        Set the default provider.
        
        Args:
            name: Provider name to set as default.
            
        Raises:
            ValueError: If provider not found.
        """
        if name not in self._providers:
            raise ValueError(f"Provider '{name}' not registered")

        self._default_name = name
        logger.info("Default LLM provider changed", provider=name)

    def list_providers(self) -> list[str]:
        """
        List all registered provider names.
        
        Returns:
            List of provider names.
        """
        return list(self._providers.keys())

    async def get_all_health(self) -> dict[str, LLMHealthStatus]:
        """
        Get health status for all providers.
        
        Returns:
            Dict mapping provider names to health status.
        """
        health = {}
        for name, provider in self._providers.items():
            try:
                health[name] = await provider.get_health()
            except Exception as e:
                logger.error("Failed to get health", provider=name, error=str(e))
                health[name] = LLMHealthStatus.unhealthy(str(e))
        return health

    async def generate_with_fallback(
        self,
        prompt: str,
        options: LLMOptions | None = None,
        provider_order: list[str] | None = None,
    ) -> LLMResponse:
        """
        Generate with automatic fallback to other providers on failure.
        
        Args:
            prompt: Input prompt.
            options: Generation options.
            provider_order: Order of providers to try.
            
        Returns:
            LLMResponse from first successful provider.
            
        Raises:
            RuntimeError: If no providers available or all fail.
        """
        if not self._providers:
            raise RuntimeError("No LLM providers registered")

        # Determine provider order
        if provider_order is None:
            provider_order = []
            if self._default_name:
                provider_order.append(self._default_name)
            provider_order.extend(n for n in self._providers if n not in provider_order)

        errors = []

        for name in provider_order:
            provider = self._providers.get(name)
            if provider is None:
                continue

            try:
                # Check health first
                health = await provider.get_health()
                if health.state == LLMHealthState.UNHEALTHY:
                    logger.debug(
                        "Skipping unhealthy provider",
                        provider=name,
                        message=health.message,
                    )
                    continue

                # Execute generation
                response = await provider.generate(prompt, options)

                if response.ok:
                    return response

                # Generation returned error
                errors.append(f"{name}: {response.error}")
                logger.warning(
                    "LLM provider returned error",
                    provider=name,
                    error=response.error,
                )

            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                logger.error("LLM provider failed", provider=name, error=str(e))

        # All providers failed
        error_msg = "; ".join(errors) if errors else "No providers available"
        model = options.model if options else "unknown"
        return LLMResponse.make_error(
            error=f"All providers failed: {error_msg}",
            model=model or "unknown",
            provider="none",
        )

    async def chat_with_fallback(
        self,
        messages: list[ChatMessage],
        options: LLMOptions | None = None,
        provider_order: list[str] | None = None,
    ) -> LLMResponse:
        """
        Chat with automatic fallback to other providers on failure.
        
        Args:
            messages: Chat messages.
            options: Generation options.
            provider_order: Order of providers to try.
            
        Returns:
            LLMResponse from first successful provider.
        """
        if not self._providers:
            raise RuntimeError("No LLM providers registered")

        # Determine provider order
        if provider_order is None:
            provider_order = []
            if self._default_name:
                provider_order.append(self._default_name)
            provider_order.extend(n for n in self._providers if n not in provider_order)

        errors = []

        for name in provider_order:
            provider = self._providers.get(name)
            if provider is None:
                continue

            try:
                health = await provider.get_health()
                if health.state == LLMHealthState.UNHEALTHY:
                    continue

                response = await provider.chat(messages, options)

                if response.ok:
                    return response

                errors.append(f"{name}: {response.error}")

            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                logger.error("LLM provider chat failed", provider=name, error=str(e))

        error_msg = "; ".join(errors) if errors else "No providers available"
        model = options.model if options else "unknown"
        return LLMResponse.make_error(
            error=f"All providers failed: {error_msg}",
            model=model or "unknown",
            provider="none",
        )

    async def close_all(self) -> None:
        """Close all registered providers."""
        for name, provider in self._providers.items():
            try:
                await provider.close()
            except Exception as e:
                logger.error("Failed to close provider", provider=name, error=str(e))

        self._providers.clear()
        self._default_name = None
        logger.info("All LLM providers closed")


# ============================================================================
# Global Registry
# ============================================================================

_registry: LLMProviderRegistry | None = None


def get_llm_registry() -> LLMProviderRegistry:
    """
    Get the global LLM provider registry.
    
    Returns:
        The global LLMProviderRegistry instance.
    """
    global _registry
    if _registry is None:
        _registry = LLMProviderRegistry()
    return _registry


async def cleanup_llm_registry() -> None:
    """
    Cleanup the global registry.
    
    Closes all providers and resets the registry.
    """
    global _registry
    if _registry is not None:
        await _registry.close_all()
        _registry = None


def reset_llm_registry() -> None:
    """
    Reset the global registry without closing providers.
    
    For testing purposes only.
    """
    global _registry
    _registry = None

