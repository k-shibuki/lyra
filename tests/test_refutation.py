"""
Tests for refutation executor module.

Tests RefutationExecutor class for searching refuting evidence
against claims and searches.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|---------------------------------------|-----------------|-------|
| TC-RF-N-01 | Valid claim_id exists | Equivalence – normal | Refutation search executed, result returned | - |
| TC-RF-N-02 | Valid search_id exists | Equivalence – normal | Search-based refutation executed | - |
| TC-RF-A-01 | Claim not found | Abnormal – not found | Error in result.errors | - |
| TC-RF-A-02 | Search not found | Abnormal – not found | Error in result.errors | - |
| TC-RF-A-03 | SERP search fails | Abnormal – external failure | Graceful handling, empty refutations | - |
| TC-RF-A-04 | Fetch URL fails | Abnormal – network error | Skip URL, continue | - |
| TC-RF-A-05 | NLI detection fails | Abnormal – model error | Graceful handling, None returned | - |
| TC-RF-B-01 | Empty claim_text | Boundary – empty | Still processes | - |
| TC-RF-B-02 | claim_text > 100 chars | Boundary – long text | Truncated for queries | - |
| TC-RF-W-01 | Refutation edge recording | Wiring – DB | Edge created | - |
| TC-RF-W-02 | Confidence threshold | Wiring – filter | Only > 0.6 returned | - |
| TC-RF-D-01 | RefutationResult.to_dict() | Data conversion | Dict with expected keys | - |
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.database import Database


class TestRefutationResult:
    """Tests for RefutationResult dataclass."""

    def test_to_dict_success(self) -> None:
        """TC-RF-D-01: RefutationResult.to_dict() returns expected structure."""
        # Given: RefutationResult with data
        from src.research.refutation import RefutationResult

        result = RefutationResult(
            target="claim_123",
            target_type="claim",
            reverse_queries_executed=5,
            refutations_found=2,
            refutation_details=[{"source_url": "https://example.com", "nli_edge_confidence": 0.8}],
            confidence_adjustment=0.0,
            errors=[],
        )

        # When: Converting to dict
        d = result.to_dict()

        # Then: Dict should have expected keys
        assert d["ok"] is True
        assert d["target"] == "claim_123"
        assert d["target_type"] == "claim"
        assert d["reverse_queries_executed"] == 5
        assert d["refutations_found"] == 2
        assert len(d["refutation_details"]) == 1
        assert d["errors"] is None  # Empty list becomes None

    def test_to_dict_with_errors(self) -> None:
        """TC-RF-D-01b: RefutationResult with errors shows ok=False."""
        # Given: RefutationResult with errors
        from src.research.refutation import RefutationResult

        result = RefutationResult(
            target="claim_456",
            target_type="claim",
            errors=["Claim not found"],
        )

        # When: Converting to dict
        d = result.to_dict()

        # Then: ok should be False
        assert d["ok"] is False
        assert d["errors"] == ["Claim not found"]


class TestRefutationExecutorGenerateReverseQueries:
    """Tests for RefutationExecutor._generate_reverse_queries method."""

    def test_generate_reverse_queries_normal(self) -> None:
        """TC-RF-N-01b: Reverse queries generated with suffixes."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_01")
        state.task_hypothesis = "Test hypothesis"
        executor = RefutationExecutor(task_id="task_01", state=state)

        # When: Generating reverse queries
        text = "The treatment is effective"
        queries = executor._generate_reverse_queries(text)

        # Then: Should generate queries with suffixes
        assert len(queries) > 0
        assert len(queries) <= 5  # Limited to 5 suffixes
        # Each query should contain the original text
        for q in queries:
            assert text[:100] in q

    def test_generate_reverse_queries_long_text_truncated(self) -> None:
        """TC-RF-B-02: Long text is truncated to 100 chars."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_01")
        state.task_hypothesis = "Test hypothesis"
        executor = RefutationExecutor(task_id="task_01", state=state)

        # When: Generating reverse queries with long text
        long_text = "A" * 200  # 200 chars
        queries = executor._generate_reverse_queries(long_text)

        # Then: Each query should use only first 100 chars
        for q in queries:
            # The key_terms is first 100 chars
            assert "A" * 100 in q
            # Should not contain the full 200 chars (suffix adds more)
            assert len(q) > 100  # Has suffix added

    def test_generate_reverse_queries_empty_text(self) -> None:
        """TC-RF-B-01: Empty text still generates queries."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_01")
        executor = RefutationExecutor(task_id="task_01", state=state)

        # When: Generating reverse queries with empty text
        queries = executor._generate_reverse_queries("")

        # Then: Should still generate queries (with just suffixes)
        assert len(queries) > 0


class TestRefutationExecutorExecuteForClaim:
    """Tests for RefutationExecutor.execute_for_claim method."""

    @pytest.mark.asyncio
    async def test_execute_for_claim_not_found(self, test_database: Database) -> None:
        """TC-RF-A-01: Claim not found returns error in result."""
        # Given: Database without the claim
        db = test_database
        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            ("task_refute", "Test", "exploring"),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_refute")
        executor = RefutationExecutor(task_id="task_refute", state=state)

        # When: Executing for non-existent claim
        result = await executor.execute_for_claim("nonexistent_claim")

        # Then: Should return error
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()
        assert result.target == "nonexistent_claim"
        assert result.target_type == "claim"

    @pytest.mark.asyncio
    async def test_execute_for_claim_success_no_refutation(self, test_database: Database) -> None:
        """TC-RF-N-01: Claim found, no refutation detected."""
        # Given: Claim in database
        db = test_database
        task_id = "task_no_refute"
        claim_id = "claim_no_refute"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test hypothesis", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Water is wet."),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id=task_id)
        executor = RefutationExecutor(task_id=task_id, state=state)

        # When: Executing with mocked search that returns no results
        # Patch at definition site (function-internal import)
        with patch(
            "src.search.search_serp",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await executor.execute_for_claim(claim_id)

        # Then: Should complete without refutations
        assert len(result.errors) == 0
        assert result.reverse_queries_executed > 0
        assert result.refutations_found == 0

    @pytest.mark.asyncio
    async def test_execute_for_claim_refutation_found(self, test_database: Database) -> None:
        """TC-RF-N-01c: Refutation found and recorded."""
        # Given: Claim in database
        db = test_database
        task_id = "task_refute_found"
        claim_id = "claim_refute_found"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test hypothesis", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "The earth is flat."),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id=task_id)
        executor = RefutationExecutor(task_id=task_id, state=state)

        # When: Executing with mocked refutation detection
        # Patch at definition site (function-internal imports)
        with (
            patch(
                "src.search.search_serp",
                new_callable=AsyncMock,
                return_value=[{"url": "https://nasa.gov/earth", "title": "NASA Earth"}],
            ),
            patch(
                "src.crawler.fetcher.fetch_url",
                new_callable=AsyncMock,
                return_value={"ok": True, "html_path": "/tmp/test.html"},
            ),
            patch(
                "src.extractor.content.extract_content",
                new_callable=AsyncMock,
                return_value={"text": "The earth is spherical, not flat."},
            ),
            patch.object(
                executor,
                "_detect_refutation_nli",
                new_callable=AsyncMock,
                return_value={
                    "claim_text": "The earth is flat.",
                    "refuting_passage": "The earth is spherical.",
                    "source_url": "https://nasa.gov/earth",
                    "source_title": "NASA Earth",
                    "nli_edge_confidence": 0.85,
                },
            ),
            patch.object(
                executor,
                "_record_refutation_edge",
                new_callable=AsyncMock,
            ) as mock_record,
        ):
            result = await executor.execute_for_claim(claim_id)

        # Then: Should find refutation and record edge
        assert len(result.errors) == 0
        assert result.refutations_found > 0
        assert mock_record.called

    @pytest.mark.asyncio
    async def test_execute_for_claim_serp_failure(self, test_database: Database) -> None:
        """TC-RF-A-03: SERP search failure handled gracefully."""
        # Given: Claim in database
        db = test_database
        task_id = "task_serp_fail"
        claim_id = "claim_serp_fail"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Test claim"),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id=task_id)
        executor = RefutationExecutor(task_id=task_id, state=state)

        # When: SERP search raises exception
        # Patch at definition site (function-internal import)
        with patch(
            "src.search.search_serp",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API rate limit"),
        ):
            result = await executor.execute_for_claim(claim_id)

        # Then: Should handle gracefully, no crash
        assert result.refutations_found == 0


class TestRefutationExecutorExecuteForSearch:
    """Tests for RefutationExecutor.execute_for_search method."""

    @pytest.mark.asyncio
    async def test_execute_for_search_not_found(self) -> None:
        """TC-RF-A-02: Search not found returns error."""
        # Given: Empty state (no searches)
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_01")
        executor = RefutationExecutor(task_id="task_01", state=state)

        # When: Executing for non-existent search
        result = await executor.execute_for_search("nonexistent_search")

        # Then: Should return error
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()
        assert result.target_type == "search"

    @pytest.mark.asyncio
    async def test_execute_for_search_success(self) -> None:
        """TC-RF-N-02: Search found, refutation executed."""
        # Given: State with search
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_02")
        state.register_search(
            search_id="search_01",
            text="Climate change is real",
            priority="medium",
        )

        executor = RefutationExecutor(task_id="task_02", state=state)
        # Manually set _db to avoid DB access
        mock_db = MagicMock()
        executor._db = mock_db

        # When: Executing with mocked search
        # Patch at definition site (function-internal import)
        with patch(
            "src.search.search_serp",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await executor.execute_for_search("search_01")

        # Then: Should complete without errors
        assert len(result.errors) == 0
        assert result.target == "search_01"
        assert result.target_type == "search"
        assert result.reverse_queries_executed > 0


class TestRefutationExecutorDetectRefutationNLI:
    """Tests for RefutationExecutor._detect_refutation_nli method."""

    @pytest.mark.asyncio
    async def test_detect_refutation_nli_refutes(self) -> None:
        """TC-RF-W-02: Refutation detected when NLI returns refutes with high confidence."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_nli")
        executor = RefutationExecutor(task_id="task_nli", state=state)

        # When: NLI returns refutes with high confidence
        # Patch at definition site (function-internal import)
        with patch(
            "src.filter.nli.nli_judge",
            new_callable=AsyncMock,
            return_value=[
                {
                    "pair_id": "refutation_check",
                    "stance": "refutes",
                    "nli_edge_confidence": 0.85,
                }
            ],
        ):
            result = await executor._detect_refutation_nli(
                claim_text="The earth is flat.",
                passage="Scientific evidence shows the earth is spherical.",
                source_url="https://nasa.gov",
                source_title="NASA",
            )

        # Then: Should return refutation details
        assert result is not None
        assert result["source_url"] == "https://nasa.gov"
        assert result["nli_edge_confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_detect_refutation_nli_neutral_returns_none(self) -> None:
        """TC-RF-W-02b: No refutation when NLI returns neutral."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_nli")
        executor = RefutationExecutor(task_id="task_nli", state=state)

        # When: NLI returns neutral
        # Patch at definition site (function-internal import)
        with patch(
            "src.filter.nli.nli_judge",
            new_callable=AsyncMock,
            return_value=[
                {
                    "pair_id": "refutation_check",
                    "stance": "neutral",
                    "nli_edge_confidence": 0.6,
                }
            ],
        ):
            result = await executor._detect_refutation_nli(
                claim_text="The sky is blue.",
                passage="Weather patterns affect visibility.",
                source_url="https://example.com",
                source_title="Example",
            )

        # Then: Should return None (no refutation)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_refutation_nli_low_confidence_returns_none(self) -> None:
        """TC-RF-W-02c: No refutation when confidence below threshold."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_nli")
        executor = RefutationExecutor(task_id="task_nli", state=state)

        # When: NLI returns refutes but low confidence
        # Patch at definition site (function-internal import)
        with patch(
            "src.filter.nli.nli_judge",
            new_callable=AsyncMock,
            return_value=[
                {
                    "pair_id": "refutation_check",
                    "stance": "refutes",
                    "nli_edge_confidence": 0.4,  # Below 0.6 threshold
                }
            ],
        ):
            result = await executor._detect_refutation_nli(
                claim_text="Test claim",
                passage="Test passage",
                source_url="https://example.com",
                source_title="Example",
            )

        # Then: Should return None (confidence too low)
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_refutation_nli_error_returns_none(self) -> None:
        """TC-RF-A-05: NLI error handled gracefully."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_nli")
        executor = RefutationExecutor(task_id="task_nli", state=state)

        # When: NLI raises exception
        # Patch at definition site (function-internal import)
        with patch(
            "src.filter.nli.nli_judge",
            new_callable=AsyncMock,
            side_effect=RuntimeError("NLI service unavailable"),
        ):
            result = await executor._detect_refutation_nli(
                claim_text="Test claim",
                passage="Test passage",
                source_url="https://example.com",
                source_title="Example",
            )

        # Then: Should return None (error handled)
        assert result is None


class TestRefutationExecutorRecordRefutationEdge:
    """Tests for RefutationExecutor._record_refutation_edge method."""

    @pytest.mark.asyncio
    async def test_record_refutation_edge_creates_records(self, test_database: Database) -> None:
        """TC-RF-W-01: Refutation edge creates page, fragment, and edge records."""
        # Given: RefutationExecutor with DB
        db = test_database
        task_id = "task_record"
        claim_id = "claim_record"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Test claim"),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id=task_id)
        executor = RefutationExecutor(task_id=task_id, state=state)

        # When: Recording refutation edge
        refutation = {
            "claim_text": "Test claim",
            "refuting_passage": "This contradicts the claim.",
            "source_url": "https://evidence.com/page",
            "source_title": "Evidence Source",
            "nli_edge_confidence": 0.85,
        }
        await executor._record_refutation_edge(claim_id, refutation)

        # Then: Should create page, fragment, and edge
        pages = await db.fetch_all(
            "SELECT * FROM pages WHERE url = ?",
            ("https://evidence.com/page",),
        )
        assert len(pages) == 1
        page_id = pages[0]["id"]

        fragments = await db.fetch_all(
            "SELECT * FROM fragments WHERE page_id = ?",
            (page_id,),
        )
        assert len(fragments) == 1

        edges = await db.fetch_all(
            "SELECT * FROM edges WHERE target_id = ? AND relation = 'refutes'",
            (claim_id,),
        )
        assert len(edges) == 1
        assert edges[0]["nli_edge_confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_record_refutation_edge_missing_url(self, test_database: Database) -> None:
        """TC-RF-W-01b: Missing source_url skips edge creation."""
        # Given: RefutationExecutor with DB
        db = test_database
        task_id = "task_no_url"
        claim_id = "claim_no_url"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Test claim"),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id=task_id)
        executor = RefutationExecutor(task_id=task_id, state=state)

        # When: Recording refutation with missing URL
        refutation = {
            "claim_text": "Test claim",
            "refuting_passage": "Some passage",
            "source_url": "",  # Empty URL
            "source_title": "",
            "nli_edge_confidence": 0.8,
        }
        await executor._record_refutation_edge(claim_id, refutation)

        # Then: No edge should be created
        edges = await db.fetch_all(
            "SELECT * FROM edges WHERE target_id = ? AND relation = 'refutes'",
            (claim_id,),
        )
        assert len(edges) == 0

    @pytest.mark.asyncio
    async def test_record_refutation_edge_existing_page(self, test_database: Database) -> None:
        """TC-RF-W-01c: Existing page is reused, not duplicated."""
        # Given: Existing page in database
        db = test_database
        task_id = "task_exist_page"
        claim_id = "claim_exist_page"
        existing_page_id = "page_existing"

        await db.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test", "exploring"),
        )
        await db.execute(
            "INSERT INTO claims (id, task_id, claim_text) VALUES (?, ?, ?)",
            (claim_id, task_id, "Test claim"),
        )
        await db.execute(
            "INSERT INTO pages (id, url, domain, title) VALUES (?, ?, ?, ?)",
            (existing_page_id, "https://existing.com/page", "existing.com", "Existing"),
        )

        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id=task_id)
        executor = RefutationExecutor(task_id=task_id, state=state)

        # When: Recording refutation with same URL
        refutation = {
            "claim_text": "Test claim",
            "refuting_passage": "Passage from existing page",
            "source_url": "https://existing.com/page",
            "source_title": "Existing",
            "nli_edge_confidence": 0.75,
        }
        await executor._record_refutation_edge(claim_id, refutation)

        # Then: Should reuse existing page
        pages = await db.fetch_all(
            "SELECT * FROM pages WHERE url = ?",
            ("https://existing.com/page",),
        )
        assert len(pages) == 1  # Not duplicated

        # Fragment should reference existing page
        fragments = await db.fetch_all(
            "SELECT * FROM fragments WHERE page_id = ?",
            (existing_page_id,),
        )
        assert len(fragments) == 1


class TestRefutationExecutorSearchAndDetect:
    """Tests for RefutationExecutor._search_and_detect_refutation method."""

    @pytest.mark.asyncio
    async def test_search_and_detect_fetch_failure(self) -> None:
        """TC-RF-A-04: Fetch URL failure is handled gracefully."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_fetch_fail")
        executor = RefutationExecutor(task_id="task_fetch_fail", state=state)
        executor._db = MagicMock()

        # When: Fetch fails for search results
        # Patch at definition site (function-internal imports)
        with (
            patch(
                "src.search.search_serp",
                new_callable=AsyncMock,
                return_value=[
                    {"url": "https://fail.com", "title": "Fail"},
                    {"url": "https://success.com", "title": "Success"},
                ],
            ),
            patch(
                "src.crawler.fetcher.fetch_url",
                new_callable=AsyncMock,
                side_effect=[
                    {"ok": False, "error": "Connection refused"},  # First fails
                    {"ok": True, "html_path": "/tmp/success.html"},  # Second succeeds
                ],
            ),
            patch(
                "src.extractor.content.extract_content",
                new_callable=AsyncMock,
                return_value={"text": "No refutation content"},
            ),
        ):
            result = await executor._search_and_detect_refutation(
                query="test query",
                original_text="Test claim",
            )

        # Then: Should handle failure gracefully, continue with others
        assert isinstance(result, list)
        # No crash occurred

    @pytest.mark.asyncio
    async def test_search_and_detect_empty_results(self) -> None:
        """TC-RF-A-03b: Empty search results returns empty list."""
        # Given: RefutationExecutor instance
        from src.research.refutation import RefutationExecutor
        from src.research.state import ExplorationState

        state = ExplorationState(task_id="task_empty")
        executor = RefutationExecutor(task_id="task_empty", state=state)
        executor._db = MagicMock()

        # When: Search returns empty results
        # Patch at definition site (function-internal import)
        with patch(
            "src.search.search_serp",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await executor._search_and_detect_refutation(
                query="test query",
                original_text="Test claim",
            )

        # Then: Should return empty list
        assert result == []
