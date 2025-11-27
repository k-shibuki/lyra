"""
Unit tests for LLM provider abstraction layer.

Tests the LLMProvider protocol, OllamaProvider implementation, and registry.
Follows §7.1 test quality standards:
- No conditional assertions
- Specific expected values
- Proper boundary testing
- Realistic test data
"""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
from src.filter.ollama_provider import OllamaProvider, create_ollama_provider


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset global registry before each test."""
    reset_llm_registry()
    yield
    reset_llm_registry()


@pytest.fixture
def mock_aiohttp_session():
    """Create a mock aiohttp session."""
    session = AsyncMock()
    session.closed = False
    return session


@pytest.fixture
def ollama_provider():
    """Create an OllamaProvider for testing."""
    return OllamaProvider(
        host="http://localhost:11434",
        fast_model="test-fast:3b",
        slow_model="test-slow:7b",
    )


# ============================================================================
# Data Class Tests
# ============================================================================


class TestLLMOptions:
    """Tests for LLMOptions dataclass."""
    
    def test_default_values(self):
        """LLMOptions should have None defaults for optional fields."""
        options = LLMOptions()
        
        assert options.model is None
        assert options.temperature is None
        assert options.max_tokens is None
        assert options.top_p is None
        assert options.top_k is None
        assert options.stop is None
        assert options.system is None
        assert options.timeout is None
    
    def test_to_dict_excludes_none(self):
        """to_dict should exclude None values."""
        options = LLMOptions(model="test", temperature=0.7)
        result = options.to_dict()
        
        assert result == {"model": "test", "temperature": 0.7}
        assert "max_tokens" not in result
    
    def test_to_dict_includes_all_set_values(self):
        """to_dict should include all explicitly set values."""
        options = LLMOptions(
            model="gpt-4",
            temperature=0.5,
            max_tokens=100,
            top_p=0.9,
            stop=[".", "!"],
        )
        result = options.to_dict()
        
        assert result["model"] == "gpt-4"
        assert result["temperature"] == 0.5
        assert result["max_tokens"] == 100
        assert result["top_p"] == 0.9
        assert result["stop"] == [".", "!"]


class TestChatMessage:
    """Tests for ChatMessage dataclass."""
    
    def test_basic_message(self):
        """ChatMessage should store role and content."""
        msg = ChatMessage(role="user", content="Hello")
        
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None
    
    def test_to_dict_basic(self):
        """to_dict should return role and content."""
        msg = ChatMessage(role="assistant", content="Hi there")
        result = msg.to_dict()
        
        assert result == {"role": "assistant", "content": "Hi there"}
    
    def test_to_dict_with_name(self):
        """to_dict should include name when set."""
        msg = ChatMessage(role="user", content="Test", name="alice")
        result = msg.to_dict()
        
        assert result["name"] == "alice"
    
    def test_from_dict(self):
        """from_dict should reconstruct ChatMessage."""
        data = {"role": "system", "content": "You are helpful"}
        msg = ChatMessage.from_dict(data)
        
        assert msg.role == "system"
        assert msg.content == "You are helpful"
    
    def test_from_dict_defaults(self):
        """from_dict should use defaults for missing keys."""
        msg = ChatMessage.from_dict({})
        
        assert msg.role == "user"
        assert msg.content == ""


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""
    
    def test_success_response(self):
        """success() should create a successful response."""
        response = LLMResponse.success(
            text="Generated text",
            model="test-model",
            provider="test-provider",
            elapsed_ms=100.5,
        )
        
        assert response.ok is True
        assert response.text == "Generated text"
        assert response.model == "test-model"
        assert response.provider == "test-provider"
        assert response.elapsed_ms == 100.5
        assert response.status == LLMResponseStatus.SUCCESS
        assert response.error is None
    
    def test_error_response(self):
        """make_error() should create an error response."""
        response = LLMResponse.make_error(
            error="Connection failed",
            model="test-model",
            provider="test-provider",
        )
        
        assert response.ok is False
        assert response.text == ""
        assert response.error == "Connection failed"
        assert response.status == LLMResponseStatus.ERROR
    
    def test_timeout_error(self):
        """make_error() with TIMEOUT status should indicate timeout."""
        response = LLMResponse.make_error(
            error="Request timed out",
            model="test-model",
            provider="test-provider",
            status=LLMResponseStatus.TIMEOUT,
        )
        
        assert response.status == LLMResponseStatus.TIMEOUT
        assert response.ok is False
    
    def test_to_dict_serialization(self):
        """to_dict should include ok property."""
        response = LLMResponse.success(
            text="Test",
            model="m",
            provider="p",
        )
        result = response.to_dict()
        
        assert result["ok"] is True
        assert result["text"] == "Test"
        assert result["status"] == "success"


class TestEmbeddingResponse:
    """Tests for EmbeddingResponse dataclass."""
    
    def test_success_embedding(self):
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
    
    def test_error_embedding(self):
        """error() should create an error embedding response."""
        response = EmbeddingResponse.error(
            error="Embedding failed",
            model="embed-model",
            provider="test-provider",
        )
        
        assert response.ok is False
        assert response.embeddings == []
        assert response.error == "Embedding failed"


class TestModelInfo:
    """Tests for ModelInfo dataclass."""
    
    def test_basic_model_info(self):
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
    
    def test_to_dict(self):
        """to_dict should serialize capabilities as strings."""
        info = ModelInfo(
            name="test",
            capabilities=[ModelCapability.EMBEDDING],
        )
        result = info.to_dict()
        
        assert result["capabilities"] == ["embedding"]


class TestLLMHealthStatus:
    """Tests for LLMHealthStatus dataclass."""
    
    def test_healthy_status(self):
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
    
    def test_degraded_status(self):
        """degraded() should indicate partial health."""
        status = LLMHealthStatus.degraded(
            success_rate=0.7,
            message="High latency detected",
        )
        
        assert status.state == LLMHealthState.DEGRADED
        assert status.success_rate == 0.7
        assert status.message == "High latency detected"
    
    def test_unhealthy_status(self):
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
    
    def test_protocol_is_runtime_checkable(self):
        """LLMProvider should be runtime checkable."""
        # A minimal implementation that satisfies the protocol
        class MinimalProvider:
            @property
            def name(self) -> str:
                return "minimal"
            
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            
            async def embed(self, texts, model=None):
                return EmbeddingResponse.success([], "m", "p")
            
            async def get_model_info(self, model):
                return None
            
            async def list_models(self):
                return []
            
            async def get_health(self):
                return LLMHealthStatus.healthy()
            
            async def unload_model(self, model=None):
                return True
            
            async def close(self):
                pass
        
        provider = MinimalProvider()
        assert isinstance(provider, LLMProvider)


class TestBaseLLMProvider:
    """Tests for BaseLLMProvider abstract base class."""
    
    def test_init_sets_name(self):
        """BaseLLMProvider should set provider name."""
        class TestProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        provider = TestProvider("my-provider")
        assert provider.name == "my-provider"
        assert provider.is_closed is False
    
    def test_set_task_id(self):
        """set_task_id should track current task."""
        class TestProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        provider = TestProvider("test")
        provider.set_task_id("task-123")
        assert provider._current_task_id == "task-123"
    
    @pytest.mark.asyncio
    async def test_close_marks_closed(self):
        """close() should mark provider as closed."""
        class TestProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        provider = TestProvider("test")
        await provider.close()
        assert provider.is_closed is True
    
    @pytest.mark.asyncio
    async def test_embed_default_not_supported(self):
        """Default embed implementation should return error."""
        class TestProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        provider = TestProvider("test")
        response = await provider.embed(["hello"])
        
        assert response.ok is False
        assert "not supported" in response.error.lower()


# ============================================================================
# OllamaProvider Tests
# ============================================================================


class TestOllamaProviderInit:
    """Tests for OllamaProvider initialization."""
    
    def test_default_configuration(self):
        """OllamaProvider should use settings defaults."""
        with patch('src.filter.ollama_provider.get_settings') as mock_settings:
            mock_settings.return_value.llm.ollama_host = "http://test:11434"
            mock_settings.return_value.llm.fast_model = "custom-fast"
            mock_settings.return_value.llm.slow_model = "custom-slow"
            mock_settings.return_value.llm.temperature = 0.5
            
            provider = OllamaProvider()
            
            assert provider.host == "http://test:11434"
            assert provider.fast_model == "custom-fast"
            assert provider.slow_model == "custom-slow"
    
    def test_explicit_configuration(self):
        """OllamaProvider should accept explicit configuration."""
        provider = OllamaProvider(
            host="http://custom:11434",
            fast_model="my-fast:3b",
            slow_model="my-slow:7b",
        )
        
        assert provider.host == "http://custom:11434"
        assert provider.fast_model == "my-fast:3b"
        assert provider.slow_model == "my-slow:7b"
    
    def test_provider_name(self):
        """OllamaProvider should have name 'ollama'."""
        provider = OllamaProvider()
        assert provider.name == "ollama"


class TestOllamaProviderGenerate:
    """Tests for OllamaProvider.generate()."""
    
    @pytest.mark.asyncio
    async def test_generate_success(self, ollama_provider):
        """generate() should return success response on 200."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "response": "Generated text here",
            "prompt_eval_count": 10,
            "eval_count": 20,
        })
        
        # Create a proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")
        
        assert response.ok is True
        assert response.text == "Generated text here"
        assert response.model == "test-fast:3b"
        assert response.provider == "ollama"
        assert response.usage["prompt_tokens"] == 10
        assert response.usage["completion_tokens"] == 20
    
    @pytest.mark.asyncio
    async def test_generate_with_options(self, ollama_provider):
        """generate() should pass options to API."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "OK"})
        
        captured_payload = {}
        
        # Create a proper async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        def capture_post(url, json, timeout=None):
            captured_payload.update(json)
            return mock_cm
        
        mock_session = MagicMock()
        mock_session.post = capture_post
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
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
    async def test_generate_api_error(self, ollama_provider):
        """generate() should return error response on non-200."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal server error")
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            response = await ollama_provider.generate("Test prompt")
        
        assert response.ok is False
        assert "500" in response.error
        assert response.status == LLMResponseStatus.ERROR
    
    @pytest.mark.asyncio
    async def test_generate_tracks_model(self, ollama_provider):
        """generate() should track current model for cleanup."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"response": "OK"})
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            await ollama_provider.generate("Test")
        
        assert ollama_provider._current_model == "test-fast:3b"


class TestOllamaProviderChat:
    """Tests for OllamaProvider.chat()."""
    
    @pytest.mark.asyncio
    async def test_chat_success(self, ollama_provider):
        """chat() should return assistant response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "message": {"content": "Hello! How can I help?"},
        })
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            messages = [ChatMessage(role="user", content="Hi")]
            response = await ollama_provider.chat(messages)
        
        assert response.ok is True
        assert response.text == "Hello! How can I help?"
    
    @pytest.mark.asyncio
    async def test_chat_converts_messages(self, ollama_provider):
        """chat() should convert ChatMessage to dict format."""
        captured_payload = {}
        
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"message": {"content": "OK"}})
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        def capture_post(url, json, timeout=None):
            captured_payload.update(json)
            return mock_cm
        
        mock_session = MagicMock()
        mock_session.post = capture_post
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
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
    async def test_embed_success(self, ollama_provider):
        """embed() should return embedding vectors."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        })
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            response = await ollama_provider.embed(["text1", "text2"])
        
        assert response.ok is True
        assert len(response.embeddings) == 2
        assert response.embeddings[0] == [0.1, 0.2, 0.3]


class TestOllamaProviderHealth:
    """Tests for OllamaProvider.get_health()."""
    
    @pytest.mark.asyncio
    async def test_health_healthy(self, ollama_provider):
        """get_health() should return healthy when API responds."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "models": [{"name": "model1"}, {"name": "model2"}],
        })
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            health = await ollama_provider.get_health()
        
        assert health.state == LLMHealthState.HEALTHY
        assert "model1" in health.available_models
        assert "model2" in health.available_models
    
    @pytest.mark.asyncio
    async def test_health_unhealthy_on_error(self, ollama_provider):
        """get_health() should return unhealthy on connection error."""
        mock_cm = AsyncMock()
        mock_cm.__aenter__.side_effect = Exception("Connection refused")
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            health = await ollama_provider.get_health()
        
        assert health.state == LLMHealthState.UNHEALTHY
        assert "Connection refused" in health.message
    
    @pytest.mark.asyncio
    async def test_health_closed_provider(self, ollama_provider):
        """get_health() should return unhealthy when closed."""
        ollama_provider._is_closed = True
        
        health = await ollama_provider.get_health()
        
        assert health.state == LLMHealthState.UNHEALTHY
        assert "closed" in health.message.lower()


class TestOllamaProviderUnload:
    """Tests for OllamaProvider.unload_model()."""
    
    @pytest.mark.asyncio
    async def test_unload_success(self, ollama_provider):
        """unload_model() should call API with keep_alive=0."""
        ollama_provider._current_model = "test-model"
        
        captured_payload = {}
        
        mock_response = MagicMock()
        mock_response.status = 200
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        def capture_post(url, json, timeout=None):
            captured_payload.update(json)
            return mock_cm
        
        mock_session = MagicMock()
        mock_session.post = capture_post
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            result = await ollama_provider.unload_model()
        
        assert result is True
        assert captured_payload["keep_alive"] == 0
        assert captured_payload["model"] == "test-model"
        assert ollama_provider._current_model is None
    
    @pytest.mark.asyncio
    async def test_unload_no_current_model(self, ollama_provider):
        """unload_model() should return False when no model loaded."""
        ollama_provider._current_model = None
        
        result = await ollama_provider.unload_model()
        
        assert result is False


class TestOllamaProviderListModels:
    """Tests for OllamaProvider.list_models()."""
    
    @pytest.mark.asyncio
    async def test_list_models_success(self, ollama_provider):
        """list_models() should return available models."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "models": [
                {"name": "qwen2.5:3b", "details": {"parameter_size": "3B"}},
                {"name": "llama2:7b", "details": {"parameter_size": "7B"}},
            ],
        })
        
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_response
        mock_cm.__aexit__.return_value = None
        
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        
        with patch.object(ollama_provider, '_get_session', AsyncMock(return_value=mock_session)):
            models = await ollama_provider.list_models()
        
        assert len(models) == 2
        assert models[0].name == "qwen2.5:3b"
        assert models[0].size == "3B"
        assert models[1].name == "llama2:7b"


# ============================================================================
# LLMProviderRegistry Tests
# ============================================================================


class TestLLMProviderRegistry:
    """Tests for LLMProviderRegistry."""
    
    def test_register_provider(self):
        """register() should add provider to registry."""
        registry = LLMProviderRegistry()
        provider = OllamaProvider()
        
        registry.register(provider)
        
        assert "ollama" in registry.list_providers()
        assert registry.get("ollama") is provider
    
    def test_register_sets_default(self):
        """First registered provider should become default."""
        registry = LLMProviderRegistry()
        provider = OllamaProvider()
        
        registry.register(provider)
        
        assert registry.get_default() is provider
    
    def test_register_duplicate_raises(self):
        """register() should raise on duplicate name."""
        registry = LLMProviderRegistry()
        provider1 = OllamaProvider()
        provider2 = OllamaProvider()
        
        registry.register(provider1)
        
        with pytest.raises(ValueError, match="already registered"):
            registry.register(provider2)
    
    def test_unregister_provider(self):
        """unregister() should remove provider."""
        registry = LLMProviderRegistry()
        provider = OllamaProvider()
        registry.register(provider)
        
        removed = registry.unregister("ollama")
        
        assert removed is provider
        assert "ollama" not in registry.list_providers()
    
    def test_unregister_updates_default(self):
        """unregister() should update default when default is removed."""
        registry = LLMProviderRegistry()
        
        class Provider1(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        p1 = Provider1("provider1")
        p2 = Provider1("provider2")
        
        registry.register(p1)
        registry.register(p2)
        
        registry.unregister("provider1")
        
        assert registry.get_default() is p2
    
    def test_set_default(self):
        """set_default() should change default provider."""
        registry = LLMProviderRegistry()
        
        class Provider1(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        p1 = Provider1("provider1")
        p2 = Provider1("provider2")
        
        registry.register(p1)
        registry.register(p2)
        
        registry.set_default("provider2")
        
        assert registry.get_default() is p2
    
    def test_set_default_nonexistent_raises(self):
        """set_default() should raise for unknown provider."""
        registry = LLMProviderRegistry()
        
        with pytest.raises(ValueError, match="not registered"):
            registry.set_default("unknown")
    
    @pytest.mark.asyncio
    async def test_generate_with_fallback_success(self):
        """generate_with_fallback() should return on first success."""
        registry = LLMProviderRegistry()
        
        class SuccessProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("Success!", "m", self._name)
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        registry.register(SuccessProvider("good"))
        
        response = await registry.generate_with_fallback("Test prompt")
        
        assert response.ok is True
        assert response.text == "Success!"
        assert response.provider == "good"
    
    @pytest.mark.asyncio
    async def test_generate_with_fallback_tries_multiple(self):
        """generate_with_fallback() should try next provider on failure."""
        registry = LLMProviderRegistry()
        
        class FailProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.make_error("Failed", "m", self._name)
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        class SuccessProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("OK", "m", self._name)
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        registry.register(FailProvider("fail"))
        registry.register(SuccessProvider("success"))
        
        response = await registry.generate_with_fallback("Test")
        
        assert response.ok is True
        assert response.provider == "success"
    
    @pytest.mark.asyncio
    async def test_generate_with_fallback_skips_unhealthy(self):
        """generate_with_fallback() should skip unhealthy providers."""
        registry = LLMProviderRegistry()
        
        class UnhealthyProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("Should not reach", "m", self._name)
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.unhealthy("Down for maintenance")
        
        class HealthyProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("From healthy", "m", self._name)
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        registry.register(UnhealthyProvider("unhealthy"))
        registry.register(HealthyProvider("healthy"))
        
        response = await registry.generate_with_fallback("Test")
        
        assert response.ok is True
        assert response.provider == "healthy"
    
    @pytest.mark.asyncio
    async def test_generate_with_fallback_all_fail(self):
        """generate_with_fallback() should return error when all fail."""
        registry = LLMProviderRegistry()
        
        class FailProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.make_error("Failed", "m", self._name)
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        registry.register(FailProvider("fail1"))
        registry.register(FailProvider("fail2"))
        
        response = await registry.generate_with_fallback("Test")
        
        assert response.ok is False
        assert "All providers failed" in response.error
    
    @pytest.mark.asyncio
    async def test_generate_with_fallback_no_providers(self):
        """generate_with_fallback() should raise when no providers."""
        registry = LLMProviderRegistry()
        
        with pytest.raises(RuntimeError, match="No LLM providers registered"):
            await registry.generate_with_fallback("Test")
    
    @pytest.mark.asyncio
    async def test_close_all(self):
        """close_all() should close all providers."""
        registry = LLMProviderRegistry()
        
        close_called = []
        
        class TrackingProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("", "m", "p")
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
            async def close(self):
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
    
    def test_get_llm_registry_creates_singleton(self):
        """get_llm_registry() should return same instance."""
        r1 = get_llm_registry()
        r2 = get_llm_registry()
        
        assert r1 is r2
    
    def test_reset_llm_registry(self):
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
    async def test_llm_extract_with_provider(self):
        """llm_extract should work with provider abstraction."""
        from src.filter.llm import llm_extract
        
        # Mock the provider
        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.fast_model = "test-fast"
        mock_provider.slow_model = "test-slow"
        mock_provider.generate = AsyncMock(return_value=LLMResponse.success(
            text='[{"fact": "Test fact", "confidence": 0.9}]',
            model="test",
            provider="mock",
        ))
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
    async def test_generate_with_provider_function(self):
        """generate_with_provider should use registry."""
        from src.filter.llm import generate_with_provider
        
        mock_provider = AsyncMock()
        mock_provider.name = "mock"
        mock_provider.generate = AsyncMock(return_value=LLMResponse.success(
            text="Generated output",
            model="test",
            provider="mock",
        ))
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
    
    def test_empty_chat_messages(self):
        """ChatMessage.from_dict should handle empty dict."""
        msg = ChatMessage.from_dict({})
        assert msg.role == "user"
        assert msg.content == ""
    
    def test_llm_options_all_none(self):
        """LLMOptions.to_dict should return empty dict when all None."""
        options = LLMOptions()
        result = options.to_dict()
        assert result == {}
    
    @pytest.mark.asyncio
    async def test_provider_check_closed(self, ollama_provider):
        """Closed provider should raise on operations."""
        ollama_provider._is_closed = True
        
        with pytest.raises(RuntimeError, match="closed"):
            await ollama_provider.generate("test")
    
    def test_model_info_empty_capabilities(self):
        """ModelInfo should handle empty capabilities."""
        info = ModelInfo(name="test")
        assert info.capabilities == []
        assert info.to_dict()["capabilities"] == []
    
    @pytest.mark.asyncio
    async def test_registry_chat_with_fallback(self):
        """chat_with_fallback should work like generate_with_fallback."""
        registry = LLMProviderRegistry()
        
        class ChatProvider(BaseLLMProvider):
            async def generate(self, prompt, options=None):
                return LLMResponse.success("", "m", "p")
            async def chat(self, messages, options=None):
                return LLMResponse.success("Chat response", "m", self._name)
            async def get_model_info(self, model):
                return None
            async def list_models(self):
                return []
            async def get_health(self):
                return LLMHealthStatus.healthy()
        
        registry.register(ChatProvider("chat"))
        
        messages = [ChatMessage(role="user", content="Hi")]
        response = await registry.chat_with_fallback(messages)
        
        assert response.ok is True
        assert response.text == "Chat response"

