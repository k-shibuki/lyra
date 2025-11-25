"""
Tests for process lifecycle management.

Per §4.2: Browser instances and LLM processes should be destroyed (Kill)
after each task completion to prevent memory leaks.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.lifecycle import (
    ProcessLifecycleManager,
    ResourceInfo,
    ResourceType,
    get_lifecycle_manager,
    cleanup_task,
    cleanup_all_resources,
    register_browser_for_task,
    register_ollama_session_for_task,
)


# =============================================================================
# Unit Tests for ResourceInfo
# =============================================================================

@pytest.mark.unit
class TestResourceInfo:
    """Tests for ResourceInfo dataclass."""
    
    def test_resource_info_creation(self):
        """Test ResourceInfo is created with correct defaults."""
        info = ResourceInfo(
            resource_type=ResourceType.BROWSER,
            resource=MagicMock(),
        )
        
        assert info.resource_type == ResourceType.BROWSER
        assert info.task_id is None
        assert info.created_at > 0
        assert info.last_used_at > 0
    
    def test_resource_info_with_task_id(self):
        """Test ResourceInfo with task ID."""
        info = ResourceInfo(
            resource_type=ResourceType.OLLAMA_SESSION,
            resource={"session": MagicMock()},
            task_id="task_123",
        )
        
        assert info.task_id == "task_123"
    
    def test_touch_updates_last_used(self):
        """Test touch() updates last_used_at timestamp."""
        info = ResourceInfo(
            resource_type=ResourceType.BROWSER,
            resource=MagicMock(),
        )
        
        initial_time = info.last_used_at
        # Small delay to ensure time difference
        import time
        time.sleep(0.01)
        
        info.touch()
        
        assert info.last_used_at >= initial_time


# =============================================================================
# Unit Tests for ProcessLifecycleManager
# =============================================================================

@pytest.mark.unit
class TestProcessLifecycleManager:
    """Tests for ProcessLifecycleManager."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh lifecycle manager for each test."""
        return ProcessLifecycleManager()
    
    @pytest.mark.asyncio
    async def test_register_resource(self, manager):
        """Test registering a resource."""
        mock_browser = MagicMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
            "task_123",
        )
        
        assert manager.get_resource_count() == 1
        assert manager.get_resource_count(ResourceType.BROWSER) == 1
        assert manager.get_resource_count(task_id="task_123") == 1
    
    @pytest.mark.asyncio
    async def test_unregister_resource(self, manager):
        """Test unregistering a resource without cleanup."""
        mock_browser = MagicMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        assert manager.get_resource_count() == 1
        
        await manager.unregister_resource("browser_1")
        
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_browser_resource(self, manager):
        """Test cleaning up a browser resource calls close()."""
        mock_browser = AsyncMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        success = await manager.cleanup_resource("browser_1")
        
        assert success is True
        mock_browser.close.assert_called_once()
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_browser_context_resource(self, manager):
        """Test cleaning up a browser context resource."""
        mock_context = AsyncMock()
        
        await manager.register_resource(
            "context_1",
            ResourceType.BROWSER_CONTEXT,
            mock_context,
        )
        
        success = await manager.cleanup_resource("context_1")
        
        assert success is True
        mock_context.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_playwright_resource(self, manager):
        """Test cleaning up a Playwright instance."""
        mock_playwright = AsyncMock()
        
        await manager.register_resource(
            "playwright_1",
            ResourceType.PLAYWRIGHT,
            mock_playwright,
        )
        
        success = await manager.cleanup_resource("playwright_1")
        
        assert success is True
        mock_playwright.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_http_session_resource(self, manager):
        """Test cleaning up an HTTP session."""
        mock_session = AsyncMock()
        mock_session.closed = False
        
        await manager.register_resource(
            "session_1",
            ResourceType.HTTP_SESSION,
            mock_session,
        )
        
        success = await manager.cleanup_resource("session_1")
        
        assert success is True
        mock_session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_tor_controller_resource(self, manager):
        """Test cleaning up a Tor controller."""
        mock_controller = MagicMock()  # Tor controller uses sync close
        
        await manager.register_resource(
            "tor_1",
            ResourceType.TOR_CONTROLLER,
            mock_controller,
        )
        
        success = await manager.cleanup_resource("tor_1")
        
        assert success is True
        mock_controller.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_task_resources(self, manager):
        """Test cleaning up all resources for a task."""
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
            "task_123",
        )
        await manager.register_resource(
            "context_1",
            ResourceType.BROWSER_CONTEXT,
            mock_context,
            "task_123",
        )
        
        # Register another resource for different task
        mock_browser_2 = AsyncMock()
        await manager.register_resource(
            "browser_2",
            ResourceType.BROWSER,
            mock_browser_2,
            "task_456",
        )
        
        assert manager.get_resource_count() == 3
        
        # Cleanup task_123 resources
        results = await manager.cleanup_task_resources("task_123")
        
        assert len(results) == 2
        assert all(v is True for v in results.values())
        assert manager.get_resource_count() == 1
        assert manager.get_resource_count(task_id="task_456") == 1
        
        mock_browser.close.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser_2.close.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_cleanup_all_resources(self, manager):
        """Test cleaning up all registered resources."""
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_session = AsyncMock()
        mock_session.closed = False
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        await manager.register_resource(
            "context_1",
            ResourceType.BROWSER_CONTEXT,
            mock_context,
        )
        await manager.register_resource(
            "session_1",
            ResourceType.HTTP_SESSION,
            mock_session,
        )
        
        results = await manager.cleanup_all()
        
        assert len(results) == 3
        assert all(v is True for v in results.values())
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_resource(self, manager):
        """Test cleaning up a resource that doesn't exist."""
        success = await manager.cleanup_resource("nonexistent")
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_cleanup_stale_resources(self, manager):
        """Test cleaning up stale resources."""
        mock_browser = AsyncMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        # Manipulate timestamps to make resource stale
        info = manager._resources["browser_1"]
        info.created_at = 0  # Very old
        info.last_used_at = 0
        
        results = await manager.cleanup_stale_resources(
            max_age_seconds=1,
            max_idle_seconds=1,
        )
        
        assert len(results) == 1
        assert results["browser_1"] is True
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_register_cleanup_callback(self, manager):
        """Test registering and running cleanup callbacks."""
        callback_called = False
        
        async def cleanup_callback():
            nonlocal callback_called
            callback_called = True
        
        manager.register_cleanup_callback(cleanup_callback)
        
        await manager.cleanup_all()
        
        assert callback_called is True
    
    def test_touch_resource(self, manager):
        """Test touching a resource updates timestamp."""
        # Need to register first (sync part)
        asyncio.run(manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            MagicMock(),
        ))
        
        initial_time = manager._resources["browser_1"].last_used_at
        
        import time
        time.sleep(0.01)
        
        manager.touch_resource("browser_1")
        
        assert manager._resources["browser_1"].last_used_at >= initial_time
    
    def test_get_resource_count_filters(self, manager):
        """Test get_resource_count with filters."""
        asyncio.run(manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            MagicMock(),
            "task_1",
        ))
        asyncio.run(manager.register_resource(
            "context_1",
            ResourceType.BROWSER_CONTEXT,
            MagicMock(),
            "task_1",
        ))
        asyncio.run(manager.register_resource(
            "browser_2",
            ResourceType.BROWSER,
            MagicMock(),
            "task_2",
        ))
        
        assert manager.get_resource_count() == 3
        assert manager.get_resource_count(ResourceType.BROWSER) == 2
        assert manager.get_resource_count(ResourceType.BROWSER_CONTEXT) == 1
        assert manager.get_resource_count(task_id="task_1") == 2
        assert manager.get_resource_count(task_id="task_2") == 1
        assert manager.get_resource_count(ResourceType.BROWSER, "task_1") == 1


# =============================================================================
# Unit Tests for Ollama Session Cleanup
# =============================================================================

@pytest.mark.unit
class TestOllamaSessionCleanup:
    """Tests for Ollama session lifecycle management."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh lifecycle manager."""
        return ProcessLifecycleManager()
    
    @pytest.mark.asyncio
    async def test_cleanup_ollama_session_with_unload(self, manager):
        """Test cleaning up Ollama session unloads model when configured."""
        mock_session = AsyncMock()
        mock_session.closed = False
        
        with patch.object(manager, '_settings') as mock_settings:
            mock_settings.llm.unload_on_task_complete = True
            mock_settings.llm.ollama_host = "http://localhost:11434"
            
            await manager.register_resource(
                "ollama_1",
                ResourceType.OLLAMA_SESSION,
                {
                    "session": mock_session,
                    "model": "qwen2.5:3b",
                    "host": "http://localhost:11434",
                },
                "task_123",
            )
            
            # Mock the aiohttp session for model unload
            # Create proper async context manager mock
            mock_response = MagicMock()
            mock_response.status = 200
            
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__.return_value = mock_response
            
            mock_client_instance = MagicMock()
            mock_client_instance.post.return_value = mock_post_cm
            
            mock_client_cm = AsyncMock()
            mock_client_cm.__aenter__.return_value = mock_client_instance
            
            with patch('aiohttp.ClientSession', return_value=mock_client_cm):
                success = await manager.cleanup_resource("ollama_1")
                
                assert success is True
                mock_session.close.assert_called_once()


# =============================================================================
# Integration Tests for Convenience Functions
# =============================================================================

@pytest.mark.integration
class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    @pytest.fixture(autouse=True)
    def reset_global_manager(self):
        """Reset global lifecycle manager before each test."""
        import src.utils.lifecycle as lifecycle_module
        lifecycle_module._lifecycle_manager = None
        yield
        lifecycle_module._lifecycle_manager = None
    
    def test_get_lifecycle_manager_singleton(self):
        """Test get_lifecycle_manager returns singleton."""
        manager1 = get_lifecycle_manager()
        manager2 = get_lifecycle_manager()
        
        assert manager1 is manager2
    
    @pytest.mark.asyncio
    async def test_cleanup_task_convenience_function(self):
        """Test cleanup_task convenience function."""
        manager = get_lifecycle_manager()
        
        mock_browser = AsyncMock()
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
            "task_123",
        )
        
        results = await cleanup_task("task_123")
        
        assert len(results) == 1
        assert results["browser_1"] is True
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_all_resources_convenience_function(self):
        """Test cleanup_all_resources convenience function."""
        manager = get_lifecycle_manager()
        
        mock_browser = AsyncMock()
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        results = await cleanup_all_resources()
        
        assert len(results) == 1
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_register_browser_for_task(self):
        """Test register_browser_for_task helper."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_playwright = MagicMock()
        
        resource_ids = await register_browser_for_task(
            "task_123",
            mock_browser,
            mock_context,
            mock_playwright,
        )
        
        assert len(resource_ids) == 3
        
        manager = get_lifecycle_manager()
        assert manager.get_resource_count(task_id="task_123") == 3
    
    @pytest.mark.asyncio
    async def test_register_ollama_session_for_task(self):
        """Test register_ollama_session_for_task helper."""
        mock_session = MagicMock()
        
        resource_id = await register_ollama_session_for_task(
            "task_123",
            mock_session,
            "qwen2.5:3b",
        )
        
        assert resource_id.startswith("ollama_task_123_")
        
        manager = get_lifecycle_manager()
        assert manager.get_resource_count(task_id="task_123") == 1
        assert manager.get_resource_count(ResourceType.OLLAMA_SESSION) == 1


# =============================================================================
# Error Handling Tests
# =============================================================================

@pytest.mark.unit
class TestErrorHandling:
    """Tests for error handling in lifecycle management."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh lifecycle manager."""
        return ProcessLifecycleManager()
    
    @pytest.mark.asyncio
    async def test_cleanup_handles_close_exception(self, manager):
        """Test cleanup handles exceptions from close() gracefully.
        
        Even if close() raises, the cleanup should:
        1. Not propagate the exception
        2. Log the error
        3. Still remove the resource from tracking
        """
        mock_browser = AsyncMock()
        mock_browser.close.side_effect = Exception("Connection lost")
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        # This should not raise even though close() fails
        success = await manager.cleanup_resource("browser_1")
        
        # Browser cleanup logs the error but returns True (cleanup attempted)
        # The important thing is that it doesn't crash
        assert success is True  # Cleanup was attempted, even if close() failed
        # Resource should still be removed from tracking
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_callback_exception_doesnt_stop_others(self, manager):
        """Test exception in one callback doesn't stop other callbacks."""
        callback1_called = False
        callback2_called = False
        
        async def callback1():
            nonlocal callback1_called
            callback1_called = True
            raise Exception("Callback 1 failed")
        
        async def callback2():
            nonlocal callback2_called
            callback2_called = True
        
        manager.register_cleanup_callback(callback1)
        manager.register_cleanup_callback(callback2)
        
        await manager.cleanup_all()
        
        assert callback1_called is True
        assert callback2_called is True


# =============================================================================
# LLM Cleanup Tests
# =============================================================================

@pytest.mark.unit
class TestLLMCleanup:
    """Tests for LLM cleanup functions."""
    
    @pytest.fixture(autouse=True)
    def reset_llm_client(self):
        """Reset global LLM client before each test."""
        import src.filter.llm as llm_module
        llm_module._client = None
        yield
        llm_module._client = None
    
    @pytest.mark.asyncio
    async def test_ollama_client_set_task_id(self):
        """Test OllamaClient.set_task_id()."""
        from src.filter.llm import OllamaClient
        
        client = OllamaClient()
        client.set_task_id("task_123")
        
        assert client._current_task_id == "task_123"
    
    @pytest.mark.asyncio
    async def test_ollama_client_unload_model(self):
        """Test OllamaClient.unload_model()."""
        from src.filter.llm import OllamaClient
        import aiohttp
        
        client = OllamaClient()
        client._current_model = "qwen2.5:3b"
        
        # Mock the entire aiohttp interaction
        with patch('aiohttp.ClientSession') as mock_client_class:
            mock_response = MagicMock()
            mock_response.status = 200
            
            # Create async context manager for response
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            
            # Create async context manager for session
            mock_session = MagicMock()
            mock_session.post.return_value = mock_cm
            mock_session.closed = False
            mock_session.close = AsyncMock()
            
            # Patch _get_session to return our mock
            async def mock_get_session():
                return mock_session
            
            client._get_session = mock_get_session
            
            result = await client.unload_model()
            
            assert result is True
            assert client._current_model is None
    
    @pytest.mark.asyncio
    async def test_cleanup_llm_for_task(self):
        """Test cleanup_llm_for_task function."""
        from src.filter.llm import _get_client, cleanup_llm_for_task
        
        # Initialize client
        client = _get_client()
        client._current_model = "qwen2.5:3b"
        
        with patch.object(client, 'cleanup_for_task', new_callable=AsyncMock) as mock_cleanup:
            await cleanup_llm_for_task("task_123")
            mock_cleanup.assert_called_once_with(unload_model=True)
    
    def test_set_llm_task_id(self):
        """Test set_llm_task_id function."""
        from src.filter.llm import _get_client, set_llm_task_id
        
        # Initialize client
        client = _get_client()
        
        set_llm_task_id("task_456")
        
        assert client._current_task_id == "task_456"

