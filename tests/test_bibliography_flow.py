"""Tests for bibliographic metadata flow.

Test Perspectives Table:
| Case ID | Input / Precondition | Perspective (Equivalence / Boundary) | Expected Result | Notes |
|---------|---------------------|--------------------------------------|-----------------|-------|
| TC-N-01 | Paper with 3 authors, venue, year, DOI | Equivalence - normal | works/work_authors/work_identifiers populated | Multi-author case |
| TC-N-02 | Paper with 1 author | Boundary - single author | author_display = single name (no "et al.") | |
| TC-N-03 | Paper with 0 authors | Boundary - empty | author_display = "unknown" | |
| TC-N-04 | Paper with only S2 source | Equivalence - normal | source_api = "semantic_scholar" | |
| TC-N-05 | Paper with OpenAlex source | Equivalence - normal | source_api = "openalex" | |
| TC-A-01 | Paper with no DOI | Boundary - NULL doi | canonical_id uses title hash | |
| TC-A-02 | Paper with no venue | Boundary - NULL venue | venue column is NULL | |
| TC-A-03 | Paper with no year | Boundary - NULL year | year column is NULL | |
| TC-W-01 | persist_work called twice with same canonical_id | Equivalence - upsert | No duplicate, counts updated | |
| TC-W-02 | work_identifiers duplicate provider_paper_id | Boundary - conflict | Upsert succeeds | |
| TC-R-01 | resolve_paper_id_to_page_id with valid paper_id | Equivalence - normal | Returns page_id | |
| TC-R-02 | resolve_paper_id_to_page_id with unknown paper_id | Boundary - not found | Returns None | |
| TC-V-01 | v_evidence_chain view with academic page | Equivalence - normal | author_display, venue, year populated | |
| TC-V-02 | v_claim_origins view with academic page | Equivalence - normal | author_display populated | |
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from src.research.schemas import paper_to_work_bibliography
from src.storage.works import (
    get_canonical_id_for_paper_id,
    persist_work,
    resolve_paper_id_to_page_id,
)
from src.utils.schemas import Author, Paper

if TYPE_CHECKING:
    from src.storage.database import Database


@pytest.fixture
def sample_paper_multi_author() -> Paper:
    """Sample paper with multiple authors."""
    return Paper(
        id="s2:abc123",
        title="DPP-4 Inhibitors in Type 2 Diabetes",
        abstract="Background: DPP-4 inhibitors are oral antidiabetic agents...",
        authors=[
            Author(name="Smith, John A.", affiliation="Harvard", orcid=None),
            Author(name="Doe, Jane B.", affiliation="MIT", orcid="0000-0001-2345-6789"),
            Author(name="Johnson, Robert", affiliation=None, orcid=None),
        ],
        year=2023,
        published_date=date(2023, 6, 15),
        doi="10.1234/diabetes.2023.001",
        arxiv_id=None,
        venue="Diabetes Care",
        citation_count=42,
        reference_count=85,
        is_open_access=True,
        oa_url="https://example.com/paper.pdf",
        pdf_url="https://example.com/paper.pdf",
        source_api="semantic_scholar",
    )


@pytest.fixture
def sample_paper_single_author() -> Paper:
    """Sample paper with single author."""
    return Paper(
        id="openalex:W12345",
        title="Single Author Study",
        abstract="Abstract content...",
        authors=[
            Author(name="Williams, Sarah", affiliation="Stanford", orcid=None),
        ],
        year=2022,
        published_date=None,
        doi="10.5678/study.2022",
        arxiv_id=None,
        venue="Journal of Medicine",
        citation_count=10,
        reference_count=30,
        is_open_access=False,
        oa_url=None,
        pdf_url=None,
        source_api="openalex",
    )


@pytest.fixture
def sample_paper_no_author() -> Paper:
    """Sample paper with no authors."""
    return Paper(
        id="s2:noauthors",
        title="Anonymous Paper",
        abstract="Content...",
        authors=[],
        year=2024,
        published_date=None,
        doi=None,
        arxiv_id="2401.12345",
        venue=None,
        citation_count=0,
        reference_count=5,
        is_open_access=True,
        oa_url="https://arxiv.org/pdf/2401.12345",
        pdf_url="https://arxiv.org/pdf/2401.12345",
        source_api="semantic_scholar",
    )


class TestWorkBibliographySchema:
    """Tests for WorkBibliography Pydantic schema."""

    # TC-N-01: Multi-author paper
    def test_author_display_multi_author(self, sample_paper_multi_author: Paper) -> None:
        """
        Given: Paper with 3 authors
        When: Convert to WorkBibliography
        Then: author_display = "Smith, John A. et al."
        """
        work = paper_to_work_bibliography(
            sample_paper_multi_author, "doi:10.1234/diabetes.2023.001"
        )
        assert work.author_display == "Smith, John A. et al."
        assert len(work.authors) == 3
        assert work.authors[0].position == 0
        assert work.authors[1].position == 1
        assert work.authors[2].position == 2

    # TC-N-02: Single author paper
    def test_author_display_single_author(self, sample_paper_single_author: Paper) -> None:
        """
        Given: Paper with 1 author
        When: Convert to WorkBibliography
        Then: author_display = single name (no "et al.")
        """
        work = paper_to_work_bibliography(sample_paper_single_author, "doi:10.5678/study.2022")
        assert work.author_display == "Williams, Sarah"
        assert len(work.authors) == 1

    # TC-N-03: No author paper
    def test_author_display_no_author(self, sample_paper_no_author: Paper) -> None:
        """
        Given: Paper with 0 authors
        When: Convert to WorkBibliography
        Then: author_display = "unknown"
        """
        work = paper_to_work_bibliography(sample_paper_no_author, "arxiv:2401.12345")
        assert work.author_display == "unknown"
        assert len(work.authors) == 0

    # TC-N-04/05: Source API propagation
    def test_source_api_propagation(
        self, sample_paper_multi_author: Paper, sample_paper_single_author: Paper
    ) -> None:
        """
        Given: Papers from different sources
        When: Convert to WorkBibliography
        Then: source_api matches original
        """
        work_s2 = paper_to_work_bibliography(sample_paper_multi_author, "doi:test")
        assert work_s2.source_api == "semantic_scholar"

        work_oa = paper_to_work_bibliography(sample_paper_single_author, "doi:test2")
        assert work_oa.source_api == "openalex"


class TestPersistWork:
    """Tests for persist_work function."""

    # TC-N-01: Normal persist with all fields
    @pytest.mark.asyncio
    async def test_persist_work_normal(
        self, test_database: Database, sample_paper_multi_author: Paper
    ) -> None:
        """
        Given: Paper with complete metadata
        When: persist_work called
        Then: works, work_authors, work_identifiers populated correctly
        """
        canonical_id = "doi:10.1234/diabetes.2023.001"
        await persist_work(test_database, sample_paper_multi_author, canonical_id)

        # Verify works table
        work_row = await test_database.fetch_one(
            "SELECT * FROM works WHERE canonical_id = ?",
            (canonical_id,),
        )
        assert work_row is not None
        assert work_row["title"] == sample_paper_multi_author.title
        assert work_row["year"] == 2023
        assert work_row["venue"] == "Diabetes Care"
        assert work_row["doi"] == "10.1234/diabetes.2023.001"
        assert work_row["source_api"] == "semantic_scholar"

        # Verify work_authors table
        author_rows = await test_database.fetch_all(
            "SELECT * FROM work_authors WHERE canonical_id = ? ORDER BY position",
            (canonical_id,),
        )
        assert len(author_rows) == 3
        assert author_rows[0]["name"] == "Smith, John A."
        assert author_rows[0]["position"] == 0
        assert author_rows[1]["name"] == "Doe, Jane B."
        assert author_rows[1]["orcid"] == "0000-0001-2345-6789"

        # Verify work_identifiers table
        id_row = await test_database.fetch_one(
            "SELECT * FROM work_identifiers WHERE canonical_id = ?",
            (canonical_id,),
        )
        assert id_row is not None
        assert id_row["provider"] == "semantic_scholar"
        assert id_row["provider_paper_id"] == "s2:abc123"

    # TC-W-01: Upsert behavior
    @pytest.mark.asyncio
    async def test_persist_work_upsert(
        self, test_database: Database, sample_paper_multi_author: Paper
    ) -> None:
        """
        Given: Paper already persisted
        When: persist_work called again with updated citation_count
        Then: Works updated, no duplicates
        """
        canonical_id = "doi:10.1234/diabetes.2023.001"
        await persist_work(test_database, sample_paper_multi_author, canonical_id)

        # Update citation count and persist again
        sample_paper_multi_author.citation_count = 100
        await persist_work(test_database, sample_paper_multi_author, canonical_id)

        # Verify only one work exists
        count_row = await test_database.fetch_one(
            "SELECT COUNT(*) as cnt FROM works WHERE canonical_id = ?",
            (canonical_id,),
        )
        assert count_row is not None
        assert count_row["cnt"] == 1

        # Verify citation count updated (MAX of old and new)
        work_row = await test_database.fetch_one(
            "SELECT citation_count FROM works WHERE canonical_id = ?",
            (canonical_id,),
        )
        assert work_row is not None
        assert work_row["citation_count"] == 100

    # TC-A-01: Paper with no DOI
    @pytest.mark.asyncio
    async def test_persist_work_no_doi(
        self, test_database: Database, sample_paper_no_author: Paper
    ) -> None:
        """
        Given: Paper with no DOI
        When: persist_work called
        Then: Works persisted with NULL doi
        """
        canonical_id = "arxiv:2401.12345"
        await persist_work(test_database, sample_paper_no_author, canonical_id)

        work_row = await test_database.fetch_one(
            "SELECT doi, venue FROM works WHERE canonical_id = ?",
            (canonical_id,),
        )
        assert work_row is not None
        assert work_row["doi"] is None
        assert work_row["venue"] is None


class TestResolvePaperId:
    """Tests for paper_id resolution functions."""

    @pytest.fixture
    async def setup_paper_page(
        self, test_database: Database, sample_paper_multi_author: Paper
    ) -> tuple[str, str]:
        """Setup a paper and page for testing."""
        canonical_id = "doi:10.1234/test"
        await persist_work(test_database, sample_paper_multi_author, canonical_id)

        # Create page linked to work
        page_id = "page_test123"
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, canonical_id, title, page_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                page_id,
                "https://example.com/paper",
                "example.com",
                canonical_id,
                sample_paper_multi_author.title,
                "academic_paper",
            ),
        )
        return canonical_id, page_id

    # TC-R-01: Normal resolution
    @pytest.mark.asyncio
    async def test_resolve_paper_id_found(
        self,
        test_database: Database,
        setup_paper_page: tuple[str, str],
        sample_paper_multi_author: Paper,
    ) -> None:
        """
        Given: Paper and page exist in DB
        When: resolve_paper_id_to_page_id called with valid paper_id
        Then: Returns page_id
        """
        _, page_id = setup_paper_page
        result = await resolve_paper_id_to_page_id(test_database, sample_paper_multi_author.id)
        assert result == page_id

    # TC-R-02: Paper not found
    @pytest.mark.asyncio
    async def test_resolve_paper_id_not_found(self, test_database: Database) -> None:
        """
        Given: Paper does not exist
        When: resolve_paper_id_to_page_id called
        Then: Returns None
        """
        result = await resolve_paper_id_to_page_id(test_database, "s2:nonexistent")
        assert result is None

    # TC-R-03: Get canonical_id
    @pytest.mark.asyncio
    async def test_get_canonical_id(
        self,
        test_database: Database,
        setup_paper_page: tuple[str, str],
        sample_paper_multi_author: Paper,
    ) -> None:
        """
        Given: Paper exists in work_identifiers
        When: get_canonical_id_for_paper_id called
        Then: Returns canonical_id
        """
        canonical_id, _ = setup_paper_page
        result = await get_canonical_id_for_paper_id(test_database, sample_paper_multi_author.id)
        assert result == canonical_id


class TestViewsWithBibliography:
    """Tests for SQL views with bibliographic data."""

    @pytest.fixture
    async def setup_evidence_chain(
        self, test_database: Database, sample_paper_multi_author: Paper
    ) -> dict:
        """Setup complete evidence chain for view testing."""
        import uuid

        # Create task
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            "INSERT INTO tasks (id, hypothesis, status) VALUES (?, ?, ?)",
            (task_id, "Test hypothesis", "running"),
        )

        # Create work
        canonical_id = "doi:10.1234/test.view"
        await persist_work(test_database, sample_paper_multi_author, canonical_id)

        # Create page
        page_id = f"page_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            """
            INSERT INTO pages (id, url, domain, canonical_id, title, page_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                page_id,
                "https://example.com/paper",
                "example.com",
                canonical_id,
                sample_paper_multi_author.title,
                "academic_paper",
            ),
        )

        # Create fragment
        fragment_id = f"frag_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            """
            INSERT INTO fragments (id, page_id, fragment_type, text_content, position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fragment_id, page_id, "abstract", "Test abstract content", 0),
        )

        # Create claim
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            """
            INSERT INTO claims (id, task_id, claim_text, claim_type)
            VALUES (?, ?, ?, ?)
            """,
            (claim_id, task_id, "Test claim text", "fact"),
        )

        # Create edges
        origin_edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (origin_edge_id, "fragment", fragment_id, "claim", claim_id, "origin"),
        )

        supports_edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            """
            INSERT INTO edges (id, source_type, source_id, target_type, target_id, relation, nli_edge_confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (supports_edge_id, "fragment", fragment_id, "claim", claim_id, "supports", 0.85),
        )

        return {
            "task_id": task_id,
            "page_id": page_id,
            "fragment_id": fragment_id,
            "claim_id": claim_id,
            "canonical_id": canonical_id,
        }

    # TC-V-01: v_evidence_chain view
    @pytest.mark.asyncio
    async def test_v_evidence_chain_with_bibliography(
        self, test_database: Database, setup_evidence_chain: dict
    ) -> None:
        """
        Given: Evidence chain with academic page
        When: Query v_evidence_chain view
        Then: author_display, venue, year populated
        """
        rows = await test_database.fetch_all(
            "SELECT * FROM v_evidence_chain WHERE task_id = ?",
            (setup_evidence_chain["task_id"],),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["year"] == 2023
        assert row["venue"] == "Diabetes Care"
        assert row["doi"] == "10.1234/diabetes.2023.001"
        assert row["source_api"] == "semantic_scholar"
        assert row["author_display"] == "Smith, John A. et al."

    # TC-V-02: v_claim_origins view
    @pytest.mark.asyncio
    async def test_v_claim_origins_with_bibliography(
        self, test_database: Database, setup_evidence_chain: dict
    ) -> None:
        """
        Given: Claim with origin edge to academic page
        When: Query v_claim_origins view
        Then: author_display populated
        """
        rows = await test_database.fetch_all(
            "SELECT * FROM v_claim_origins WHERE task_id = ?",
            (setup_evidence_chain["task_id"],),
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["year"] == 2023
        assert row["venue"] == "Diabetes Care"
        assert row["author_display"] == "Smith, John A. et al."


class TestAuthorDisplaySQLGeneration:
    """Tests for author_display SQL generation in views."""

    @pytest.fixture
    async def setup_works_with_authors(self, test_database: Database) -> list[str]:
        """Setup works with various author counts."""
        import uuid

        canonical_ids = []

        # 0 authors
        cid_0 = "test:zero_authors"
        await test_database.execute(
            "INSERT INTO works (canonical_id, title, source_api) VALUES (?, ?, ?)",
            (cid_0, "Zero Authors Paper", "semantic_scholar"),
        )
        canonical_ids.append(cid_0)

        # 1 author
        cid_1 = "test:one_author"
        await test_database.execute(
            "INSERT INTO works (canonical_id, title, source_api) VALUES (?, ?, ?)",
            (cid_1, "One Author Paper", "openalex"),
        )
        wa_id = f"wa_{uuid.uuid4().hex[:8]}"
        await test_database.execute(
            "INSERT INTO work_authors (id, canonical_id, position, name) VALUES (?, ?, ?, ?)",
            (wa_id, cid_1, 0, "Solo Author"),
        )
        canonical_ids.append(cid_1)

        # 2 authors
        cid_2 = "test:two_authors"
        await test_database.execute(
            "INSERT INTO works (canonical_id, title, source_api) VALUES (?, ?, ?)",
            (cid_2, "Two Authors Paper", "semantic_scholar"),
        )
        for pos, name in enumerate(["First Author", "Second Author"]):
            wa_id = f"wa_{uuid.uuid4().hex[:8]}"
            await test_database.execute(
                "INSERT INTO work_authors (id, canonical_id, position, name) VALUES (?, ?, ?, ?)",
                (wa_id, cid_2, pos, name),
            )
        canonical_ids.append(cid_2)

        return canonical_ids

    @pytest.mark.asyncio
    async def test_author_display_sql_boundary_cases(
        self, test_database: Database, setup_works_with_authors: list[str]
    ) -> None:
        """
        Given: Works with 0, 1, 2 authors
        When: Query with author_display SQL
        Then: Correct display for each case
        """
        cid_0, cid_1, cid_2 = setup_works_with_authors

        # Test SQL that mirrors view logic
        rows = await test_database.fetch_all(
            """
            SELECT
                w.canonical_id,
                CASE
                    WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 0 THEN 'unknown'
                    WHEN (SELECT COUNT(*) FROM work_authors wa WHERE wa.canonical_id = w.canonical_id) = 1
                        THEN (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id LIMIT 1)
                    ELSE (SELECT wa.name FROM work_authors wa WHERE wa.canonical_id = w.canonical_id ORDER BY wa.position LIMIT 1) || ' et al.'
                END AS author_display
            FROM works w
            WHERE w.canonical_id IN (?, ?, ?)
            ORDER BY w.canonical_id
            """,
            (cid_0, cid_1, cid_2),
        )

        results = {r["canonical_id"]: r["author_display"] for r in rows}
        assert results[cid_0] == "unknown"
        assert results[cid_1] == "Solo Author"
        assert results[cid_2] == "First Author et al."
