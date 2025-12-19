"""
Canonical paper index for unified deduplication.

Manages unique papers across Browser Search (SERP) and Academic API results.
"""

import hashlib
import re

from src.utils.logging import get_logger
from src.utils.schemas import CanonicalEntry, Paper, PaperIdentifier

logger = get_logger(__name__)


class PaperIdentityResolver:
    """Paper identity resolution."""

    def __init__(self, similarity_threshold: float = 0.9):
        """Initialize resolver.
        
        Args:
            similarity_threshold: Title similarity threshold (0.0-1.0)
        """
        self.similarity_threshold = similarity_threshold
        self._title_index: dict[str, str] = {}  # normalized_title -> canonical_id

    def resolve_identity(self, paper: Paper) -> str:
        """Determine canonical ID for a paper.
        
        Args:
            paper: Paper object
            
        Returns:
            Canonical ID string
        """
        # 1. DOI has highest priority
        if paper.doi:
            return f"doi:{paper.doi.lower().strip()}"

        # 2. Title + first author + year
        normalized_title = self._normalize_title(paper.title)
        first_author = self._extract_first_author_surname(paper.authors)
        year = paper.year

        if normalized_title and first_author and year:
            key = f"{normalized_title}|{first_author}|{year}"
            return f"meta:{hashlib.md5(key.encode()).hexdigest()[:12]}"

        # 3. Title similarity
        if normalized_title:
            similar_id = self._find_similar_title(normalized_title)
            if similar_id:
                return similar_id

            # Register as new
            new_id = f"title:{hashlib.md5(normalized_title.encode()).hexdigest()[:12]}"
            self._title_index[normalized_title] = new_id
            return new_id

        # 4. Fallback (unique ID)
        import uuid
        return f"unknown:{uuid.uuid4().hex[:8]}"

    def resolve_identity_from_identifier(self, identifier: PaperIdentifier) -> str:
        """Determine canonical ID from PaperIdentifier.
        
        Args:
            identifier: PaperIdentifier
            
        Returns:
            Canonical ID string
        """
        return identifier.get_canonical_id()

    def _normalize_title(self, title: str) -> str:
        """Normalize title.
        
        Args:
            title: Original title
            
        Returns:
            Normalized title
        """
        if not title:
            return ""
        # Lowercase, remove punctuation, remove articles, normalize whitespace
        title = title.lower()
        title = re.sub(r'[^\w\s]', ' ', title)
        title = re.sub(r'\b(the|a|an)\b', '', title)
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def _extract_first_author_surname(self, authors: list) -> str | None:
        """Extract first author's surname.
        
        Args:
            authors: List of Author objects
            
        Returns:
            Surname (lowercase) or None
        """
        if not authors:
            return None

        from src.utils.schemas import Author

        first_author = authors[0]
        if isinstance(first_author, Author):
            name = first_author.name
        elif isinstance(first_author, dict):
            name = first_author.get("name", "")
        else:
            name = str(first_author)

        # "John Smith" -> "smith", "Smith, John" -> "smith"
        if ',' in name:
            # "Last, First" format → take the part before comma
            surname = name.split(',')[0].strip()
        else:
            # "First Last" format → take the last word
            parts = name.split()
            surname = parts[-1] if parts else ""

        return surname.lower() if surname else None

    def _find_similar_title(self, normalized_title: str) -> str | None:
        """Find similar title (Jaccard coefficient).
        
        Args:
            normalized_title: Normalized title
            
        Returns:
            Existing canonical ID or None
        """
        target_words = set(normalized_title.split())

        for existing_title, canonical_id in self._title_index.items():
            existing_words = set(existing_title.split())

            intersection = len(target_words & existing_words)
            union = len(target_words | existing_words)

            if union > 0 and intersection / union >= self.similarity_threshold:
                return canonical_id

        return None


class CanonicalPaperIndex:
    """Unified deduplication index."""

    def __init__(self, similarity_threshold: float = 0.9):
        """Initialize index.
        
        Args:
            similarity_threshold: Title similarity threshold
        """
        self._index: dict[str, CanonicalEntry] = {}
        self._resolver = PaperIdentityResolver(similarity_threshold)

    def clear(self) -> None:
        """Clear the index."""
        self._index.clear()
        self._resolver._title_index.clear()
        logger.debug("CanonicalPaperIndex cleared")

    def register_paper(self, paper: Paper, source_api: str) -> str:
        """Register a paper from academic API.
        
        Args:
            paper: Paper object
            source_api: Source API name
            
        Returns:
            Canonical ID
        """
        canonical_id = self._resolver.resolve_identity(paper)

        if canonical_id in self._index:
            # Add source to existing entry
            entry = self._index[canonical_id]
            if entry.paper is None:
                # Existing entry is SERP-only, overwrite with API data
                entry.paper = paper
                entry.source = "both"
            elif entry.source == "api":
                # Same paper from multiple APIs, keep existing (priority controlled by caller)
                pass
            logger.debug("Paper already registered", canonical_id=canonical_id, source_api=source_api)
        else:
            # Register new entry
            self._index[canonical_id] = CanonicalEntry(
                canonical_id=canonical_id,
                paper=paper,
                serp_results=[],
                source="api",
            )
            logger.debug("Registered new paper", canonical_id=canonical_id, source_api=source_api)

        return canonical_id

    def register_serp_result(
        self,
        serp_result: "SearchResult",
        identifier: PaperIdentifier | None = None,
    ) -> str:
        """Register a SERP result.
        
        Args:
            serp_result: SearchResult object
            identifier: Extracted PaperIdentifier (optional)
            
        Returns:
            Canonical ID
        """
        if identifier is None:
            from src.search.identifier_extractor import IdentifierExtractor
            extractor = IdentifierExtractor()
            identifier = extractor.extract(serp_result.url)

        canonical_id = self._resolver.resolve_identity_from_identifier(identifier)

        if canonical_id in self._index:
            # Add SERP result to existing entry
            entry = self._index[canonical_id]
            entry.serp_results.append(serp_result)
            if entry.source == "api":
                entry.source = "both"
            logger.debug("SERP result linked to existing paper", canonical_id=canonical_id)
        else:
            # Register new entry (SERP only)
            self._index[canonical_id] = CanonicalEntry(
                canonical_id=canonical_id,
                paper=None,
                serp_results=[serp_result],
                source="serp",
            )
            logger.debug("Registered new SERP result", canonical_id=canonical_id)

        return canonical_id

    def find_by_title_similarity(self, normalized_title: str, threshold: float = 0.9) -> CanonicalEntry | None:
        """Find entry by title similarity.
        
        Args:
            normalized_title: Normalized title
            threshold: Similarity threshold
            
        Returns:
            CanonicalEntry or None
        """
        similar_id = self._resolver._find_similar_title(normalized_title)
        if similar_id and similar_id in self._index:
            return self._index[similar_id]
        return None

    def get_all_entries(self) -> list[CanonicalEntry]:
        """Get all entries.
        
        Returns:
            List of CanonicalEntry
        """
        return list(self._index.values())

    def get_stats(self) -> dict[str, int]:
        """Get statistics.
        
        Returns:
            Statistics dictionary
        """
        total = len(self._index)
        api_only = sum(1 for e in self._index.values() if e.source == "api")
        serp_only = sum(1 for e in self._index.values() if e.source == "serp")
        both = sum(1 for e in self._index.values() if e.source == "both")

        return {
            "total": total,
            "api_only": api_only,
            "serp_only": serp_only,
            "both": both,
        }
