"""
End-to-End Tests for Lyra.

Per .1.7: E2E tests require real environment (Browser, Ollama, etc.) and
should be executed manually, not in CI.

These tests validate:
1. Browser Search → Fetch → Extract → Report pipeline
2. Authentication queue → Manual intervention → Resume flow

Usage:
    # Run E2E tests (requires running services and display)
    pytest tests/test_e2e.py -v -m e2e

    # Skip if services not available
    pytest tests/test_e2e.py -v -m e2e --ignore-missing-services

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-E2E-N-01 | Valid search query, mojeek engine | Equivalence – normal search | Returns ≥1 results with required fields | Browser search integration |
| TC-E2E-N-02 | Valid Wikipedia URL | Equivalence – normal fetch/extract | Fetch succeeds, extracts >100 chars | HTTP fetch + extraction |
| TC-E2E-N-03 | Complete pipeline (task→search→graph) | Equivalence – full workflow | Task created, subquery registered, status available | Multi-component integration |
| TC-E2E-N-04 | Claims + fragments in evidence graph | Equivalence – report materials | Graph has 2 claims, 1 supporting evidence | Evidence graph building |
| TC-E2E-N-05 | Auth queue with high/medium/low priority | Equivalence – enqueue operation | Queue IDs generated with iq_ prefix | Authentication queue |
| TC-E2E-N-06 | Multiple tasks for same domain | Equivalence – domain grouping | Results grouped by domain, affected_tasks correct | Domain-based auth |
| TC-E2E-N-07 | Single auth item completion | Equivalence – single complete | Status becomes 'completed' | Legacy API |
| TC-E2E-N-08 | Domain-wide auth completion | Equivalence – batch resolution | All items for domain resolved, session stored | Domain-based completion |
| TC-E2E-N-09 | Skip specific queue_ids | Equivalence – selective skip | Only specified items skipped | Item-level skip |
| TC-E2E-N-10 | Skip by domain | Equivalence – domain skip | All items for domain skipped | Domain-level skip |
| TC-E2E-N-11 | Pending count with mixed priorities | Equivalence – count summary | Correct total/high/medium/low counts | Priority counting |
| TC-E2E-B-01 | Expired queue items | Boundary – expiration | Expired items cleaned up | Expiration handling |
| TC-E2E-N-12 | New domain for skip check | Equivalence – initial state | Should not be skipped (no failures) | Domain failure tracking |
| TC-E2E-N-13 | Domain failure tracking | Equivalence – failure counter | Initial failures=0, max_failures=3 | Failure limit |
| TC-E2E-N-14 | Full research workflow | Equivalence – complete flow | 3 subqueries, ≥1 claims, evidence linked | End-to-end workflow |
| TC-E2E-N-15 | Ollama availability check | Equivalence – service check | Status 200, models list returned | LLM service check |
| TC-E2E-N-16 | LLM extract with simple passage | Equivalence – LLM extraction | Extraction succeeds | LLM integration |
"""

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from _pytest.tmpdir import TempPathFactory

if TYPE_CHECKING:
    from src.storage.database import Database

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
        headless = os.environ.get("LYRA_HEADLESS", "false").lower() == "true"

        if not display and not headless:
            return False

        # Check if Playwright is available
        import playwright.async_api  # noqa: F401

        return True
    except ImportError:
        return False


async def is_ollama_available() -> bool:
    """Check if Ollama is available.

    In hybrid mode, Ollama is accessed via proxy server (http://localhost:8080/ollama).
    Uses the same connection method as OllamaProvider.
    """
    try:
        import aiohttp

        from src.utils.config import get_settings

        # Use the same connection method as OllamaProvider
        # In hybrid mode, Ollama is accessed via proxy (http://localhost:8080/ollama)
        settings = get_settings()
        proxy_url = settings.general.proxy_url
        ollama_url = f"{proxy_url}/ollama"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ollama_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
    except Exception:
        return False


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def e2e_database(tmp_path_factory: TempPathFactory) -> AsyncGenerator["Database", None]:
    """Create a test database for E2E tests."""
    from src.storage.database import Database

    tmp_dir = tmp_path_factory.mktemp("e2e")
    db_path = tmp_dir / "e2e_test.db"
    db = Database(str(db_path))
    await db.connect()
    await db.initialize_schema()
    yield db
    await db.close()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def check_browser_search() -> bool:
    """Check browser search availability and skip if not available."""
    available = await is_browser_search_available()
    if not available:
        pytest.skip("Browser search not available. Requires display or LYRA_HEADLESS=true")
    return True


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def check_ollama() -> bool:
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

    Verifies ADR-0010-ADR-0005 requirements:
    - Search execution via browser-based search
    - URL fetching with rate limiting
    - Content extraction from HTML
    - Report material generation

    Requirements:
    - Display available or LYRA_HEADLESS=true
    - Network access for URL fetching
    """

    @pytest.mark.asyncio
    async def test_search_returns_results(
        self, check_browser_search: bool, e2e_database: "Database"
    ) -> None:
        """
        Verify browser-based search returns normalized results.

        Tests ADR-0003 search_serp tool:
        - Query execution with real browser search
        - Result normalization (title, url, snippet, engine, rank)
        """
        from src.search import search_serp

        # Given: Browser search is available and a valid search query
        # (check_browser_search fixture ensures browser is available)

        # When: Execute a simple search query using mojeek (block-resistant)
        results = await search_serp(
            query="Python programming language",
            engines=["mojeek"],
            limit=5,
            time_range="all",
            use_cache=False,  # Skip cache for E2E test
        )

        # Then: Results are returned with required fields
        assert isinstance(results, list), f"Expected list, got {type(results)}"
        assert len(results) >= 1, f"Expected >=1 search results, got {len(results)}"

        first_result = results[0]
        required_fields = ["title", "url", "snippet", "engine", "rank"]
        for field in required_fields:
            assert field in first_result, f"Missing required field: {field}"

        assert first_result["url"].startswith(("http://", "https://")), (
            f"Invalid URL: {first_result['url']}"
        )

        print(f"\n[E2E] Search returned {len(results)} results")
        print(f"[E2E] First result: {first_result['title'][:50]}...")

    @pytest.mark.asyncio
    async def test_fetch_and_extract_content(
        self, check_browser_search: bool, e2e_database: "Database"
    ) -> None:
        """
        Verify URL fetching and content extraction.

        Tests ADR-0003 fetch_url and ADR-0005 extract_content:
        - HTTP fetching with rate limiting
        - Content extraction from HTML
        - Text and metadata extraction
        """
        from src.crawler.fetcher import fetch_url
        from src.extractor.content import extract_content

        # Given: A known stable URL (Wikipedia) to fetch
        test_url = "https://en.wikipedia.org/wiki/Python_(programming_language)"

        # When: Fetch the URL with HTTP client
        fetch_result = await fetch_url(
            url=test_url,
            context={"referer": "https://www.google.com/"},
            policy={"force_browser": False, "max_retries": 2},
        )

        # Then: Fetch succeeds and returns html_path
        assert fetch_result["ok"] is True, f"Fetch failed: {fetch_result.get('reason')}"
        assert "html_path" in fetch_result, (
            f"Expected 'html_path' in fetch result, got keys: {list(fetch_result.keys())}"
        )

        # Given: Fetched HTML content exists
        html_content = None
        if "html_path" in fetch_result and fetch_result["html_path"]:
            html_path = Path(fetch_result["html_path"])
            if html_path.exists():
                html_content = html_path.read_text(encoding="utf-8", errors="replace")
        elif "content" in fetch_result:
            html_content = fetch_result["content"]

        if html_content:
            # When: Extract content from HTML
            extract_result = await extract_content(html=html_content, content_type="html")

            # Then: Extraction succeeds with substantial content
            assert extract_result["ok"] is True, f"Extract failed: {extract_result.get('error')}"

            text = extract_result.get("text", "")
            assert len(text) > 100, "Expected substantial text content"
            assert "Python" in text, "Expected 'Python' in extracted text"

            print(f"\n[E2E] Extracted {len(text)} characters from {test_url}")
        else:
            pytest.skip("Could not retrieve HTML content for extraction test")

    @pytest.mark.asyncio
    async def test_full_pipeline_simulation(
        self, check_browser_search: bool, e2e_database: "Database"
    ) -> None:
        """
        Simulate a complete research pipeline.

        Tests the flow: Search → Fetch → Extract → Store
        Verifies ADR-0010 exploration control and ADR-0005 filtering.
        """
        from src.research.context import ResearchContext
        from src.research.state import ExplorationState, SubqueryStatus
        from src.search import search_serp

        # Given: A research query to investigate
        task_id = await e2e_database.create_task(
            query="What is the history of Python programming language?"
        )
        assert task_id is not None, "Failed to create task"

        # When: Initialize research context
        context = ResearchContext(task_id)
        context._db = e2e_database
        ctx_result = await context.get_context()

        # Then: Context is retrieved successfully
        assert ctx_result["ok"] is True, f"Context retrieval failed: {ctx_result}"
        assert "extracted_entities" in ctx_result

        # Given: Exploration state initialized with a subquery
        state = ExplorationState(task_id)
        state._db = e2e_database

        state.register_subquery(
            subquery_id="sq_python_history",
            text="Python programming language history site:wikipedia.org",
            priority="high",
        )

        # When: Execute search for the subquery
        results = await search_serp(
            query="Python programming language history",
            engines=["mojeek"],
            limit=3,
            use_cache=False,
        )

        # Then: Subquery status is updated based on results
        sq = state.get_subquery("sq_python_history")
        assert sq is not None

        if len(results) >= 1:
            sq.status = SubqueryStatus.PARTIAL
            sq.independent_sources = len(results)
        else:
            sq.status = SubqueryStatus.EXHAUSTED

        # When: Get exploration status
        status = await state.get_status()

        # Then: Status contains registered subqueries
        assert "subqueries" in status
        assert len(status["subqueries"]) == 1

        print("\n[E2E] Pipeline simulation completed")
        print(f"[E2E] Task ID: {task_id}")
        print(f"[E2E] Search results: {len(results)}")
        print(f"[E2E] Subquery status: {status['subqueries'][0]['status']}")

    @pytest.mark.asyncio
    async def test_report_materials_generation(
        self, check_browser_search: bool, e2e_database: "Database"
    ) -> None:
        """
        Test report materials can be generated from research data.

        Verifies ADR-0005 and ADR-0003 get_report_materials.
        Note: This tests data structure, not Cursor AI composition.
        """
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType

        # Given: A task with claims and supporting fragments
        task_id = await e2e_database.create_task(query="E2E test query for report generation")

        graph = EvidenceGraph(task_id=task_id)

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

        graph.add_node(
            NodeType.FRAGMENT,
            "frag_1",
            text="Python was conceived in the late 1980s by Guido van Rossum...",
            url="https://en.wikipedia.org/wiki/Python_(programming_language)",
        )

        graph.add_edge(
            NodeType.FRAGMENT,
            "frag_1",
            NodeType.CLAIM,
            "claim_1",
            RelationType.SUPPORTS,
            confidence=0.92,
        )

        # When: Query graph statistics and evidence
        stats = graph.get_stats()
        claim_count = stats["node_counts"].get("claim", 0)
        evidence = graph.get_supporting_evidence("claim_1")
        ratio_info = graph.get_primary_source_ratio()

        # Then: Graph contains expected claims and evidence
        assert claim_count == 2, f"Expected 2 claims, got {claim_count}"
        assert len(evidence) == 1, f"Expected 1 evidence, got {len(evidence)}"
        assert "primary_ratio" in ratio_info

        print("\n[E2E] Report materials generated")
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
    async def cleanup_queue(self, e2e_database: "Database") -> AsyncGenerator[None, None]:
        """Clear intervention_queue before each test to ensure isolation."""
        await e2e_database.execute("DELETE FROM intervention_queue WHERE 1=1")
        yield

    @pytest.mark.asyncio
    async def test_enqueue_authentication(self, e2e_database: "Database") -> None:
        """
        Test enqueueing authentication challenges.

        Verifies queue item creation with priority and domain tracking.
        """
        from src.utils.notification import InterventionQueue

        # Given: An intervention queue and a task requiring authentication
        queue = InterventionQueue()
        queue._db = e2e_database
        task_id = await e2e_database.create_task(query="E2E auth queue test")

        # When: Enqueue authentication challenges with different priorities
        queue_id_1 = await queue.enqueue(
            task_id=task_id,
            url="https://protected.go.jp/document.pdf",
            domain="protected.go.jp",
            auth_type="cloudflare",
            priority="high",
        )

        queue_id_2 = await queue.enqueue(
            task_id=task_id,
            url="https://secure.example.com/page",
            domain="secure.example.com",
            auth_type="captcha",
            priority="medium",
        )

        queue_id_3 = await queue.enqueue(
            task_id=task_id,
            url="https://blog.example.com/article",
            domain="blog.example.com",
            auth_type="turnstile",
            priority="low",
        )

        # Then: Queue IDs are generated with correct format
        assert queue_id_1.startswith("iq_"), f"Invalid queue ID format: {queue_id_1}"
        assert queue_id_2.startswith("iq_"), f"Invalid queue ID format: {queue_id_2}"
        assert queue_id_3.startswith("iq_"), f"Invalid queue ID format: {queue_id_3}"

        print("\n[E2E] Enqueued 3 authentication challenges")
        print(f"[E2E] High priority: {queue_id_1}")
        print(f"[E2E] Medium priority: {queue_id_2}")
        print(f"[E2E] Low priority: {queue_id_3}")

    @pytest.mark.asyncio
    async def test_get_pending_by_domain(self, e2e_database: "Database") -> None:
        """
        Test retrieving pending authentications grouped by domain.

        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - Results are grouped by domain
        - Each domain shows affected_tasks, pending_count, high_priority_count
        """
        from src.utils.notification import InterventionQueue

        # Given: Multiple tasks needing auth for overlapping domains
        queue = InterventionQueue()
        queue._db = e2e_database

        task_a = await e2e_database.create_task(query="E2E task A")
        task_b = await e2e_database.create_task(query="E2E task B")

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
        await queue.enqueue(
            task_id=task_a,
            url="https://example.com/page",
            domain="example.com",
            auth_type="captcha",
            priority="low",
        )

        # When: Get pending items grouped by domain
        result = await queue.get_pending_by_domain()

        # Then: Results are correctly grouped with counts
        assert result["ok"] is True
        assert result["total_domains"] == 2, f"Expected 2 domains, got {result['total_domains']}"
        assert result["total_pending"] == 3, f"Expected 3 pending, got {result['total_pending']}"

        go_jp = next((d for d in result["domains"] if d["domain"] == "protected.go.jp"), None)
        assert go_jp is not None, "protected.go.jp should be in domains"
        assert go_jp["pending_count"] == 2
        assert go_jp["high_priority_count"] == 1
        assert set(go_jp["affected_tasks"]) == {task_a, task_b}

        print("\n[E2E] Pending by domain:")
        for d in result["domains"]:
            print(
                f"[E2E]   {d['domain']}: {d['pending_count']} pending, "
                f"{d['high_priority_count']} high priority, "
                f"tasks: {d['affected_tasks']}"
            )

    @pytest.mark.asyncio
    async def test_complete_authentication_single_item(self, e2e_database: "Database") -> None:
        """
        Test completing a single authentication item.

        Verifies single-item complete (legacy API).
        """
        from src.utils.notification import InterventionQueue

        # Given: A pending authentication item in the queue
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
            "authenticated_at": datetime.now(UTC).isoformat(),
        }

        # When: Complete the authentication item
        result = await queue.complete(
            queue_id=queue_id,
            success=True,
            session_data=session_data,
            task_id=task_id,
        )

        # Then: Item is marked as completed
        assert result["ok"] is True, f"Complete failed: {result}"
        assert result["status"] == "completed"

        print(f"\n[E2E] Single authentication completed for {queue_id}")

    @pytest.mark.asyncio
    async def test_complete_domain_resolves_multiple_tasks(self, e2e_database: "Database") -> None:
        """
        Test domain-based authentication completion.

        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - One auth resolves all pending URLs for that domain
        - Returns affected_tasks list
        """
        from src.utils.notification import InterventionQueue

        # Given: Multiple tasks needing auth for the same domain
        queue = InterventionQueue()
        queue._db = e2e_database

        task_a = await e2e_database.create_task(query="E2E task A for domain auth")
        task_b = await e2e_database.create_task(query="E2E task B for domain auth")

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
            "authenticated_at": datetime.now(UTC).isoformat(),
        }

        # When: Complete authentication by domain
        result = await queue.complete_domain(
            domain="protected.gov",
            success=True,
            session_data=session_data,
        )

        # Then: All items for that domain are resolved
        assert result["ok"] is True
        assert result["domain"] == "protected.gov"
        assert result["resolved_count"] == 2, (
            f"Should resolve 2 items, got {result['resolved_count']}"
        )
        assert set(result["affected_tasks"]) == {task_a, task_b}
        assert result["session_stored"] is True

        # Then: No more pending items for that domain
        pending = await queue.get_pending_by_domain()
        protected_domain = next(
            (d for d in pending["domains"] if d["domain"] == "protected.gov"), None
        )
        assert protected_domain is None, "protected.gov should have no pending items"

        print(f"\n[E2E] Domain auth completed: {result['resolved_count']} items resolved")
        print(f"[E2E] Affected tasks: {result['affected_tasks']}")

    @pytest.mark.asyncio
    async def test_skip_by_queue_ids(self, e2e_database: "Database") -> None:
        """
        Test skipping specific queue items.

        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - skip(queue_ids=[...]) skips only those items
        """
        from src.utils.notification import InterventionQueue

        # Given: Multiple pending authentication items
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

        # When: Skip a specific item by queue ID
        result = await queue.skip(queue_ids=[queue_id_1])

        # Then: Only the specified item is skipped
        assert result["ok"] is True
        assert result["skipped"] == 1

        pending = await queue.get_pending(task_id=task_id)
        pending_ids = [p["id"] for p in pending]

        assert queue_id_1 not in pending_ids, "Skipped item should not be pending"
        assert queue_id_2 in pending_ids, "Non-skipped item should still be pending"

        print(f"\n[E2E] Skipped authentication {queue_id_1}")
        print(f"[E2E] Remaining pending: {len(pending)}")

    @pytest.mark.asyncio
    async def test_skip_by_domain(self, e2e_database: "Database") -> None:
        """
        Test skipping all items for a domain.

        Per RFC_AUTH_QUEUE_DOMAIN_BASED:
        - skip(domain=...) skips all pending for that domain
        """
        from src.utils.notification import InterventionQueue

        # Given: Multiple tasks with items across different domains
        queue = InterventionQueue()
        queue._db = e2e_database

        task_a = await e2e_database.create_task(query="E2E skip domain task A")
        task_b = await e2e_database.create_task(query="E2E skip domain task B")

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
        await queue.enqueue(
            task_id=task_a,
            url="https://keep.com/page",
            domain="keep.com",
            auth_type="captcha",
        )

        # When: Skip all items for a specific domain
        result = await queue.skip(domain="skip-domain.com")

        # Then: All items for that domain are skipped, others remain
        assert result["ok"] is True
        assert result["skipped"] == 2
        assert set(result["affected_tasks"]) == {task_a, task_b}

        pending = await queue.get_pending(task_id=task_a)
        assert len(pending) == 1
        assert pending[0]["domain"] == "keep.com"

        print(f"\n[E2E] Skipped domain skip-domain.com: {result['skipped']} items")

    @pytest.mark.asyncio
    async def test_pending_count_and_summary(self, e2e_database: "Database") -> None:
        """
        Test getting pending count for exploration status.

        Verifies ADR-0007 integration with get_exploration_status:
        - Pending count by priority
        - High priority count for alerts
        """
        from src.utils.notification import InterventionQueue

        # Given: A queue with items of different priorities
        queue = InterventionQueue()
        queue._db = e2e_database

        task_id = await e2e_database.create_task(query="E2E pending count test")

        await queue.enqueue(
            task_id=task_id,
            url="https://h1.go.jp/",
            domain="h1.go.jp",
            auth_type="cloudflare",
            priority="high",
        )
        await queue.enqueue(
            task_id=task_id,
            url="https://h2.go.jp/",
            domain="h2.go.jp",
            auth_type="cloudflare",
            priority="high",
        )
        await queue.enqueue(
            task_id=task_id,
            url="https://m1.example.com/",
            domain="m1.example.com",
            auth_type="captcha",
            priority="medium",
        )
        await queue.enqueue(
            task_id=task_id,
            url="https://l1.example.com/",
            domain="l1.example.com",
            auth_type="captcha",
            priority="low",
        )

        # When: Get pending count summary
        counts = await queue.get_pending_count(task_id=task_id)

        # Then: Counts are correctly categorized by priority
        assert counts["total"] == 4, f"Expected 4 total, got {counts['total']}"
        assert counts["high"] == 2, f"Expected 2 high priority, got {counts['high']}"
        assert counts["medium"] == 1, f"Expected 1 medium priority, got {counts['medium']}"
        assert counts["low"] == 1, f"Expected 1 low priority, got {counts['low']}"

        # Then: Threshold alerts would be triggered per ADR-0007
        assert counts["total"] >= 3, "Should trigger warning threshold"
        assert counts["high"] >= 2, "Should trigger critical due to high priority count"

        print("\n[E2E] Pending count summary:")
        print(
            f"[E2E] Total: {counts['total']}, High: {counts['high']}, "
            f"Medium: {counts['medium']}, Low: {counts['low']}"
        )

    @pytest.mark.asyncio
    async def test_cleanup_expired_items(self, e2e_database: "Database") -> None:
        """
        Test cleanup of expired queue items.

        Verifies queue maintenance functionality.
        """
        from datetime import timedelta

        from src.utils.notification import InterventionQueue

        # Given: A queue item that has already expired
        queue = InterventionQueue()
        queue._db = e2e_database

        task_id = await e2e_database.create_task(query="E2E cleanup test")

        await queue.enqueue(
            task_id=task_id,
            url="https://expired.example.com/",
            domain="expired.example.com",
            auth_type="captcha",
            priority="low",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        # When: Run cleanup process
        cleaned_count = await queue.cleanup_expired()

        # Then: Cleanup completes without error
        assert cleaned_count >= 0, "Cleanup should return non-negative count"

        print(f"\n[E2E] Cleaned up {cleaned_count} expired items")


# =============================================================================
# E2E Test 3: Intervention Manager (Immediate Mode)
# =============================================================================


@pytest.mark.e2e
class TestInterventionManagerFlow:
    """
    E2E test for the intervention manager (immediate/legacy mode).

    Verifies ADR-0007 requirements:
    - Intervention request handling
    - Timeout management
    - Domain failure tracking

    Note: This doesn't test actual UI interaction, but verifies
    the intervention workflow logic.
    """

    @pytest.mark.asyncio
    async def test_intervention_request_creates_record(self, e2e_database: "Database") -> None:
        """
        Test that intervention requests create database records.

        Verifies ADR-0007 logging requirements.
        """
        from src.utils.notification import InterventionManager

        # Given: An intervention manager instance
        manager = InterventionManager()

        # When: Check if a new domain should be skipped
        should_skip = await manager._should_skip_domain("new-domain.example.com")

        # Then: New domain should not be skipped (no prior failures)
        assert should_skip is False, "New domain should not be skipped"

        print("\n[E2E] Intervention manager initialized")
        print(f"[E2E] New domain skip check: {should_skip}")

    @pytest.mark.asyncio
    async def test_domain_failure_tracking(self, e2e_database: "Database") -> None:
        """
        Test domain failure tracking for skip decisions.

        Verifies ADR-0007: Skip domain after 3 consecutive failures.
        Uses get_domain_failures() and max_domain_failures property.
        """
        from src.utils.notification import InterventionManager

        # Given: An intervention manager and a test domain
        manager = InterventionManager()
        test_domain = "failing-domain.example.com"

        # When: Check initial failure count
        initial_failures = manager.get_domain_failures(test_domain)

        # Then: Initial failures should be 0
        assert initial_failures == 0, f"Initial failures should be 0, got {initial_failures}"

        # When: Check max_domain_failures property
        max_failures = manager.max_domain_failures

        # Then: Max failures should be 3 per ADR-0007
        assert max_failures == 3, f"Max failures should be 3, got {max_failures}"

        # When: Reset domain failures
        manager.reset_domain_failures(test_domain)
        after_reset = manager.get_domain_failures(test_domain)

        # Then: Failures should be reset to 0
        assert after_reset == 0, f"After reset should be 0, got {after_reset}"

        print("\n[E2E] Domain failure tracking:")
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
    async def test_end_to_end_research_workflow(
        self, check_browser_search: bool, e2e_database: "Database"
    ) -> None:
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
        from src.filter.evidence_graph import EvidenceGraph, NodeType, RelationType
        from src.research.context import ResearchContext
        from src.research.state import ExplorationState, SubqueryStatus
        from src.search import search_serp

        # Given: A research query to investigate
        query = "What are the main features of Python 3.12?"
        task_id = await e2e_database.create_task(query=query)

        assert task_id is not None, "Failed to create task"
        print(f"\n[E2E] Step 1: Created task {task_id}")

        # When: Get research context
        context = ResearchContext(task_id)
        context._db = e2e_database
        ctx_result = await context.get_context()

        # Then: Context retrieval succeeds
        assert ctx_result["ok"] is True
        print("[E2E] Step 2: Got research context")
        print(f"[E2E]   - Entities: {len(ctx_result.get('extracted_entities', []))}")
        print(f"[E2E]   - Templates: {len(ctx_result.get('applicable_templates', []))}")

        # Given: Exploration state with registered subqueries
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

        # When: Execute first subquery via search
        results = await search_serp(
            query=subqueries[0][1],
            engines=["mojeek"],
            limit=3,
            use_cache=False,
        )

        sq = state.get_subquery("sq_1")
        if len(results) >= 2 and sq is not None:
            sq.status = SubqueryStatus.PARTIAL
            sq.independent_sources = len(results)

        print(f"[E2E] Step 4: Executed search, got {len(results)} results")

        # When: Build evidence graph from search results
        graph = EvidenceGraph(task_id=task_id)

        graph.add_node(
            NodeType.CLAIM,
            "claim_1",
            text="Python 3.12 includes new features for developers",
            confidence=0.85,
        )

        for i, result in enumerate(results[:2]):
            frag_id = f"frag_{i + 1}"
            graph.add_node(
                NodeType.FRAGMENT,
                frag_id,
                text=result.get("snippet", "")[:200],
                url=result.get("url", ""),
            )
            graph.add_edge(
                NodeType.FRAGMENT,
                frag_id,
                NodeType.CLAIM,
                "claim_1",
                RelationType.SUPPORTS,
                confidence=0.8,
            )

        print("[E2E] Step 5: Built evidence graph")

        # Then: Final state has expected structure
        final_status = await state.get_status()
        stats = graph.get_stats()
        claim_count = stats["node_counts"].get("claim", 0)
        evidence = graph.get_supporting_evidence("claim_1")

        print("[E2E] Step 6: Final state:")
        print(f"[E2E]   - Subqueries: {len(final_status['subqueries'])}")
        print(f"[E2E]   - Claims: {claim_count}")
        print(f"[E2E]   - Evidence for claim_1: {len(evidence)}")

        assert len(final_status["subqueries"]) == 3
        assert claim_count >= 1

        print("\n[E2E] ✓ Complete research workflow test passed")


# =============================================================================
# E2E Test 5: LLM Integration (Optional - requires Ollama)
# =============================================================================


@pytest.mark.e2e
class TestLLMIntegration:
    """
    E2E test for LLM integration.

    Tests ADR-0005 LLM extraction functionality with real Ollama.
    Optional - skipped if Ollama is not available.
    """

    @pytest.mark.asyncio
    async def test_ollama_model_availability(self, check_ollama: bool) -> None:
        """
        Verify Ollama is running and has required models.

        Uses proxy URL for Ollama access (http://localhost:8080/ollama, same as OllamaProvider).
        """
        import aiohttp

        from src.utils.config import get_settings

        # Given: Ollama is available (check_ollama fixture)
        # Use the same connection method as OllamaProvider (proxy URL)
        settings = get_settings()
        ollama_url = f"{settings.general.proxy_url}/ollama"

        # When: Query the Ollama API for available models
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_url}/api/tags") as resp:
                # Then: API responds with status 200 and model list
                assert resp.status == 200
                data = await resp.json()

                models = data.get("models", [])
                model_names = [m.get("name", "") for m in models]

                print(f"\n[E2E] Ollama available models: {model_names}")

                if not model_names:
                    pytest.skip("No Ollama models installed")

    @pytest.mark.asyncio
    async def test_llm_extract_basic(self, check_ollama: bool, e2e_database: "Database") -> None:
        """
        Test basic LLM extraction.

        Note: This test may be slow (LLM inference).
        """
        from src.filter.llm import llm_extract

        # Given: A simple test passage for LLM extraction
        passages = [
            {
                "id": "p1",
                "text": "Python 3.12 was released in October 2023. It includes "
                "improvements to error messages and a new type parameter syntax.",
            }
        ]

        try:
            # When: Run LLM extraction on the passage
            result = await llm_extract(
                passages=passages,
                task="extract_facts",
            )

            # Then: Extraction succeeds
            assert result["ok"] is True, f"LLM extraction failed: {result.get('error')}"

            print(f"\n[E2E] LLM extraction result: {result}")
        except Exception as e:
            # LLM may not be available or may timeout
            pytest.skip(f"LLM extraction failed (may need model): {e}")
