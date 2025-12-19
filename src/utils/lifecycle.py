"""
Process Lifecycle Management for Lancet.

Per §4.2: Browser instances and LLM processes should be destroyed (Kill)
after each task completion to prevent memory leaks.

This module provides:
- Centralized process lifecycle management
- Browser instance cleanup after task completion
- Ollama context release after task completion
- Resource tracking and automatic cleanup
"""

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import aiohttp

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ResourceType(Enum):
    """Types of managed resources."""

    BROWSER = "browser"
    BROWSER_CONTEXT = "browser_context"
    PLAYWRIGHT = "playwright"
    OLLAMA_SESSION = "ollama_session"
    HTTP_SESSION = "http_session"
    TOR_CONTROLLER = "tor_controller"


@dataclass
class ResourceInfo:
    """Information about a tracked resource.
    
    Attributes:
        resource_type: Type of the resource.
        resource: The actual resource object.
        task_id: Associated task ID (if any).
        created_at: Creation timestamp.
        last_used_at: Last usage timestamp.
    """
    resource_type: ResourceType
    resource: Any
    task_id: str | None = None
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Update last used timestamp."""
        self.last_used_at = time.time()


class ProcessLifecycleManager:
    """Manages lifecycle of browser and LLM processes.
    
    Provides centralized cleanup for:
    - Browser instances (Playwright browsers and contexts)
    - Ollama sessions and model context
    - HTTP sessions
    - Tor controller connections
    
    Per §4.2 requirements:
    - Resources are tracked per task
    - Automatic cleanup on task completion
    - Prevention of memory leaks
    """

    def __init__(self):
        """Initialize lifecycle manager."""
        self._resources: dict[str, ResourceInfo] = {}
        self._task_resources: dict[str, set[str]] = {}  # task_id -> resource_ids
        self._cleanup_callbacks: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._settings = get_settings()
        self._lock = asyncio.Lock()
        self._closed = False

    async def register_resource(
        self,
        resource_id: str,
        resource_type: ResourceType,
        resource: Any,
        task_id: str | None = None,
    ) -> None:
        """Register a resource for lifecycle management.
        
        Args:
            resource_id: Unique identifier for the resource.
            resource_type: Type of the resource.
            resource: The actual resource object.
            task_id: Associated task ID for task-scoped cleanup.
        """
        async with self._lock:
            self._resources[resource_id] = ResourceInfo(
                resource_type=resource_type,
                resource=resource,
                task_id=task_id,
            )

            if task_id:
                if task_id not in self._task_resources:
                    self._task_resources[task_id] = set()
                self._task_resources[task_id].add(resource_id)

            logger.debug(
                "Registered resource",
                resource_id=resource_id,
                resource_type=resource_type.value,
                task_id=task_id,
            )

    async def unregister_resource(self, resource_id: str) -> None:
        """Unregister a resource without cleanup.
        
        Args:
            resource_id: Resource identifier.
        """
        async with self._lock:
            if resource_id in self._resources:
                info = self._resources.pop(resource_id)

                # Remove from task resources
                if info.task_id and info.task_id in self._task_resources:
                    self._task_resources[info.task_id].discard(resource_id)

                logger.debug(
                    "Unregistered resource",
                    resource_id=resource_id,
                    resource_type=info.resource_type.value,
                )

    async def cleanup_resource(self, resource_id: str) -> bool:
        """Cleanup and unregister a specific resource.
        
        Args:
            resource_id: Resource identifier.
            
        Returns:
            True if cleanup was successful.
        """
        async with self._lock:
            if resource_id not in self._resources:
                return False

            info = self._resources[resource_id]

        success = await self._cleanup_single_resource(info)

        async with self._lock:
            if resource_id in self._resources:
                self._resources.pop(resource_id)

                # Remove from task resources
                if info.task_id and info.task_id in self._task_resources:
                    self._task_resources[info.task_id].discard(resource_id)

        return success

    async def cleanup_task_resources(self, task_id: str) -> dict[str, bool]:
        """Cleanup all resources associated with a task.
        
        Per §4.2: Browser instances and LLM processes are destroyed
        after task completion to prevent memory leaks.
        
        Args:
            task_id: Task identifier.
            
        Returns:
            Dict mapping resource_id to cleanup success status.
        """
        async with self._lock:
            resource_ids = self._task_resources.get(task_id, set()).copy()

        if not resource_ids:
            logger.debug("No resources to cleanup for task", task_id=task_id)
            return {}

        logger.info(
            "Cleaning up task resources",
            task_id=task_id,
            resource_count=len(resource_ids),
        )

        results = {}
        for resource_id in resource_ids:
            results[resource_id] = await self.cleanup_resource(resource_id)

        async with self._lock:
            # Remove task tracking
            self._task_resources.pop(task_id, None)

        success_count = sum(1 for v in results.values() if v)
        logger.info(
            "Task resource cleanup complete",
            task_id=task_id,
            success_count=success_count,
            total_count=len(results),
        )

        return results

    async def cleanup_all(self) -> dict[str, bool]:
        """Cleanup all registered resources.
        
        Returns:
            Dict mapping resource_id to cleanup success status.
        """
        async with self._lock:
            resource_ids = list(self._resources.keys())

        logger.info("Cleaning up all resources", resource_count=len(resource_ids))

        results = {}
        for resource_id in resource_ids:
            results[resource_id] = await self.cleanup_resource(resource_id)

        # Run additional cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                await callback()
            except Exception as e:
                logger.warning("Cleanup callback failed", error=str(e))

        self._closed = True

        return results

    async def cleanup_stale_resources(
        self,
        max_age_seconds: float = 3600,
        max_idle_seconds: float = 600,
    ) -> dict[str, bool]:
        """Cleanup resources that are too old or have been idle too long.
        
        Args:
            max_age_seconds: Maximum age in seconds (default: 1 hour).
            max_idle_seconds: Maximum idle time in seconds (default: 10 minutes).
            
        Returns:
            Dict mapping resource_id to cleanup success status.
        """
        now = time.time()
        stale_ids = []

        async with self._lock:
            for resource_id, info in self._resources.items():
                age = now - info.created_at
                idle = now - info.last_used_at

                if age > max_age_seconds or idle > max_idle_seconds:
                    stale_ids.append(resource_id)

        if not stale_ids:
            return {}

        logger.info("Cleaning up stale resources", count=len(stale_ids))

        results = {}
        for resource_id in stale_ids:
            results[resource_id] = await self.cleanup_resource(resource_id)

        return results

    def register_cleanup_callback(
        self,
        callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an additional cleanup callback.
        
        Callbacks are run during cleanup_all().
        
        Args:
            callback: Async function to call during cleanup.
        """
        self._cleanup_callbacks.append(callback)

    def touch_resource(self, resource_id: str) -> None:
        """Update last used timestamp for a resource.
        
        Args:
            resource_id: Resource identifier.
        """
        if resource_id in self._resources:
            self._resources[resource_id].touch()

    def get_resource_count(
        self,
        resource_type: ResourceType | None = None,
        task_id: str | None = None,
    ) -> int:
        """Get count of registered resources.
        
        Args:
            resource_type: Filter by resource type.
            task_id: Filter by task ID.
            
        Returns:
            Number of matching resources.
        """
        count = 0
        for info in self._resources.values():
            if resource_type and info.resource_type != resource_type:
                continue
            if task_id and info.task_id != task_id:
                continue
            count += 1
        return count

    async def _cleanup_single_resource(self, info: ResourceInfo) -> bool:
        """Cleanup a single resource based on its type.
        
        Args:
            info: Resource information.
            
        Returns:
            True if cleanup was successful.
        """
        try:
            resource = info.resource
            resource_type = info.resource_type

            if resource_type == ResourceType.BROWSER:
                await self._cleanup_browser(resource)
            elif resource_type == ResourceType.BROWSER_CONTEXT:
                await self._cleanup_browser_context(resource)
            elif resource_type == ResourceType.PLAYWRIGHT:
                await self._cleanup_playwright(resource)
            elif resource_type == ResourceType.OLLAMA_SESSION:
                await self._cleanup_ollama_session(resource)
            elif resource_type == ResourceType.HTTP_SESSION:
                await self._cleanup_http_session(resource)
            elif resource_type == ResourceType.TOR_CONTROLLER:
                await self._cleanup_tor_controller(resource)
            else:
                logger.warning(
                    "Unknown resource type",
                    resource_type=resource_type.value,
                )
                return False

            logger.debug(
                "Cleaned up resource",
                resource_type=resource_type.value,
                task_id=info.task_id,
            )
            return True

        except Exception as e:
            logger.error(
                "Resource cleanup failed",
                resource_type=info.resource_type.value,
                error=str(e),
            )
            return False

    async def _cleanup_browser(self, browser) -> None:
        """Cleanup Playwright browser instance.
        
        Args:
            browser: Playwright browser object.
        """
        try:
            await browser.close()
        except Exception as e:
            logger.debug("Browser close error (may be expected)", error=str(e))

    async def _cleanup_browser_context(self, context) -> None:
        """Cleanup Playwright browser context.
        
        Args:
            context: Playwright context object.
        """
        try:
            await context.close()
        except Exception as e:
            logger.debug("Context close error (may be expected)", error=str(e))

    async def _cleanup_playwright(self, playwright) -> None:
        """Cleanup Playwright instance.
        
        Args:
            playwright: Playwright instance.
        """
        try:
            await playwright.stop()
        except Exception as e:
            logger.debug("Playwright stop error (may be expected)", error=str(e))

    async def _cleanup_ollama_session(self, session_info: dict) -> None:
        """Cleanup Ollama session and release model context.
        
        Per §4.2: LLM process context should be released after task completion.
        
        Args:
            session_info: Dict with 'session' and optionally 'model' keys.
        """
        session = session_info.get("session")
        model = session_info.get("model")
        host = session_info.get("host", self._settings.llm.ollama_host)

        # Close HTTP session
        if session and not session.closed:
            try:
                await session.close()
            except Exception as e:
                logger.debug("Session close error", error=str(e))

        # Unload model to free VRAM (optional, based on settings)
        if model and self._settings.llm.unload_on_task_complete:
            await self._unload_ollama_model(host, model)

    async def _unload_ollama_model(self, host: str, model: str) -> None:
        """Unload Ollama model to free VRAM.
        
        Args:
            host: Ollama host URL.
            model: Model name to unload.
        """
        try:
            async with aiohttp.ClientSession() as session:
                # Ollama API: POST /api/generate with keep_alive=0 unloads the model
                url = f"{host}/api/generate"
                payload = {
                    "model": model,
                    "prompt": "",
                    "keep_alive": 0,  # Unload immediately
                }

                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        logger.info(
                            "Ollama model unloaded",
                            model=model,
                        )
                    else:
                        logger.debug(
                            "Ollama model unload request returned non-200",
                            model=model,
                            status=response.status,
                        )

        except Exception as e:
            logger.debug(
                "Ollama model unload failed (may be expected)",
                model=model,
                error=str(e),
            )

    async def _cleanup_http_session(self, session: aiohttp.ClientSession) -> None:
        """Cleanup aiohttp session.
        
        Args:
            session: aiohttp ClientSession.
        """
        if not session.closed:
            try:
                await session.close()
            except Exception as e:
                logger.debug("HTTP session close error", error=str(e))

    async def _cleanup_tor_controller(self, controller) -> None:
        """Cleanup Tor controller connection.
        
        Args:
            controller: Tor controller object.
        """
        try:
            controller.close()
        except Exception as e:
            logger.debug("Tor controller close error", error=str(e))


# Global lifecycle manager instance
_lifecycle_manager: ProcessLifecycleManager | None = None


def get_lifecycle_manager() -> ProcessLifecycleManager:
    """Get or create the global lifecycle manager.
    
    Returns:
        ProcessLifecycleManager instance.
    """
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = ProcessLifecycleManager()
    return _lifecycle_manager


async def cleanup_task(task_id: str) -> dict[str, bool]:
    """Cleanup all resources for a completed task.
    
    Convenience function for task completion cleanup.
    
    Args:
        task_id: Task identifier.
        
    Returns:
        Dict mapping resource_id to cleanup success status.
    """
    manager = get_lifecycle_manager()
    return await manager.cleanup_task_resources(task_id)


async def cleanup_all_resources() -> dict[str, bool]:
    """Cleanup all registered resources.
    
    Convenience function for shutdown cleanup.
    
    Returns:
        Dict mapping resource_id to cleanup success status.
    """
    manager = get_lifecycle_manager()
    return await manager.cleanup_all()


async def register_browser_for_task(
    task_id: str,
    browser,
    context=None,
    playwright=None,
) -> list[str]:
    """Register browser resources for task-scoped lifecycle management.
    
    Args:
        task_id: Task identifier.
        browser: Playwright browser object.
        context: Playwright browser context (optional).
        playwright: Playwright instance (optional).
        
    Returns:
        List of registered resource IDs.
    """
    manager = get_lifecycle_manager()
    resource_ids = []

    # Register browser
    browser_id = f"browser_{task_id}_{id(browser)}"
    await manager.register_resource(
        browser_id,
        ResourceType.BROWSER,
        browser,
        task_id,
    )
    resource_ids.append(browser_id)

    # Register context if provided
    if context:
        context_id = f"context_{task_id}_{id(context)}"
        await manager.register_resource(
            context_id,
            ResourceType.BROWSER_CONTEXT,
            context,
            task_id,
        )
        resource_ids.append(context_id)

    # Register playwright if provided
    if playwright:
        playwright_id = f"playwright_{task_id}_{id(playwright)}"
        await manager.register_resource(
            playwright_id,
            ResourceType.PLAYWRIGHT,
            playwright,
            task_id,
        )
        resource_ids.append(playwright_id)

    return resource_ids


async def register_ollama_session_for_task(
    task_id: str,
    session: aiohttp.ClientSession,
    model: str | None = None,
) -> str:
    """Register Ollama session for task-scoped lifecycle management.
    
    Args:
        task_id: Task identifier.
        session: aiohttp ClientSession for Ollama.
        model: Currently loaded model name (optional).
        
    Returns:
        Registered resource ID.
    """
    manager = get_lifecycle_manager()
    settings = get_settings()

    resource_id = f"ollama_{task_id}_{id(session)}"
    await manager.register_resource(
        resource_id,
        ResourceType.OLLAMA_SESSION,
        {
            "session": session,
            "model": model,
            "host": settings.llm.ollama_host,
        },
        task_id,
    )

    return resource_id





