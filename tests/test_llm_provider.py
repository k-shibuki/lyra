"""
Unit tests for LLM provider abstraction layer.

Tests the LLMProvider protocol, OllamaProvider implementation, and registry.

Follows §7.1 test quality standards:
- No conditional assertions (§7.1.1)
- Specific expected values (§7.1.2)
- Proper boundary testing (§7.1.2)
- Realistic test data with Ollama API format (§7.1.3)
- External dependencies fully mocked (§7.1.7)

## Test Perspectives Table
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|----------------------|---------------------------------------|-----------------|-------|
| TC-CM-01 | ChatMessage creation | Equivalence – normal | Message with role/content | - |
| TC-CM-02 | ChatMessage serialization | Equivalence – to_dict | Dictionary output | - |
| TC-LO-01 | LLMOptions defaults | Equivalence – defaults | Default values set | - |
| TC-LO-02 | LLMOptions custom | Equivalence – custom | Custom values used | - |
| TC-ER-01 | EmbeddingResponse creation | Equivalence – normal | Response with embeddings | - |
| TC-HS-01 | LLMHealthStatus healthy | Equivalence – healthy | available=True | - |
| TC-HS-02 | LLMHealthStatus unhealthy | Equivalence – unhealthy | available=False | - |
| TC-OI-01 | Default config (no args) | Equivalence – normal | Uses proxy URL | Hybrid mode |
| TC-OI-02 | Explicit host/model | Equivalence – override | Uses explicit values | Bypass proxy |
| TC-OI-03 | Provider name | Equivalence – normal | name == "ollama" | Identity |
| TC-OP-01 | OllamaProvider generate | Equivalence – generate | Text response | - |
| TC-OP-02 | OllamaProvider chat | Equivalence – chat | Chat response | - |
| TC-OP-03 | OllamaProvider embed | Equivalence – embed | Embedding vector | - |
| TC-OP-04 | OllamaProvider health | Equivalence – health | Health status | - |
| TC-OP-05 | OllamaProvider error | Abnormal – error | Handles gracefully | - |
| TC-PR-01 | Register provider | Equivalence – register | Provider registered | - |
| TC-PR-02 | Get provider | Equivalence – retrieval | Returns provider | - |
| TC-PR-03 | Fallback provider | Equivalence – fallback | Uses fallback | - |
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit

from src.filter.ollama_provider import OllamaProvider
from src.filter.provider import (
    BaseLLMProvider,
    ChatMessage,
    EmbeddingResponse,
    LLMHealthState,
    LLMHealthStatus,
    LLMOptions,
    LLMProvider,
    LLMProviderRegistry,
    LLMResponse,
    LLMResponseStatus,
    ModelCapability,
    ModelInfo,
    get_llm_registry,
    reset_llm_registry,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def reset_registry() -> Generator[None, None, None]:
    """Reset global registry before each test."""
    reset_llm_registry()
    yield
    reset_llm_registry()


@pytest.fixture
def mock_aiohttp_session() -> AsyncMock:
    """Create a mock aiohttp session."""
    session = AsyncMock()
    session.closed = False
    return session


@pytest.fixture
def ollama_provider() -> OllamaProvider:
    """Create an OllamaProvider for testing."""
    return OllamaProvider(
        host="http://localhost:11434",
        model="test-model:3b",
    )


# ============================================================================
# Data Class Tests
# ============================================================================


class TestLLMOptions:
    """Tests for LLMOptions dataclass (§3.2.1 MCP Tool IF Spec)."""

    def test_default_values(self) -> None:
        """LLMOptions should have None defaults for optional fields."""
        options = LLMOptions()

        assert options.model is None, "model should default to None"
        assert options.temperature is None, "temperature should default to None"
        assert options.max_tokens is None, "max_tokens should default to None"
        assert options.top_p is None, "top_p should default to None"
        assert options.top_k is None, "top_k should default to None"
        assert options.stop is None, "stop should default to None"
        assert options.system is None, "system should default to None"
        assert options.timeout is None, "timeout should default to None"

    def test_to_dict_excludes_none(self) -> None:
        """to_dict should exclude None values for clean API payloads."""
        options = LLMOptions(model="test", temperature=0.7)
        result = options.to_dict()

        assert result == {"model": "test", "temperature": 0.7}, f"Got {result}"
        assert "max_tokens" not in result, "None values should be excluded"

    def test_to_dict_includes_all_set_values(self) -> None:
        """to_dict should include all explicitly set values."""
        options = LLMOptions(
            model="gpt-4",
            temperature=0.5,
            max_tokens=100,
            top_p=0.9,
            stop=[".", "!"],
        )
        result = options.to_dict()

        assert result["model"] == "gpt-4", f"Expected gpt-4, got {result.get('model')}"
        assert result["temperature"] == 0.5, f"Expected 0.5, got {result.get('temperature')}"
        assert result["max_tokens"] == 100, f"Expected 100, got {result.get('max_tokens')}"
        assert result["top_p"] == 0.9, f"Expected 0.9, got {result.get('top_p')}"
        assert result["stop"] == [".", "!"], f"Expected ['.', '!'], got {result.get('stop')}"


class TestChatMessage:
    """Tests for ChatMessage dataclass."""

    def test_basic_message(self) -> None:
        """ChatMessage should store role and content."""
        msg = ChatMessage(role="user", content="Hello")

        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None

    def test_to_dict_basic(self) -> None:
        """to_dict should return role and content."""
        msg = ChatMessage(role="assistant", content="Hi there")
        result = msg.to_dict()

        assert result == {"role": "assistant", "content": "Hi there"}

    def test_to_dict_with_name(self) -> None:
        """to_dict should include name when set."""
        msg = ChatMessage(role="user", content="Test", name="alice")
        result = msg.to_dict()

        assert result["name"] == "alice"

    def test_from_dict(self) -> None:
        """from_dict should reconstruct ChatMessage."""
        data = {"role": "system", "content": "You are helpful"}
        msg = ChatMessage.from_dict(data)

        assert msg.role == "system"
        assert msg.content == "You are helpful"

    def test_from_dict_defaults(self) -> None:
        """from_dict should use defaults for missing keys."""
        msg = ChatMessage.from_dict({})

        assert msg.role == "user"
        assert msg.content == ""


class TestLLMResponse:
    """Tests for LLMResponse dataclass (§3.2.1 MCP Tool IF Spec)."""

    def test_success_response(self) -> None:
        """success() should create a successful response with all fields set."""
        response = LLMResponse.success(
            text="Generated text",
            model="test-model",
            provider="test-provider",
            elapsed_ms=100.5,
        )

        assert response.ok is True, "Success response should have ok=True"
        assert response.text == "Generated text", (
            f"Expected 'Generated text', got '{response.text}'"
        )
        assert response.model == "test-model", f"Expected 'test-model', got '{response.model}'"
        assert response.provider == "test-provider", (
            f"Expected 'test-provider', got '{response.provider}'"
        )
        assert response.elapsed_ms == 100.5, f"Expected 100.5ms, got {response.elapsed_ms}ms"
        assert response.status == LLMResponseStatus.SUCCESS, (
            f"Expected SUCCESS, got {response.status}"
        )
        assert response.error is None, f"Error should be None for success, got '{response.error}'"

    def test_error_response(self) -> None:
        """make_error() should create an error response with empty text."""
        response = LLMResponse.make_error(
            error="Connection failed",
            model="test-model",
            provider="test-provider",
        )

        assert response.ok is False, "Error response should have ok=False"
        assert response.text == "", f"Error response should have empty text, got '{response.text}'"
        assert response.error == "Connection failed", (
            f"Expected 'Connection failed', got '{response.error}'"
        )
        assert response.status == LLMResponseStatus.ERROR, f"Expected ERROR, got {response.status}"

    def test_timeout_error(self) -> None:
        """make_error() with TIMEOUT status should indicate timeout (§4.3 Resilience)."""
        response = LLMResponse.make_error(
            error="Request timed out",
            model="test-model",
            provider="test-provider",
            status=LLMResponseStatus.TIMEOUT,
        )

        assert response.status == LLMResponseStatus.TIMEOUT, (
            f"Expected TIMEOUT, got {response.status}"
        )
        assert response.ok is False, "Timeout response should have ok=False"

    def test_to_dict_serialization(self) -> None:
        """to_dict should include ok property for MCP response serialization."""
        response = LLMResponse.success(
            text="Test",
            model="m",
            provider="p",
        )
        result = response.to_dict()

        assert result["ok"] is True, f"Expected ok=True in dict, got {result.get('ok')}"
        assert result["text"] == "Test", f"Expected 'Test', got {result.get('text')}"
        assert result["status"] == "success", f"Expected 'success', got {result.get('status')}"


class TestEmbeddingResponse:
    """Tests for EmbeddingResponse dataclass."""

    def test_success_embedding(self) -> None:
        """success() should create a successful embedding response."""
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        response = EmbeddingResponse.success(
            embeddings=embeddings,
            model="embed-model",
            provider="test-provider",
        )

        assert response.ok is True
        assert response.embeddings == embeddings
        assert len(response.embeddings) == 2

    def test_error_embedding(self) -> None:
        """error() should create an error embedding response."""
        response = EmbeddingResponse.error_response(
            error="Embedding failed",
            model="embed-model",
            provider="test-provider",
        )

        assert response.ok is False
        assert response.embeddings == []
        assert response.error == "Embedding failed"


class TestModelInfo:
    """Tests for ModelInfo dataclass."""

    def test_basic_model_info(self) -> None:
        """ModelInfo should store model metadata."""
        info = ModelInfo(
            name="qwen2.5:3b",
            size="3B",
            capabilities=[ModelCapability.TEXT_GENERATION, ModelCapability.CHAT],
        )

        assert info.name == "qwen2.5:3b"
        assert info.size == "3B"
        assert ModelCapability.TEXT_GENERATION in info.capabilities
        assert ModelCapability.CHAT in info.capabilities

    def test_to_dict(self) -> None:
        """to_dict should serialize capabilities as strings."""
        info = ModelInfo(
            name="test",
            capabilities=[ModelCapability.EMBEDDING],
        )
        result = info.to_dict()

        assert result["capabilities"] == ["embedding"]


class TestLLMHealthStatus:
    """Tests for LLMHealthStatus dataclass."""

    def test_healthy_status(self) -> None:
        """healthy() should create a healthy status."""
        status = LLMHealthStatus.healthy(
            available_models=["model1", "model2"],
            latency_ms=50.0,
        )

        assert status.state == LLMHealthState.HEALTHY
        assert status.success_rate == 1.0
        assert status.available_models == ["model1", "model2"]
        assert status.latency_ms == 50.0
        assert status.last_check is not None

    def test_degraded_status(self) -> None:
        """degraded() should indicate partial health."""
        status = LLMHealthStatus.degraded(
            success_rate=0.7,
            message="High latency detected",
        )

        assert status.state == LLMHealthState.DEGRADED
        assert status.success_rate == 0.7
        assert status.message == "High latency detected"

    def test_unhealthy_status(self) -> None:
        """unhealthy() should indicate complete failure."""
        status = LLMHealthStatus.unhealthy(message="Connection refused")

        assert status.state == LLMHealthState.UNHEALTHY
        assert status.success_rate == 0.0
        assert status.message == "Connection refused"


# ============================================================================
# Protocol and Base Class Tests
# ============================================================================


class TestLLMProviderProtocol:
    """Tests for LLMProvider protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """LLMProvider should be runtime checkable."""

        # A minimal implementation that satisfies the protocol
        class MinimalProvider:
            @property
            def name(self) -> str:
                return "minimal"

            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def embed(
                self, texts: list[str], model: str | None = None
            ) -> EmbeddingResponse:
                return EmbeddingResponse.success([], "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

            async def unload_model(self, model: str | None = None) -> bool:
                return True

            async def close(self) -> None:
                pass

        provider = MinimalProvider()
        assert isinstance(provider, LLMProvider)


class TestBaseLLMProvider:
    """Tests for BaseLLMProvider abstract base class."""

    def test_init_sets_name(self) -> None:
        """BaseLLMProvider should set provider name."""

        class TestProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        provider = TestProvider("my-provider")
        assert provider.name == "my-provider"
        assert provider.is_closed is False

    def test_set_task_id(self) -> None:
        """set_task_id should track current task."""

        class TestProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        provider = TestProvider("test")
        provider.set_task_id("task-123")
        assert provider._current_task_id == "task-123"

    @pytest.mark.asyncio
    async def test_close_marks_closed(self) -> None:
        """close() should mark provider as closed."""

        class TestProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        provider = TestProvider("test")
        await provider.close()
        assert provider.is_closed is True

    @pytest.mark.asyncio
    async def test_embed_default_not_supported(self) -> None:
        """Default embed implementation should return error."""

        class TestProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        provider = TestProvider("test")
        response = await provider.embed(["hello"])

        assert response.ok is False
        assert "not supported" in response.error.lower()


# ============================================================================
# OllamaProvider Tests
# ============================================================================


class TestOllamaProviderInit:
    """Tests for OllamaProvider initialization (Phase O.3 hybrid mode)."""

    def test_default_configuration(self) -> None:
        """
        TC-OI-01: OllamaProvider uses proxy URL in hybrid mode.

        // Given: Settings with proxy_url configured
        // When: Creating OllamaProvider without explicit host
        // Then: Host is set to proxy_url/ollama
        """
        with patch("src.filter.ollama_provider.get_settings") as mock_settings:
            mock_settings.return_value.general.proxy_url = "http://localhost:8080"
            mock_settings.return_value.llm.model = "custom-model"
            mock_settings.return_value.llm.temperature = 0.5

            provider = OllamaProvider()

            # In hybrid mode, Ollama is accessed via proxy
            assert provider.host == "http://localhost:8080/ollama"
            assert provider.model == "custom-model"

    def test_explicit_configuration(self) -> None:
        """
        TC-OI-02: OllamaProvider accepts explicit host/model configuration.

        // Given: Explicit host and model arguments
        // When: Creating OllamaProvider with explicit args
        // Then: Explicit values override proxy URL
        """
        provider = OllamaProvider(
            host="http://custom:11434",
            model="my-model:3b",
        )

        assert provider.host == "http://custom:11434"
        assert provider.model == "my-model:3b"

    def test_provider_name(self) -> None:
        """
        TC-OI-03: OllamaProvider has correct provider name.

        // Given: OllamaProvider instance
        // When: Accessing name property
        // Then: Returns "ollama"
        """
        provider = OllamaProvider()
        assert provider.name == "ollama"


class TestOllamaProviderGenerate:
    """Tests for OllamaProvider.generate() (Ollama /api/generate endpoint)."""

    @pytest.mark.asyncio
    async def test_generate_success(self, ollama_provider: OllamaProvider) -> None:
        """generate() should return success response on HTTP 200 with Ollama format."""
        # Ollama API response format: response, prompt_eval_count, eval_count
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "response": "Generated text here",
                "prompt_eval_count": 10,
                "eval_count": 20,
            }
        )

        # Create a proper async context manager for aiohttp
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")

        assert response.ok is True, (
            f"Expected ok=True, got ok={response.ok}, error={response.error}"
        )
        assert response.text == "Generated text here", (
            f"Expected 'Generated text here', got '{response.text}'"
        )
        assert response.model == "test-model:3b", (
            f"Expected 'test-model:3b', got '{response.model}'"
        )
        assert response.provider == "ollama", f"Expected 'ollama', got '{response.provider}'"
        assert response.usage["prompt_tokens"] == 10, (
            f"Expected 10 prompt tokens, got {response.usage.get('prompt_tokens')}"
        )
        assert response.usage["completion_tokens"] == 20, (
            f"Expected 20 completion tokens, got {response.usage.get('completion_tokens')}"
        )

    @pytest.mark.asyncio
    async def test_generate_with_options(self, ollama_provider: OllamaProvider) -> None:
        """generate() should pass options to API."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "OK"})

        captured_payload: dict[str, object] = {}

        # Create a proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        def capture_post(
            url: str, json: dict[str, object], timeout: float | None = None
        ) -> AsyncMock:
            captured_payload.update(json)
            return mock_cm

        mock_session = MagicMock()
        mock_session.post = capture_post

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            options = LLMOptions(
                model="custom-model",
                temperature=0.8,
                max_tokens=500,
                system="You are helpful",
            )
            await ollama_provider.generate("Test", options)

        assert captured_payload["model"] == "custom-model"
        assert captured_payload["options"]["temperature"] == 0.8
        assert captured_payload["options"]["num_predict"] == 500
        assert captured_payload["system"] == "You are helpful"

    @pytest.mark.asyncio
    async def test_generate_api_error(self, ollama_provider: OllamaProvider) -> None:
        """generate() should return error response on non-200 (§4.3 Resilience)."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal server error")

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")

        assert response.ok is False, f"API error should have ok=False, got {response.ok}"
        assert "500" in response.error, (
            f"Error message should contain status code 500: {response.error}"
        )
        assert response.status == LLMResponseStatus.ERROR, (
            f"Expected ERROR status, got {response.status}"
        )

    @pytest.mark.asyncio
    async def test_generate_tracks_model(self, ollama_provider: OllamaProvider) -> None:
        """generate() should track current model for cleanup."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "OK"})

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            await ollama_provider.generate("Test")

        assert ollama_provider._current_model == "test-model:3b"


class TestOllamaProviderChat:
    """Tests for OllamaProvider.chat() (Ollama /api/chat endpoint)."""

    @pytest.mark.asyncio
    async def test_chat_success(self, ollama_provider: OllamaProvider) -> None:
        """chat() should return assistant response with content extracted."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "message": {"content": "Hello! How can I help?"},
            }
        )

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            messages = [ChatMessage(role="user", content="Hi")]
            response = await ollama_provider.chat(messages)

        assert response.ok is True, (
            f"Expected ok=True, got ok={response.ok}, error={response.error}"
        )
        assert response.text == "Hello! How can I help?", (
            f"Expected chat response content, got '{response.text}'"
        )

    @pytest.mark.asyncio
    async def test_chat_converts_messages(self, ollama_provider: OllamaProvider) -> None:
        """chat() should convert ChatMessage to dict format."""
        captured_payload: dict[str, object] = {}

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"message": {"content": "OK"}})

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        def capture_post(
            url: str, json: dict[str, object], timeout: float | None = None
        ) -> AsyncMock:
            captured_payload.update(json)
            return mock_cm

        mock_session = MagicMock()
        mock_session.post = capture_post

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            messages = [
                ChatMessage(role="system", content="Be helpful"),
                ChatMessage(role="user", content="Hello"),
            ]
            await ollama_provider.chat(messages)

        assert len(captured_payload["messages"]) == 2
        assert captured_payload["messages"][0]["role"] == "system"
        assert captured_payload["messages"][1]["content"] == "Hello"


class TestOllamaProviderEmbed:
    """Tests for OllamaProvider.embed()."""

    @pytest.mark.asyncio
    async def test_embed_success(self, ollama_provider: OllamaProvider) -> None:
        """embed() should return embedding vectors."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            }
        )

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            response = await ollama_provider.embed(["text1", "text2"])

        assert response.ok is True
        assert len(response.embeddings) == 2
        assert response.embeddings[0] == [0.1, 0.2, 0.3]


class TestOllamaProviderHealth:
    """Tests for OllamaProvider.get_health()."""

    @pytest.mark.asyncio
    async def test_health_healthy(self, ollama_provider: OllamaProvider) -> None:
        """get_health() should return healthy when API responds."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "models": [{"name": "model1"}, {"name": "model2"}],
            }
        )

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            health = await ollama_provider.get_health()

        assert health.state == LLMHealthState.HEALTHY
        assert "model1" in health.available_models
        assert "model2" in health.available_models

    @pytest.mark.asyncio
    async def test_health_unhealthy_on_error(self, ollama_provider: OllamaProvider) -> None:
        """get_health() should return unhealthy on connection error."""
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = Exception("Connection refused")

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            health = await ollama_provider.get_health()

        assert health.state == LLMHealthState.UNHEALTHY
        assert "Connection refused" in health.message

    @pytest.mark.asyncio
    async def test_health_closed_provider(self, ollama_provider: OllamaProvider) -> None:
        """get_health() should return unhealthy when closed."""
        ollama_provider._is_closed = True

        health = await ollama_provider.get_health()

        assert health.state == LLMHealthState.UNHEALTHY
        assert "closed" in health.message.lower()


class TestOllamaProviderUnload:
    """Tests for OllamaProvider.unload_model()."""

    @pytest.mark.asyncio
    async def test_unload_success(self, ollama_provider: OllamaProvider) -> None:
        """unload_model() should call API with keep_alive=0."""
        ollama_provider._current_model = "test-model"

        captured_payload = {}

        mock_response = MagicMock()
        mock_response.status = 200

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        def capture_post(
            url: str, json: dict[str, object], timeout: float | None = None
        ) -> AsyncMock:
            captured_payload.update(json)
            return mock_cm

        mock_session = MagicMock()
        mock_session.post = capture_post

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            result = await ollama_provider.unload_model()

        assert result is True
        assert captured_payload["keep_alive"] == 0
        assert captured_payload["model"] == "test-model"
        assert ollama_provider._current_model is None

    @pytest.mark.asyncio
    async def test_unload_no_current_model(self, ollama_provider: OllamaProvider) -> None:
        """unload_model() should return False when no model loaded."""
        ollama_provider._current_model = None

        result = await ollama_provider.unload_model()

        assert result is False


class TestOllamaProviderListModels:
    """Tests for OllamaProvider.list_models()."""

    @pytest.mark.asyncio
    async def test_list_models_success(self, ollama_provider: OllamaProvider) -> None:
        """list_models() should return available models."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "models": [
                    {"name": "qwen2.5:3b", "details": {"parameter_size": "3B"}},
                    {"name": "llama2:7b", "details": {"parameter_size": "7B"}},
                ],
            }
        )

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)

        with patch.object(ollama_provider, "_get_session", AsyncMock(return_value=mock_session)):
            models = await ollama_provider.list_models()

        assert len(models) == 2
        assert models[0].name == "qwen2.5:3b"
        assert models[0].size == "3B"
        assert models[1].name == "llama2:7b"


# ============================================================================
# LLMProviderRegistry Tests
# ============================================================================


class TestLLMProviderRegistry:
    """Tests for LLMProviderRegistry (§5.2 Plugin Mechanism)."""

    def test_register_provider(self) -> None:
        """register() should add provider to registry."""
        registry = LLMProviderRegistry()
        provider = OllamaProvider()

        registry.register(provider)

        providers = registry.list_providers()
        assert "ollama" in providers, f"'ollama' not in registered providers: {providers}"
        assert registry.get("ollama") is provider, (
            "get() should return the registered provider instance"
        )

    def test_register_sets_default(self) -> None:
        """First registered provider should become default (§4.3.1 Fallback)."""
        registry = LLMProviderRegistry()
        provider = OllamaProvider()

        registry.register(provider)

        default = registry.get_default()
        assert default is provider, f"Expected default to be the registered provider, got {default}"

    def test_register_duplicate_raises(self) -> None:
        """register() should raise on duplicate name."""
        registry = LLMProviderRegistry()
        provider1 = OllamaProvider()
        provider2 = OllamaProvider()

        registry.register(provider1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(provider2)

    def test_unregister_provider(self) -> None:
        """unregister() should remove provider."""
        registry = LLMProviderRegistry()
        provider = OllamaProvider()
        registry.register(provider)

        removed = registry.unregister("ollama")

        assert removed is provider
        assert "ollama" not in registry.list_providers()

    def test_unregister_updates_default(self) -> None:
        """unregister() should update default when default is removed."""
        registry = LLMProviderRegistry()

        class Provider1(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        p1 = Provider1("provider1")
        p2 = Provider1("provider2")

        registry.register(p1)
        registry.register(p2)

        registry.unregister("provider1")

        assert registry.get_default() is p2

    def test_set_default(self) -> None:
        """set_default() should change default provider."""
        registry = LLMProviderRegistry()

        class Provider1(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        p1 = Provider1("provider1")
        p2 = Provider1("provider2")

        registry.register(p1)
        registry.register(p2)

        registry.set_default("provider2")

        assert registry.get_default() is p2

    def test_set_default_nonexistent_raises(self) -> None:
        """set_default() should raise for unknown provider."""
        registry = LLMProviderRegistry()

        with pytest.raises(ValueError, match="not registered"):
            registry.set_default("unknown")

    @pytest.mark.asyncio
    async def test_generate_with_fallback_success(self) -> None:
        """generate_with_fallback() should return on first success (§4.3.1 Fallback)."""
        registry = LLMProviderRegistry()

        class SuccessProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("Success!", "m", self._name)

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        registry.register(SuccessProvider("good"))

        response = await registry.generate_with_fallback("Test prompt")

        assert response.ok is True, (
            f"Expected ok=True, got ok={response.ok}, error={response.error}"
        )
        assert response.text == "Success!", f"Expected 'Success!', got '{response.text}'"
        assert response.provider == "good", f"Expected provider 'good', got '{response.provider}'"

    @pytest.mark.asyncio
    async def test_generate_with_fallback_tries_multiple(self) -> None:
        """generate_with_fallback() should try next provider on failure (§4.3.1 Fallback)."""
        registry = LLMProviderRegistry()

        class FailProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.make_error("Failed", "m", self._name)

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        class SuccessProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("OK", "m", self._name)

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        registry.register(FailProvider("fail"))
        registry.register(SuccessProvider("success"))

        response = await registry.generate_with_fallback("Test")

        assert response.ok is True, (
            f"Fallback should succeed, got ok={response.ok}, error={response.error}"
        )
        assert response.provider == "success", (
            f"Should fallback to 'success' provider, got '{response.provider}'"
        )

    @pytest.mark.asyncio
    async def test_generate_with_fallback_skips_unhealthy(self) -> None:
        """generate_with_fallback() should skip unhealthy providers (§4.3.1 Health Check)."""
        registry = LLMProviderRegistry()

        class UnhealthyProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("Should not reach", "m", self._name)

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.unhealthy("Down for maintenance")

        class HealthyProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("From healthy", "m", self._name)

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        registry.register(UnhealthyProvider("unhealthy"))
        registry.register(HealthyProvider("healthy"))

        response = await registry.generate_with_fallback("Test")

        assert response.ok is True, f"Should skip unhealthy and succeed, got ok={response.ok}"
        assert response.provider == "healthy", (
            f"Should use 'healthy' provider, got '{response.provider}'"
        )

    @pytest.mark.asyncio
    async def test_generate_with_fallback_all_fail(self) -> None:
        """generate_with_fallback() should return error when all fail (§4.3 Error Cases)."""
        registry = LLMProviderRegistry()

        class FailProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.make_error("Failed", "m", self._name)

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        registry.register(FailProvider("fail1"))
        registry.register(FailProvider("fail2"))

        response = await registry.generate_with_fallback("Test")

        assert response.ok is False, f"All providers failed should have ok=False, got {response.ok}"
        assert "All providers failed" in response.error, (
            f"Error should mention 'All providers failed': {response.error}"
        )

    @pytest.mark.asyncio
    async def test_generate_with_fallback_no_providers(self) -> None:
        """generate_with_fallback() should raise when no providers."""
        registry = LLMProviderRegistry()

        with pytest.raises(RuntimeError, match="No LLM providers registered"):
            await registry.generate_with_fallback("Test")

    @pytest.mark.asyncio
    async def test_close_all(self) -> None:
        """close_all() should close all providers."""
        registry = LLMProviderRegistry()

        close_called: list[str] = []

        class TrackingProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

            async def close(self) -> None:
                close_called.append(self._name)
                await super().close()

        registry.register(TrackingProvider("p1"))
        registry.register(TrackingProvider("p2"))

        await registry.close_all()

        assert "p1" in close_called
        assert "p2" in close_called
        assert len(registry.list_providers()) == 0


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_llm_registry_creates_singleton(self) -> None:
        """get_llm_registry() should return same instance."""
        r1 = get_llm_registry()
        r2 = get_llm_registry()

        assert r1 is r2

    def test_reset_llm_registry(self) -> None:
        """reset_llm_registry() should create new instance."""
        r1 = get_llm_registry()
        reset_llm_registry()
        r2 = get_llm_registry()

        assert r1 is not r2


# ============================================================================
# Integration Tests
# ============================================================================


class TestLLMModuleIntegration:
    """Integration tests for llm.py module functions."""

    @pytest.mark.asyncio
    async def test_llm_extract_with_provider(self) -> None:
        """llm_extract should work with provider abstraction."""
        from src.filter.llm import llm_extract

        # Mock the provider
        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.model = "test-model"  # Single model per §K.1
        mock_provider.generate = AsyncMock(
            return_value=LLMResponse.success(
                text='[{"fact": "Test fact", "confidence": 0.9}]',
                model="test",
                provider="mock",
            )
        )
        mock_provider.get_health = AsyncMock(return_value=LLMHealthStatus.healthy())

        registry = get_llm_registry()
        registry.register(mock_provider, set_default=True)

        passages = [{"id": "p1", "text": "Test passage content"}]
        result = await llm_extract(passages, task="extract_facts", use_provider=True)

        assert result["ok"] is True
        assert result["task"] == "extract_facts"
        assert len(result["facts"]) == 1
        assert result["facts"][0]["fact"] == "Test fact"

    @pytest.mark.asyncio
    async def test_generate_with_provider_function(self) -> None:
        """generate_with_provider should use registry."""
        from src.filter.llm import generate_with_provider

        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.generate = AsyncMock(
            return_value=LLMResponse.success(
                text="Generated output",
                model="test",
                provider="mock",
            )
        )
        mock_provider.get_health = AsyncMock(return_value=LLMHealthStatus.healthy())

        registry = get_llm_registry()
        registry.register(mock_provider, set_default=True)

        result = await generate_with_provider("Test prompt")

        assert result == "Generated output"
        mock_provider.generate.assert_called_once()


# ============================================================================
# Edge Cases and Boundary Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_chat_messages(self) -> None:
        """ChatMessage.from_dict should handle empty dict."""
        msg = ChatMessage.from_dict({})
        assert msg.role == "user"
        assert msg.content == ""

    def test_llm_options_all_none(self) -> None:
        """LLMOptions.to_dict should return empty dict when all None."""
        options = LLMOptions()
        result = options.to_dict()
        assert result == {}

    @pytest.mark.asyncio
    async def test_provider_check_closed(self, ollama_provider: OllamaProvider) -> None:
        """Closed provider should raise on operations."""
        ollama_provider._is_closed = True

        with pytest.raises(RuntimeError, match="closed"):
            await ollama_provider.generate("test")

    def test_model_info_empty_capabilities(self) -> None:
        """ModelInfo should handle empty capabilities."""
        info = ModelInfo(name="test")
        assert info.capabilities == []
        assert info.to_dict()["capabilities"] == []

    @pytest.mark.asyncio
    async def test_registry_chat_with_fallback(self) -> None:
        """chat_with_fallback should work like generate_with_fallback."""
        registry = LLMProviderRegistry()

        class ChatProvider(BaseLLMProvider):
            async def generate(
                self, prompt: str, options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("", "m", "p")

            async def chat(
                self, messages: list[ChatMessage], options: LLMOptions | None = None
            ) -> LLMResponse:
                return LLMResponse.success("Chat response", "m", self._name)

            async def get_model_info(self, model: str) -> ModelInfo | None:
                return None

            async def list_models(self) -> list[str]:
                return []

            async def get_health(self) -> LLMHealthStatus:
                return LLMHealthStatus.healthy()

        registry.register(ChatProvider("chat"))

        messages = [ChatMessage(role="user", content="Hi")]
        response = await registry.chat_with_fallback(messages)

        assert response.ok is True
        assert response.text == "Chat response"
