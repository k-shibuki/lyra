"""
Tests for process lifecycle management.

Per §4.2: Browser instances and LLM processes should be destroyed (Kill)
after each task completion to prevent memory leaks.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-LC-N-01 | ResourceInfo creation | Equivalence – normal | Correct defaults set | Dataclass init |
| TC-LC-N-02 | ResourceInfo with task_id | Equivalence – normal | task_id stored | With optional param |
| TC-LC-N-03 | touch() method | Equivalence – normal | last_used_at updated | Timestamp update |
| TC-LC-N-04 | Register resource | Equivalence – normal | Count increases | Basic registration |
| TC-LC-N-05 | Unregister resource | Equivalence – normal | Count decreases | Without cleanup |
| TC-LC-N-06 | Cleanup browser | Equivalence – normal | close() called, removed | Browser cleanup |
| TC-LC-N-07 | Cleanup browser context | Equivalence – normal | close() called | Context cleanup |
| TC-LC-N-08 | Cleanup Playwright | Equivalence – normal | stop() called | Playwright cleanup |
| TC-LC-N-09 | Cleanup HTTP session | Equivalence – normal | close() called | Session cleanup |
| TC-LC-N-10 | Cleanup Tor controller | Equivalence – normal | close() called | Tor cleanup |
| TC-LC-N-11 | Cleanup task resources | Equivalence – normal | All task resources cleaned | Task-scoped cleanup |
| TC-LC-N-12 | Cleanup all resources | Equivalence – normal | All resources cleaned | Global cleanup |
| TC-LC-A-01 | Cleanup nonexistent | Equivalence – error | Returns False | Missing resource |
| TC-LC-N-13 | Cleanup stale resources | Equivalence – normal | Old resources cleaned | Age-based cleanup |
| TC-LC-N-14 | Cleanup callback | Equivalence – normal | Callback executed | Callback registration |
| TC-LC-N-15 | Touch resource | Equivalence – normal | Timestamp updated | Via manager |
| TC-LC-N-16 | Count with filters | Equivalence – normal | Correct filtered counts | Type/task filters |
| TC-LC-N-17 | Ollama session cleanup | Equivalence – normal | Session closed | With model unload |
| TC-LC-N-18 | Singleton manager | Equivalence – normal | Same instance returned | get_lifecycle_manager |
| TC-LC-N-19 | cleanup_task function | Equivalence – normal | Task resources cleaned | Convenience function |
| TC-LC-N-20 | cleanup_all function | Equivalence – normal | All resources cleaned | Convenience function |
| TC-LC-N-21 | register_browser helper | Equivalence – normal | 3 resources registered | Browser helper |
| TC-LC-N-22 | register_ollama helper | Equivalence – normal | 1 resource registered | Ollama helper |
| TC-LC-A-02 | close() throws exception | Equivalence – error | Error logged, resource removed | Exception handling |
| TC-LC-A-03 | Callback exception | Equivalence – error | Other callbacks still run | Isolation |
| TC-LC-N-23 | set_task_id | Equivalence – normal | task_id stored | OllamaClient |
| TC-LC-N-24 | unload_model | Equivalence – normal | Model unloaded | OllamaClient |
| TC-LC-N-25 | cleanup_llm_for_task | Equivalence – normal | LLM cleaned | Convenience function |
| TC-LC-N-26 | set_llm_task_id | Equivalence – normal | task_id set | Convenience function |
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

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

class TestResourceInfo:
    """Tests for ResourceInfo dataclass."""
    
    def test_resource_info_creation(self):
        """Test ResourceInfo is created with correct defaults."""
        # Given: ResourceInfo constructor with minimal args
        # When: Create ResourceInfo
        info = ResourceInfo(
            resource_type=ResourceType.BROWSER,
            resource=MagicMock(),
        )
        
        # Then: Defaults are correctly set
        assert info.resource_type == ResourceType.BROWSER
        assert info.task_id is None
        assert info.created_at > 0
        assert info.last_used_at > 0
    
    def test_resource_info_with_task_id(self):
        """Test ResourceInfo with task ID."""
        # Given/When: Create ResourceInfo with task_id
        info = ResourceInfo(
            resource_type=ResourceType.OLLAMA_SESSION,
            resource={"session": MagicMock()},
            task_id="task_123",
        )
        
        # Then: task_id is stored
        assert info.task_id == "task_123"
    
    def test_touch_updates_last_used(self):
        """Test touch() updates last_used_at timestamp."""
        # Given: A ResourceInfo instance
        info = ResourceInfo(
            resource_type=ResourceType.BROWSER,
            resource=MagicMock(),
        )
        
        initial_time = info.last_used_at
        import time
        time.sleep(0.01)
        
        # When: Touch the resource
        info.touch()
        
        # Then: last_used_at is updated
        assert info.last_used_at >= initial_time


# =============================================================================
# Unit Tests for ProcessLifecycleManager
# =============================================================================

class TestProcessLifecycleManager:
    """Tests for ProcessLifecycleManager."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh lifecycle manager for each test."""
        return ProcessLifecycleManager()
    
    @pytest.mark.asyncio
    async def test_register_resource(self, manager):
        """Test registering a resource."""
        # Given: A mock browser resource
        mock_browser = MagicMock()
        
        # When: Register the resource
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
            "task_123",
        )
        
        # Then: Resource count increases
        assert manager.get_resource_count() == 1
        assert manager.get_resource_count(ResourceType.BROWSER) == 1
        assert manager.get_resource_count(task_id="task_123") == 1
    
    @pytest.mark.asyncio
    async def test_unregister_resource(self, manager):
        """Test unregistering a resource without cleanup."""
        # Given: A registered resource
        mock_browser = MagicMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        assert manager.get_resource_count() == 1
        
        # When: Unregister the resource
        await manager.unregister_resource("browser_1")
        
        # Then: Resource count is 0
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_browser_resource(self, manager):
        """Test cleaning up a browser resource calls close()."""
        # Given: A registered browser resource
        mock_browser = AsyncMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        # When: Cleanup the resource
        success = await manager.cleanup_resource("browser_1")
        
        # Then: close() is called and resource is removed
        assert success is True
        mock_browser.close.assert_called_once()
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_browser_context_resource(self, manager):
        """Test cleaning up a browser context resource."""
        # Given: A registered browser context
        mock_context = AsyncMock()
        
        await manager.register_resource(
            "context_1",
            ResourceType.BROWSER_CONTEXT,
            mock_context,
        )
        
        # When: Cleanup the resource
        success = await manager.cleanup_resource("context_1")
        
        # Then: close() is called
        assert success is True
        mock_context.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_playwright_resource(self, manager):
        """Test cleaning up a Playwright instance."""
        # Given: A registered Playwright instance
        mock_playwright = AsyncMock()
        
        await manager.register_resource(
            "playwright_1",
            ResourceType.PLAYWRIGHT,
            mock_playwright,
        )
        
        # When: Cleanup the resource
        success = await manager.cleanup_resource("playwright_1")
        
        # Then: stop() is called
        assert success is True
        mock_playwright.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_http_session_resource(self, manager):
        """Test cleaning up an HTTP session."""
        # Given: A registered HTTP session
        mock_session = AsyncMock()
        mock_session.closed = False
        
        await manager.register_resource(
            "session_1",
            ResourceType.HTTP_SESSION,
            mock_session,
        )
        
        # When: Cleanup the resource
        success = await manager.cleanup_resource("session_1")
        
        # Then: close() is called
        assert success is True
        mock_session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_tor_controller_resource(self, manager):
        """Test cleaning up a Tor controller."""
        # Given: A registered Tor controller
        mock_controller = MagicMock()
        
        await manager.register_resource(
            "tor_1",
            ResourceType.TOR_CONTROLLER,
            mock_controller,
        )
        
        # When: Cleanup the resource
        success = await manager.cleanup_resource("tor_1")
        
        # Then: close() is called
        assert success is True
        mock_controller.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_task_resources(self, manager):
        """Test cleaning up all resources for a task."""
        # Given: Resources for two different tasks
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
        
        mock_browser_2 = AsyncMock()
        await manager.register_resource(
            "browser_2",
            ResourceType.BROWSER,
            mock_browser_2,
            "task_456",
        )
        
        assert manager.get_resource_count() == 3
        
        # When: Cleanup resources for task_123
        results = await manager.cleanup_task_resources("task_123")
        
        # Then: Only task_123 resources are cleaned
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
        # Given: Multiple registered resources
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
        
        # When: Cleanup all resources
        results = await manager.cleanup_all()
        
        # Then: All resources are cleaned
        assert len(results) == 3
        assert all(v is True for v in results.values())
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_resource(self, manager):
        """Test cleaning up a resource that doesn't exist."""
        # Given: No resources registered
        # When: Try to cleanup nonexistent resource
        success = await manager.cleanup_resource("nonexistent")
        
        # Then: Returns False
        assert success is False
    
    @pytest.mark.asyncio
    async def test_cleanup_stale_resources(self, manager):
        """Test cleaning up stale resources."""
        # Given: A resource with old timestamps
        mock_browser = AsyncMock()
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        info = manager._resources["browser_1"]
        info.created_at = 0
        info.last_used_at = 0
        
        # When: Cleanup stale resources
        results = await manager.cleanup_stale_resources(
            max_age_seconds=1,
            max_idle_seconds=1,
        )
        
        # Then: Stale resource is cleaned
        assert len(results) == 1
        assert results["browser_1"] is True
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_register_cleanup_callback(self, manager):
        """Test registering and running cleanup callbacks."""
        # Given: A cleanup callback
        callback_called = False
        
        async def cleanup_callback():
            nonlocal callback_called
            callback_called = True
        
        manager.register_cleanup_callback(cleanup_callback)
        
        # When: Cleanup all
        await manager.cleanup_all()
        
        # Then: Callback is executed
        assert callback_called is True
    
    def test_touch_resource(self, manager):
        """Test touching a resource updates timestamp."""
        # Given: A registered resource
        asyncio.run(manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            MagicMock(),
        ))
        
        initial_time = manager._resources["browser_1"].last_used_at
        
        import time
        time.sleep(0.01)
        
        # When: Touch the resource
        manager.touch_resource("browser_1")
        
        # Then: Timestamp is updated
        assert manager._resources["browser_1"].last_used_at >= initial_time
    
    def test_get_resource_count_filters(self, manager):
        """Test get_resource_count with filters."""
        # Given: Resources of different types and tasks
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
        
        # When/Then: Filtered counts are correct
        assert manager.get_resource_count() == 3
        assert manager.get_resource_count(ResourceType.BROWSER) == 2
        assert manager.get_resource_count(ResourceType.BROWSER_CONTEXT) == 1
        assert manager.get_resource_count(task_id="task_1") == 2
        assert manager.get_resource_count(task_id="task_2") == 1
        assert manager.get_resource_count(ResourceType.BROWSER, "task_1") == 1


# =============================================================================
# Unit Tests for Ollama Session Cleanup
# =============================================================================

class TestOllamaSessionCleanup:
    """Tests for Ollama session lifecycle management."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh lifecycle manager."""
        return ProcessLifecycleManager()
    
    @pytest.mark.asyncio
    async def test_cleanup_ollama_session_with_unload(self, manager):
        """Test cleaning up Ollama session unloads model when configured."""
        # Given: An Ollama session resource with unload configured
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
            
            mock_response = MagicMock()
            mock_response.status = 200
            
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__.return_value = mock_response
            
            mock_client_instance = MagicMock()
            mock_client_instance.post.return_value = mock_post_cm
            
            mock_client_cm = AsyncMock()
            mock_client_cm.__aenter__.return_value = mock_client_instance
            
            # When: Cleanup the Ollama session
            with patch('aiohttp.ClientSession', return_value=mock_client_cm):
                success = await manager.cleanup_resource("ollama_1")
                
                # Then: Session is closed
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
        # Given/When: Get lifecycle manager twice
        manager1 = get_lifecycle_manager()
        manager2 = get_lifecycle_manager()
        
        # Then: Same instance is returned
        assert manager1 is manager2
    
    @pytest.mark.asyncio
    async def test_cleanup_task_convenience_function(self):
        """Test cleanup_task convenience function."""
        # Given: A task with registered resources
        manager = get_lifecycle_manager()
        
        mock_browser = AsyncMock()
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
            "task_123",
        )
        
        # When: Call cleanup_task
        results = await cleanup_task("task_123")
        
        # Then: Task resources are cleaned
        assert len(results) == 1
        assert results["browser_1"] is True
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_all_resources_convenience_function(self):
        """Test cleanup_all_resources convenience function."""
        # Given: A registered resource
        manager = get_lifecycle_manager()
        
        mock_browser = AsyncMock()
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        # When: Call cleanup_all_resources
        results = await cleanup_all_resources()
        
        # Then: All resources are cleaned
        assert len(results) == 1
        mock_browser.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_register_browser_for_task(self):
        """Test register_browser_for_task helper."""
        # Given: Browser, context, and Playwright mocks
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_playwright = MagicMock()
        
        # When: Register browser for task
        resource_ids = await register_browser_for_task(
            "task_123",
            mock_browser,
            mock_context,
            mock_playwright,
        )
        
        # Then: 3 resources are registered
        assert len(resource_ids) == 3
        
        manager = get_lifecycle_manager()
        assert manager.get_resource_count(task_id="task_123") == 3
    
    @pytest.mark.asyncio
    async def test_register_ollama_session_for_task(self):
        """Test register_ollama_session_for_task helper."""
        # Given: A mock Ollama session
        mock_session = MagicMock()
        
        # When: Register Ollama session for task
        resource_id = await register_ollama_session_for_task(
            "task_123",
            mock_session,
            "qwen2.5:3b",
        )
        
        # Then: Resource is registered with correct ID format
        assert resource_id.startswith("ollama_task_123_")
        
        manager = get_lifecycle_manager()
        assert manager.get_resource_count(task_id="task_123") == 1
        assert manager.get_resource_count(ResourceType.OLLAMA_SESSION) == 1


# =============================================================================
# Error Handling Tests
# =============================================================================

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
        # Given: A resource whose close() throws an exception
        mock_browser = AsyncMock()
        mock_browser.close.side_effect = Exception("Connection lost")
        
        await manager.register_resource(
            "browser_1",
            ResourceType.BROWSER,
            mock_browser,
        )
        
        # When: Cleanup the resource
        success = await manager.cleanup_resource("browser_1")
        
        # Then: Cleanup completes without propagating exception
        assert success is True
        assert manager.get_resource_count() == 0
    
    @pytest.mark.asyncio
    async def test_cleanup_callback_exception_doesnt_stop_others(self, manager):
        """Test exception in one callback doesn't stop other callbacks."""
        # Given: Two callbacks, one that throws
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
        
        # When: Cleanup all
        await manager.cleanup_all()
        
        # Then: Both callbacks are called despite exception
        assert callback1_called is True
        assert callback2_called is True


# =============================================================================
# LLM Cleanup Tests
# =============================================================================

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
        
        # Given: An OllamaClient instance
        client = OllamaClient()
        
        # When: Set task ID
        client.set_task_id("task_123")
        
        # Then: task_id is stored
        assert client._current_task_id == "task_123"
    
    @pytest.mark.asyncio
    async def test_ollama_client_unload_model(self):
        """Test OllamaClient.unload_model()."""
        from src.filter.llm import OllamaClient
        import aiohttp
        
        # Given: An OllamaClient with a loaded model
        client = OllamaClient()
        client._current_model = "qwen2.5:3b"
        
        mock_response = MagicMock()
        mock_response.status = 200
        
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        
        mock_session = MagicMock()
        mock_session.post.return_value = mock_cm
        mock_session.closed = False
        mock_session.close = AsyncMock()
        
        provider = client._get_provider()
        
        async def mock_get_session():
            return mock_session
        
        # When: Unload the model
        with patch.object(provider, '_get_session', mock_get_session):
            result = await client.unload_model()
        
        # Then: Model is unloaded
        assert result is True
        assert client._current_model is None
    
    @pytest.mark.asyncio
    async def test_cleanup_llm_for_task(self):
        """Test cleanup_llm_for_task function."""
        from src.filter.llm import _get_client, cleanup_llm_for_task
        
        # Given: An LLM client with a loaded model
        client = _get_client()
        client._current_model = "qwen2.5:3b"
        
        # When: Cleanup LLM for task
        with patch.object(client, 'cleanup_for_task', new_callable=AsyncMock) as mock_cleanup:
            await cleanup_llm_for_task("task_123")
            
            # Then: cleanup_for_task is called
            mock_cleanup.assert_called_once_with(unload_model=True)
    
    def test_set_llm_task_id(self):
        """Test set_llm_task_id function."""
        from src.filter.llm import _get_client, set_llm_task_id
        
        # Given: An LLM client
        client = _get_client()
        
        # When: Set task ID
        set_llm_task_id("task_456")
        
        # Then: task_id is stored in client
        assert client._current_task_id == "task_456"

