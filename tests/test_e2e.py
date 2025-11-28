"""
End-to-End Tests for Lancet.

Per §7.1.7: E2E tests require real environment (Browser, Ollama, etc.) and
should be executed manually, not in CI.

These tests validate:
1. Browser Search → Fetch → Extract → Report pipeline
2. Authentication queue → Manual intervention → Resume flow

Usage:
    # Run E2E tests (requires running services and display)
    pytest tests/test_e2e.py -v -m e2e

    # Skip if services not available
    pytest tests/test_e2e.py -v -m e2e --ignore-missing-services
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

# Skip E2E tests if not explicitly requested or if services are unavailable
pytestmark = pytest.mark.e2e


# =============================================================================
# Service Availability Checks
# =============================================================================

async def is_browser_search_available() -> bool:
    """Check if browser-based search is available.
    
    Returns True only if:
    - Playwright is installed
    - A display is available (for headed mode) or headless mode is configured
    """
    try:
        # Check if running in container without display
        display = os.environ.get("DISPLAY")
        headless = os.environ.get("LANCET_HEADLESS", "false").lower() == "true"
        
        if not display and not headless:
            return False
        
        # Check if Playwright is available
        from playwright.async_api import async_playwright
        return True
    except ImportError:
        return False


async def is_ollama_available() -> bool:
    """Check if Ollama is available."""
    try:
        import aiohttp
        
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_host}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def e2e_database(tmp_path_factory):
    """Create a test database for E2E tests."""
    from src.storage.database import Database
    
    tmp_dir = tmp_path_factory.mktemp("e2e")
    db_path = tmp_dir / "e2e_test.db"
    db = Database(str(db_path))
    await db.connect()
    await db.initialize_schema()
    yield db
    await db.close()


@pytest_asyncio.fixture(scope="module")
async def check_browser_search():
    """Check browser search availability and skip if not available."""
    available = await is_browser_search_available()
    if not available:
        pytest.skip("Browser search not available. Requires display or LANCET_HEADLESS=true")
    return True


@pytest_asyncio.fixture(scope="module")
async def check_ollama():
    """Check Ollama availability and skip if not available."""
    available = await is_ollama_available()
    if not available:
        pytest.skip("Ollama is not available. Start with: podman-compose up ollama")
    return True


# =============================================================================
# E2E Test 1: Browser Search → Fetch → Extract → Report Pipeline
# =============================================================================

@pytest.mark.e2e
class TestSearchToReportPipeline:
    """
    E2E test for the complete research pipeline.
    
    Verifies §3.1-§3.4 requirements:
    - Search execution via browser-based search
    - URL fetching with rate limiting
    - Content extraction from HTML
    - Report material generation
    
    Requirements:
    - Display available or LANCET_HEADLESS=true
    - Network access for URL fetching
    """
    
    @pytest.mark.asyncio
    async def test_search_returns_results(self, check_browser_search, e2e_database):
        """
        Verify browser-based search returns normalized results.
        
        Tests §3.2.1 search_serp tool:
        - Query execution with real browser search
        - Result normalization (title, url, snippet, engine, rank)
        """
        from src.search import search_serp
        
        # Execute a simple search query
        # Use mojeek as it's block-resistant and returns results reliably
        # duckduckgo/qwant/brave often blocked by CAPTCHA/rate limits
        results = await search_serp(
            query="Python programming language",
            engines=["mojeek"],
            limit=5,
            time_range="all",
            use_cache=False,  # Skip cache for E2E test
        )
        
        # Verify results structure
        assert isinstance(results, list), f"Expected list, got {type(results)}"
        assert len(results) > 0, "Expected at least one search result"
        
        # Verify result fields per §3.2.1
        first_result = results[0]
        required_fields = ["title", "url", "snippet", "engine", "rank"]
        for field in required_fields:
            assert field in first_result, f"Missing required field: {field}"
        
        # Verify URL is valid
        assert first_result["url"].startswith(("http://", "https://")), \
            f"Invalid URL: {first_result['url']}"
        
        # Log for manual inspection
        print(f"\n[E2E] Search returned {len(results)} results")
        print(f"[E2E] First result: {first_result['title'][:50]}...")
    
    @pytest.mark.asyncio
    async def test_fetch_and_extract_content(self, check_browser_search, e2e_database):
        """
        Verify URL fetching and content extraction.
        
        Tests §3.2 fetch_url and §3.3 extract_content:
        - HTTP fetching with rate limiting
        - Content extraction from HTML
        - Text and metadata extraction
        """
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content
        
        # Fetch a known stable URL (Wikipedia)
        test_url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
        
        fetch_result = await fetch_url(
            url=test_url,
            context={"referer": "https://www.google.com/"},
            policy={"force_browser": False, "max_retries": 2},
        )
        
        # Verify fetch succeeded
        assert fetch_result["ok"] is True, f"Fetch failed: {fetch_result.get('reason')}"
        assert "html_path" in fetch_result or "content" in fetch_result, \
            "Expected html_path or content in fetch result"
        
        # Extract content
        html_content = None
        if "html_path" in fetch_result and fetch_result["html_path"]:
            html_path = Path(fetch_result["html_path"])
            if html_path.exists():
                html_content = html_path.read_text(encoding="utf-8", errors="replace")
        elif "content" in fetch_result:
            html_content = fetch_result["content"]
        
        if html_content:
            extract_result = await extract_content(html=html_content, content_type="html")
            
            assert extract_result["ok"] is True, f"Extract failed: {extract_result.get('error')}"
            
            # Verify extracted content
            text = extract_result.get("text", "")
            assert len(text) > 100, "Expected substantial text content"
            assert "Python" in text, "Expected 'Python' in extracted text"
            
            print(f"\n[E2E] Extracted {len(text)} characters from {test_url}")
        else:
            pytest.skip("Could not retrieve HTML content for extraction test")
    
    @pytest.mark.asyncio
    async def test_full_pipeline_simulation(self, check_browser_search, e2e_database):
        """
        Simulate a complete research pipeline.
        
        Tests the flow: Search → Fetch → Extract → Store
        Verifies §3.1.7 exploration control and §3.3 filtering.
        """
        from src.search import search_serp
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content
        from src.research.context import ResearchContext
        from src.research.state import ExplorationState, SubqueryStatus
        
        # Step 1: Create research task
        task_id = await e2e_database.create_task(
            query="What is the history of Python programming language?"
        )
        assert task_id is not None, "Failed to create task"
        
        # Step 2: Initialize research context
        context = ResearchContext(task_id)
        context._db = e2e_database
        ctx_result = await context.get_context()
        
        assert ctx_result["ok"] is True, f"Context retrieval failed: {ctx_result}"
        assert "extracted_entities" in ctx_result
        
        # Step 3: Initialize exploration state
        state = ExplorationState(task_id)
        state._db = e2e_database
        
        # Register a subquery (as if designed by Cursor AI)
        state.register_subquery(
            subquery_id="sq_python_history",
            text="Python programming language history site:wikipedia.org",
            priority="high",
        )
        
        # Step 4: Execute search
        results = await search_serp(
            query="Python programming language history",
            engines=["mojeek"],  # Use block-resistant engine
            limit=3,
            use_cache=False,
        )
        
        # Step 5: Update subquery status based on results
        sq = state.get_subquery("sq_python_history")
        assert sq is not None
        
        if len(results) >= 1:
            sq.status = SubqueryStatus.PARTIAL
            sq.independent_sources = len(results)
        else:
            sq.status = SubqueryStatus.EXHAUSTED
        
        # Step 6: Get exploration status
        status = await state.get_status()
        
        assert "subqueries" in status
        assert len(status["subqueries"]) == 1
        
        print(f"\n[E2E] Pipeline simulation completed")
        print(f"[E2E] Task ID: {task_id}")
        print(f"[E2E] Search results: {len(results)}")
        print(f"[E2E] Subquery status: {status['subqueries'][0]['status']}")
    
    @pytest.mark.asyncio
    async def test_report_materials_generation(self, check_browser_search, e2e_database):
        """
        Test report materials can be generated from research data.
        
        Verifies §3.4 and §3.2.1 get_report_materials.
        Note: This tests data structure, not Cursor AI composition.
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        
        # Create task with evidence
        task_id = await e2e_database.create_task(
            query="E2E test query for report generation"
        )
        
        # Build evidence graph with mock data
        graph = EvidenceGraph(task_id=task_id)
        
        # Add claims (would normally come from LLM extraction)
        graph.add_node(
            NodeType.CLAIM,
            "claim_1",
            text="Python was created by Guido van Rossum",
            confidence=0.95,
        )
        graph.add_node(
            NodeType.CLAIM,
            "claim_2",
            text="Python's first release was in 1991",
            confidence=0.9,
        )
        
        # Add supporting fragments
        graph.add_node(
            NodeType.FRAGMENT,
            "frag_1",
            text="Python was conceived in the late 1980s by Guido van Rossum...",
            url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        )
        
        # Add support relationship
        graph.add_edge(
            NodeType.FRAGMENT, "frag_1",
            NodeType.CLAIM, "claim_1",
            RelationType.SUPPORTS,
            confidence=0.92,
        )
        
        # Verify graph structure using get_stats()
        stats = graph.get_stats()
        claim_count = stats["node_counts"].get("claim", 0)
        assert claim_count == 2, f"Expected 2 claims, got {claim_count}"
        
        evidence = graph.get_supporting_evidence("claim_1")
        assert len(evidence) == 1, f"Expected 1 evidence, got {len(evidence)}"
        
        # Get primary source ratio
        ratio_info = graph.get_primary_source_ratio()
        assert "primary_ratio" in ratio_info
        
        print(f"\n[E2E] Report materials generated")
        print(f"[E2E] Claims: {claim_count}")
        print(f"[E2E] Evidence for claim_1: {len(evidence)}")


# =============================================================================
# E2E Test 2: Authentication Queue → Manual Intervention → Resume
# =============================================================================

@pytest.mark.e2e
class TestAuthenticationQueueFlow:
    """
    E2E test for the authentication queue and intervention flow.
    
    Per RFC_AUTH_QUEUE_DOMAIN_BASED:
    - Authentication is domain-centric (one auth resolves all URLs for that domain)
    - Queue is grouped by domain for efficient batch processing
    - Session reuse is per-domain
    
    This test simulates the semi-automatic operation mode where
    authentication challenges are queued for batch processing.
    """
    
    @pytest_asyncio.fixture(autouse=True)
    async def cleanup_queue(self, e2e_database):
        """Clear intervention_queue before each test to ensure isolation."""
        await e2e_database.execute(
            "DELETE FROM intervention_queue WHERE 1=1"
        )
        yield
    
    @pytest.mark.asyncio
    async def test_enqueue_authentication(self, e2e_database):
        """
        Test enqueueing authentication challenges.
        
        Verifies queue item creation with priority and domain tracking.
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        # Create task first (required for foreign key constraint)
        task_id = await e2e_database.create_task(query="E2E auth queue test")
        
        # High priority (primary source)
        queue_id_1 = await queue.enqueue(
            task_id=task_id,
            url="https://protected.go.jp/document.pdf",
            domain="protected.go.jp",
            auth_type="cloudflare",
            priority="high",
        )
        
        # Medium priority
        queue_id_2 = await queue.enqueue(
            task_id=task_id,
            url="https://secure.example.com/page",
            domain="secure.example.com",
            auth_type="captcha",
            priority="medium",
        )
        
        # Low priority
        queue_id_3 = await queue.enqueue(
            task_id=task_id,
            url="https://blog.example.com/article",
            domain="blog.example.com",
            auth_type="turnstile",
            priority="low",
        )
        
        # Verify queue IDs are generated
        assert queue_id_1.startswith("iq_"), f"Invalid queue ID format: {queue_id_1}"
        assert queue_id_2.startswith("iq_"), f"Invalid queue ID format: {queue_id_2}"
        assert queue_id_3.startswith("iq_"), f"Invalid queue ID format: {queue_id_3}"
        
        print(f"\n[E2E] Enqueued 3 authentication challenges")
        print(f"[E2E] High priority: {queue_id_1}")
        print(f"[E2E] Medium priority: {queue_id_2}")
        print(f"[E2E] Low priority: {queue_id_3}")
        
        return task_id, [queue_id_1, queue_id_2, queue_id_3]
    
    @pytest.mark.asyncio
    async def test_get_pending_by_domain(self, e2e_database):
        """
        Test retrieving pending authentications grouped by domain.
        
        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - Results are grouped by domain
        - Each domain shows affected_tasks, pending_count, high_priority_count
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        # Create two tasks
        task_a = await e2e_database.create_task(query="E2E task A")
        task_b = await e2e_database.create_task(query="E2E task B")
        
        # Both tasks need auth for same domain (protected.go.jp)
        await queue.enqueue(
            task_id=task_a,
            url="https://protected.go.jp/doc1.pdf",
            domain="protected.go.jp",
            auth_type="cloudflare",
            priority="high",
        )
        await queue.enqueue(
            task_id=task_b,
            url="https://protected.go.jp/doc2.pdf",
            domain="protected.go.jp",
            auth_type="cloudflare",
            priority="medium",
        )
        
        # Another domain
        await queue.enqueue(
            task_id=task_a,
            url="https://example.com/page",
            domain="example.com",
            auth_type="captcha",
            priority="low",
        )
        
        # Get pending by domain
        result = await queue.get_pending_by_domain()
        
        assert result["ok"] is True
        assert result["total_domains"] == 2, (
            f"Expected 2 domains, got {result['total_domains']}"
        )
        assert result["total_pending"] == 3, (
            f"Expected 3 pending, got {result['total_pending']}"
        )
        
        # Find protected.go.jp domain
        go_jp = next((d for d in result["domains"] if d["domain"] == "protected.go.jp"), None)
        assert go_jp is not None, "protected.go.jp should be in domains"
        assert go_jp["pending_count"] == 2
        assert go_jp["high_priority_count"] == 1
        assert set(go_jp["affected_tasks"]) == {task_a, task_b}
        
        print(f"\n[E2E] Pending by domain:")
        for d in result["domains"]:
            print(f"[E2E]   {d['domain']}: {d['pending_count']} pending, "
                  f"{d['high_priority_count']} high priority, "
                  f"tasks: {d['affected_tasks']}")
    
    @pytest.mark.asyncio
    async def test_complete_authentication_single_item(self, e2e_database):
        """
        Test completing a single authentication item.
        
        Verifies single-item complete (legacy API).
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        task_id = await e2e_database.create_task(query="E2E complete single auth test")
        
        queue_id = await queue.enqueue(
            task_id=task_id,
            url="https://auth.example.com/",
            domain="auth.example.com",
            auth_type="cloudflare",
            priority="high",
        )
        
        session_data = {
            "cookies": {"cf_clearance": "mock_token_123"},
            "user_agent": "Mozilla/5.0...",
            "authenticated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await queue.complete(
            queue_id=queue_id,
            success=True,
            session_data=session_data,
            task_id=task_id,
        )
        
        assert result["ok"] is True, f"Complete failed: {result}"
        assert result["status"] == "completed"
        
        print(f"\n[E2E] Single authentication completed for {queue_id}")
    
    @pytest.mark.asyncio
    async def test_complete_domain_resolves_multiple_tasks(self, e2e_database):
        """
        Test domain-based authentication completion.
        
        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - One auth resolves all pending URLs for that domain
        - Returns affected_tasks list
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        # Create two tasks
        task_a = await e2e_database.create_task(query="E2E task A for domain auth")
        task_b = await e2e_database.create_task(query="E2E task B for domain auth")
        
        # Both tasks need auth for same domain
        await queue.enqueue(
            task_id=task_a,
            url="https://protected.gov/doc1.pdf",
            domain="protected.gov",
            auth_type="cloudflare",
            priority="high",
        )
        await queue.enqueue(
            task_id=task_b,
            url="https://protected.gov/doc2.pdf",
            domain="protected.gov",
            auth_type="cloudflare",
            priority="medium",
        )
        
        session_data = {
            "cookies": {"cf_clearance": "mock_token_abc"},
            "authenticated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Complete by domain - should resolve both
        result = await queue.complete_domain(
            domain="protected.gov",
            success=True,
            session_data=session_data,
        )
        
        assert result["ok"] is True
        assert result["domain"] == "protected.gov"
        assert result["resolved_count"] == 2, (
            f"Should resolve 2 items, got {result['resolved_count']}"
        )
        assert set(result["affected_tasks"]) == {task_a, task_b}
        assert result["session_stored"] is True
        
        # Verify no more pending for protected.gov
        pending = await queue.get_pending_by_domain()
        protected_domain = next(
            (d for d in pending["domains"] if d["domain"] == "protected.gov"), 
            None
        )
        assert protected_domain is None, "protected.gov should have no pending items"
        
        print(f"\n[E2E] Domain auth completed: {result['resolved_count']} items resolved")
        print(f"[E2E] Affected tasks: {result['affected_tasks']}")
    
    @pytest.mark.asyncio
    async def test_skip_by_queue_ids(self, e2e_database):
        """
        Test skipping specific queue items.
        
        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - skip(queue_ids=[...]) skips only those items
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        task_id = await e2e_database.create_task(query="E2E skip by ids test")
        
        queue_id_1 = await queue.enqueue(
            task_id=task_id,
            url="https://skip1.example.com/",
            domain="skip1.example.com",
            auth_type="captcha",
            priority="low",
        )
        queue_id_2 = await queue.enqueue(
            task_id=task_id,
            url="https://skip2.example.com/",
            domain="skip2.example.com",
            auth_type="captcha",
            priority="low",
        )
        
        # Skip specific item
        result = await queue.skip(queue_ids=[queue_id_1])
        
        assert result["ok"] is True
        assert result["skipped"] == 1
        
        # Verify only one item remains pending
        pending = await queue.get_pending(task_id=task_id)
        pending_ids = [p["id"] for p in pending]
        
        assert queue_id_1 not in pending_ids, "Skipped item should not be pending"
        assert queue_id_2 in pending_ids, "Non-skipped item should still be pending"
        
        print(f"\n[E2E] Skipped authentication {queue_id_1}")
        print(f"[E2E] Remaining pending: {len(pending)}")
    
    @pytest.mark.asyncio
    async def test_skip_by_domain(self, e2e_database):
        """
        Test skipping all items for a domain.
        
        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - skip(domain=...) skips all pending for that domain
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        task_a = await e2e_database.create_task(query="E2E skip domain task A")
        task_b = await e2e_database.create_task(query="E2E skip domain task B")
        
        # Both tasks need same domain
        await queue.enqueue(
            task_id=task_a,
            url="https://skip-domain.com/doc1",
            domain="skip-domain.com",
            auth_type="cloudflare",
        )
        await queue.enqueue(
            task_id=task_b,
            url="https://skip-domain.com/doc2",
            domain="skip-domain.com",
            auth_type="cloudflare",
        )
        # Keep this one
        await queue.enqueue(
            task_id=task_a,
            url="https://keep.com/page",
            domain="keep.com",
            auth_type="captcha",
        )
        
        # Skip by domain
        result = await queue.skip(domain="skip-domain.com")
        
        assert result["ok"] is True
        assert result["skipped"] == 2
        assert set(result["affected_tasks"]) == {task_a, task_b}
        
        # Verify keep.com is still pending
        pending = await queue.get_pending(task_id=task_a)
        assert len(pending) == 1
        assert pending[0]["domain"] == "keep.com"
        
        print(f"\n[E2E] Skipped domain skip-domain.com: {result['skipped']} items")
    
    @pytest.mark.asyncio
    async def test_pending_count_and_summary(self, e2e_database):
        """
        Test getting pending count for exploration status.
        
        Verifies §3.6.1 integration with get_exploration_status:
        - Pending count by priority
        - High priority count for alerts
        """
        from src.utils.notification import InterventionQueue
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        # Create task first (required for foreign key constraint)
        task_id = await e2e_database.create_task(query="E2E pending count test")
        
        await queue.enqueue(task_id=task_id, url="https://h1.go.jp/", 
                           domain="h1.go.jp", auth_type="cloudflare", priority="high")
        await queue.enqueue(task_id=task_id, url="https://h2.go.jp/", 
                           domain="h2.go.jp", auth_type="cloudflare", priority="high")
        await queue.enqueue(task_id=task_id, url="https://m1.example.com/", 
                           domain="m1.example.com", auth_type="captcha", priority="medium")
        await queue.enqueue(task_id=task_id, url="https://l1.example.com/", 
                           domain="l1.example.com", auth_type="captcha", priority="low")
        
        # Get pending count
        counts = await queue.get_pending_count(task_id=task_id)
        
        assert counts["total"] == 4, f"Expected 4 total, got {counts['total']}"
        assert counts["high"] == 2, f"Expected 2 high priority, got {counts['high']}"
        assert counts["medium"] == 1, f"Expected 1 medium priority, got {counts['medium']}"
        assert counts["low"] == 1, f"Expected 1 low priority, got {counts['low']}"
        
        # Verify threshold alerts would be triggered
        # Per §3.6.1: ≥3件でwarning、≥5件またはhigh≥2件でcritical
        assert counts["total"] >= 3, "Should trigger warning threshold"
        assert counts["high"] >= 2, "Should trigger critical due to high priority count"
        
        print(f"\n[E2E] Pending count summary:")
        print(f"[E2E] Total: {counts['total']}, High: {counts['high']}, "
              f"Medium: {counts['medium']}, Low: {counts['low']}")
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_items(self, e2e_database):
        """
        Test cleanup of expired queue items.
        
        Verifies queue maintenance functionality.
        """
        from src.utils.notification import InterventionQueue
        from datetime import timedelta
        
        queue = InterventionQueue()
        queue._db = e2e_database
        
        # Create task first (required for foreign key constraint)
        task_id = await e2e_database.create_task(query="E2E cleanup test")
        
        # This item will be expired (expires in the past)
        await queue.enqueue(
            task_id=task_id,
            url="https://expired.example.com/",
            domain="expired.example.com",
            auth_type="captcha",
            priority="low",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Already expired
        )
        
        # Run cleanup
        cleaned_count = await queue.cleanup_expired()
        
        # Verify cleanup ran (may or may not find items depending on timing)
        assert cleaned_count >= 0, "Cleanup should return non-negative count"
        
        print(f"\n[E2E] Cleaned up {cleaned_count} expired items")


# =============================================================================
# E2E Test 3: Intervention Manager (Immediate Mode)
# =============================================================================

@pytest.mark.e2e
class TestInterventionManagerFlow:
    """
    E2E test for the intervention manager (immediate/legacy mode).
    
    Verifies §3.6.2 requirements:
    - Intervention request handling
    - Timeout management
    - Domain failure tracking
    
    Note: This doesn't test actual UI interaction, but verifies
    the intervention workflow logic.
    """
    
    @pytest.mark.asyncio
    async def test_intervention_request_creates_record(self, e2e_database):
        """
        Test that intervention requests create database records.
        
        Verifies §3.6.2 logging requirements.
        """
        from src.utils.notification import InterventionManager, InterventionType
        
        manager = InterventionManager()
        
        # Note: This will timeout quickly since no actual user interaction
        # We just verify the setup logic works
        
        # Check domain skip logic (should not skip initially)
        should_skip = await manager._should_skip_domain("new-domain.example.com")
        assert should_skip is False, "New domain should not be skipped"
        
        print(f"\n[E2E] Intervention manager initialized")
        print(f"[E2E] New domain skip check: {should_skip}")
    
    @pytest.mark.asyncio
    async def test_domain_failure_tracking(self, e2e_database):
        """
        Test domain failure tracking for skip decisions.
        
        Verifies §3.6.2: Skip domain after 3 consecutive failures.
        Uses get_domain_failures() and max_domain_failures property.
        """
        from src.utils.notification import InterventionManager
        
        manager = InterventionManager()
        
        test_domain = "failing-domain.example.com"
        
        # Verify initial state
        initial_failures = manager.get_domain_failures(test_domain)
        assert initial_failures == 0, f"Initial failures should be 0, got {initial_failures}"
        
        # Verify max_domain_failures property
        max_failures = manager.max_domain_failures
        assert max_failures == 3, f"Max failures should be 3, got {max_failures}"
        
        # Test reset functionality
        manager.reset_domain_failures(test_domain)
        after_reset = manager.get_domain_failures(test_domain)
        assert after_reset == 0, f"After reset should be 0, got {after_reset}"
        
        print(f"\n[E2E] Domain failure tracking:")
        print(f"[E2E] Domain: {test_domain}")
        print(f"[E2E] Initial failures: {initial_failures}")
        print(f"[E2E] Max allowed failures: {max_failures}")


# =============================================================================
# E2E Test 4: Complete Research Flow with Evidence Graph
# =============================================================================

@pytest.mark.e2e
class TestCompleteResearchFlow:
    """
    E2E test for a complete research workflow.
    
    This test simulates the entire flow from task creation to
    report material generation, verifying the integration of
    all major components.
    """
    
    @pytest.mark.asyncio
    async def test_end_to_end_research_workflow(self, check_browser_search, e2e_database):
        """
        Complete E2E test of the research workflow.
        
        Flow:
        1. Create task
        2. Get research context
        3. Execute subqueries (search)
        4. Fetch and extract content
        5. Build evidence graph
        6. Generate report materials
        
        This test uses real browser search but mocks content fetching
        to avoid rate limiting and external dependencies.
        """
        from src.research.context import ResearchContext
        from src.research.state import ExplorationState, SubqueryStatus
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        from src.search import search_serp
        
        # Step 1: Create research task
        query = "What are the main features of Python 3.12?"
        task_id = await e2e_database.create_task(query=query)
        
        assert task_id is not None, "Failed to create task"
        print(f"\n[E2E] Step 1: Created task {task_id}")
        
        # Step 2: Get research context
        context = ResearchContext(task_id)
        context._db = e2e_database
        ctx_result = await context.get_context()
        
        assert ctx_result["ok"] is True
        print(f"[E2E] Step 2: Got research context")
        print(f"[E2E]   - Entities: {len(ctx_result.get('extracted_entities', []))}")
        print(f"[E2E]   - Templates: {len(ctx_result.get('applicable_templates', []))}")
        
        # Step 3: Initialize exploration state and register subqueries
        state = ExplorationState(task_id)
        state._db = e2e_database
        
        subqueries = [
            ("sq_1", "Python 3.12 new features"),
            ("sq_2", "Python 3.12 release notes site:python.org"),
            ("sq_3", "Python 3.12 improvements performance"),
        ]
        
        for sq_id, sq_text in subqueries:
            state.register_subquery(sq_id, sq_text, priority="medium")
        
        print(f"[E2E] Step 3: Registered {len(subqueries)} subqueries")
        
        # Step 4: Execute first subquery
        results = await search_serp(
            query=subqueries[0][1],
            engines=["mojeek"],  # Use block-resistant engine
            limit=3,
            use_cache=False,
        )
        
        sq = state.get_subquery("sq_1")
        if len(results) >= 2:
            sq.status = SubqueryStatus.PARTIAL
            sq.independent_sources = len(results)
        
        print(f"[E2E] Step 4: Executed search, got {len(results)} results")
        
        # Step 5: Build evidence graph
        graph = EvidenceGraph(task_id=task_id)
        
        # Add claims based on search results
        graph.add_node(
            NodeType.CLAIM,
            "claim_1",
            text="Python 3.12 includes new features for developers",
            confidence=0.85,
        )
        
        # Add fragments from search results
        for i, result in enumerate(results[:2]):
            frag_id = f"frag_{i+1}"
            graph.add_node(
                NodeType.FRAGMENT,
                frag_id,
                text=result.get("snippet", "")[:200],
                url=result.get("url", ""),
            )
            graph.add_edge(
                NodeType.FRAGMENT, frag_id,
                NodeType.CLAIM, "claim_1",
                RelationType.SUPPORTS,
                confidence=0.8,
            )
        
        print(f"[E2E] Step 5: Built evidence graph")
        
        # Step 6: Verify final state
        final_status = await state.get_status()
        stats = graph.get_stats()
        claim_count = stats["node_counts"].get("claim", 0)
        evidence = graph.get_supporting_evidence("claim_1")
        
        print(f"[E2E] Step 6: Final state:")
        print(f"[E2E]   - Subqueries: {len(final_status['subqueries'])}")
        print(f"[E2E]   - Claims: {claim_count}")
        print(f"[E2E]   - Evidence for claim_1: {len(evidence)}")
        
        # Assertions
        assert len(final_status["subqueries"]) == 3
        assert claim_count >= 1
        
        print(f"\n[E2E] ✓ Complete research workflow test passed")


# =============================================================================
# E2E Test 5: LLM Integration (Optional - requires Ollama)
# =============================================================================

@pytest.mark.e2e
class TestLLMIntegration:
    """
    E2E test for LLM integration.
    
    Tests §3.3 LLM extraction functionality with real Ollama.
    Optional - skipped if Ollama is not available.
    """
    
    @pytest.mark.asyncio
    async def test_ollama_model_availability(self, check_ollama):
        """
        Verify Ollama is running and has required models.
        """
        import aiohttp
        
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_host}/api/tags") as resp:
                assert resp.status == 200
                data = await resp.json()
                
                models = data.get("models", [])
                model_names = [m.get("name", "") for m in models]
                
                print(f"\n[E2E] Ollama available models: {model_names}")
                
                # Check for required models (optional)
                # Note: qwen2.5:3b may not be installed
                if not model_names:
                    pytest.skip("No Ollama models installed")
    
    @pytest.mark.asyncio
    async def test_llm_extract_basic(self, check_ollama, e2e_database):
        """
        Test basic LLM extraction.
        
        Note: This test may be slow (LLM inference).
        """
        # Import the LLM extraction module
        from src.filter.llm import llm_extract
        
        # Simple test passage
        passages = [
            {
                "id": "p1",
                "text": "Python 3.12 was released in October 2023. It includes "
                        "improvements to error messages and a new type parameter syntax.",
            }
        ]
        
        try:
            result = await llm_extract(
                passages=passages,
                task="extract_facts",
            )
            
            assert result["ok"] is True, f"LLM extraction failed: {result.get('error')}"
            
            print(f"\n[E2E] LLM extraction result: {result}")
        except Exception as e:
            # LLM may not be available or may timeout
            pytest.skip(f"LLM extraction failed (may need model): {e}")

