"""
Deduplication module for Lyra.
Uses MinHash/LSH and SimHash for detecting duplicate/near-duplicate text fragments.
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, cast

from datasketch import MinHash, MinHashLSH

from src.utils.config import get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DuplicateCluster:
    """A cluster of duplicate/near-duplicate fragments."""

    cluster_id: str
    canonical_id: str  # The representative fragment ID
    fragment_ids: list[str] = field(default_factory=list)
    similarity: float = 0.0

    def __len__(self) -> int:
        return len(self.fragment_ids)


class ShingleTokenizer:
    """Tokenizer for creating shingles (n-grams) from text."""

    def __init__(self, shingle_size: int = 3, use_words: bool = True):
        """Initialize shingle tokenizer.

        Args:
            shingle_size: Size of shingles (n-gram length).
            use_words: If True, use word-level shingles; if False, use character-level.
        """
        self.shingle_size = shingle_size
        self.use_words = use_words
        self._sudachi_tokenizer: Any = None

    def _get_sudachi(self) -> Any:
        """Get or create SudachiPy tokenizer."""
        if self._sudachi_tokenizer is None:
            try:
                from sudachipy import dictionary, tokenizer

                self._sudachi_tokenizer = dictionary.Dictionary().create()
                self._tokenize_mode = tokenizer.Tokenizer.SplitMode.A
            except ImportError:
                logger.warning("SudachiPy not available, using simple tokenization")
                self._sudachi_tokenizer = "simple"
        return self._sudachi_tokenizer

    def _tokenize_words(self, text: str) -> list[str]:
        """Tokenize text into words."""
        tokenizer = self._get_sudachi()

        if tokenizer == "simple":
            # Simple word tokenization
            return re.findall(r"\w+", text.lower())
        else:
            # SudachiPy tokenization
            tokens = [
                m.surface().lower()
                for m in tokenizer.tokenize(text, self._tokenize_mode)
                if m.surface().strip()
            ]
            return tokens

    def get_shingles(self, text: str) -> set[str]:
        """Extract shingles from text.

        Args:
            text: Input text.

        Returns:
            Set of shingle strings.
        """
        if self.use_words:
            tokens = self._tokenize_words(text)
            if len(tokens) < self.shingle_size:
                # For short texts, use the whole text as one shingle
                return {" ".join(tokens)} if tokens else set()

            shingles = set()
            for i in range(len(tokens) - self.shingle_size + 1):
                shingle = " ".join(tokens[i : i + self.shingle_size])
                shingles.add(shingle)
            return shingles
        else:
            # Character-level shingles
            text = text.lower().replace(" ", "_")
            if len(text) < self.shingle_size:
                return {text} if text else set()

            return {
                text[i : i + self.shingle_size] for i in range(len(text) - self.shingle_size + 1)
            }


class MinHashDeduplicator:
    """MinHash/LSH-based deduplicator for near-duplicate detection."""

    def __init__(
        self,
        num_perm: int = 128,
        threshold: float = 0.5,
        shingle_size: int = 3,
        use_word_shingles: bool = True,
    ):
        """Initialize MinHash deduplicator.

        Args:
            num_perm: Number of permutations for MinHash.
            threshold: Jaccard similarity threshold for considering duplicates.
            shingle_size: Size of shingles for tokenization.
            use_word_shingles: Use word-level (True) or character-level (False) shingles.
        """
        self.num_perm = num_perm
        self.threshold = threshold
        self.tokenizer = ShingleTokenizer(shingle_size, use_word_shingles)

        # LSH index for efficient similarity search
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._minhashes: dict[str, MinHash] = {}
        self._texts: dict[str, str] = {}

    def _create_minhash(self, text: str) -> MinHash:
        """Create MinHash signature for text.

        Args:
            text: Input text.

        Returns:
            MinHash object.
        """
        mh = MinHash(num_perm=self.num_perm)
        shingles = self.tokenizer.get_shingles(text)

        for shingle in shingles:
            mh.update(shingle.encode("utf-8"))

        return mh

    def add(self, fragment_id: str, text: str) -> None:
        """Add a fragment to the index.

        Args:
            fragment_id: Unique identifier for the fragment.
            text: Fragment text content.
        """
        if fragment_id in self._minhashes:
            logger.debug("Fragment already indexed", fragment_id=fragment_id)
            return

        mh = self._create_minhash(text)
        self._minhashes[fragment_id] = mh
        self._texts[fragment_id] = text

        try:
            self._lsh.insert(fragment_id, mh)
        except ValueError:
            # Already in LSH
            pass

    def add_batch(self, fragments: list[dict[str, Any]]) -> None:
        """Add multiple fragments to the index.

        Args:
            fragments: List of dicts with 'id' and 'text' keys.
        """
        for fragment in fragments:
            self.add(fragment["id"], fragment["text"])

    def query(self, text: str, exclude_id: str | None = None) -> list[str]:
        """Find similar fragments to given text.

        Args:
            text: Query text.
            exclude_id: Fragment ID to exclude from results.

        Returns:
            List of similar fragment IDs.
        """
        mh = self._create_minhash(text)
        results = self._lsh.query(mh)

        if exclude_id and exclude_id in results:
            results.remove(exclude_id)

        return list(results)

    def find_duplicates(self, fragment_id: str) -> list[tuple[str, float]]:
        """Find duplicates of a specific fragment.

        Args:
            fragment_id: Fragment ID to find duplicates for.

        Returns:
            List of (fragment_id, similarity) tuples.
        """
        if fragment_id not in self._minhashes:
            return []

        mh = self._minhashes[fragment_id]
        candidates = self._lsh.query(mh)

        results = []
        for cand_id in candidates:
            if cand_id != fragment_id:
                similarity = self.get_similarity(fragment_id, cand_id)
                results.append((cand_id, similarity))

        return sorted(results, key=lambda x: x[1], reverse=True)

    def get_similarity(self, id1: str, id2: str) -> float:
        """Get Jaccard similarity between two indexed fragments.

        Args:
            id1: First fragment ID.
            id2: Second fragment ID.

        Returns:
            Jaccard similarity score (0.0 to 1.0).
        """
        if id1 not in self._minhashes or id2 not in self._minhashes:
            return 0.0

        return cast(float, self._minhashes[id1].jaccard(self._minhashes[id2]))

    def get_clusters(self) -> list[DuplicateCluster]:
        """Get all duplicate clusters.

        Uses Union-Find to group fragments into clusters.

        Returns:
            List of DuplicateCluster objects.
        """
        # Union-Find data structure
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Find all duplicate pairs
        for frag_id in self._minhashes:
            duplicates = self.find_duplicates(frag_id)
            for dup_id, _ in duplicates:
                union(frag_id, dup_id)

        # Group by cluster root
        cluster_members: dict[str, list[str]] = defaultdict(list)
        for frag_id in self._minhashes:
            root = find(frag_id)
            cluster_members[root].append(frag_id)

        # Create cluster objects (only for clusters with >1 member)
        clusters = []
        for root, members in cluster_members.items():
            if len(members) > 1:
                # Choose canonical as the first added (earliest)
                canonical = members[0]

                # Calculate average similarity within cluster
                total_sim = 0.0
                count = 0
                for i, m1 in enumerate(members):
                    for m2 in members[i + 1 :]:
                        total_sim += self.get_similarity(m1, m2)
                        count += 1
                avg_sim = total_sim / count if count > 0 else 1.0

                cluster = DuplicateCluster(
                    cluster_id=hashlib.md5(root.encode()).hexdigest()[:12],
                    canonical_id=canonical,
                    fragment_ids=members,
                    similarity=avg_sim,
                )
                clusters.append(cluster)

        return clusters

    def get_duplicate_ratio(self) -> float:
        """Calculate the ratio of duplicate fragments.

        Returns:
            Ratio of fragments in duplicate clusters to total fragments.
        """
        if not self._minhashes:
            return 0.0

        clusters = self.get_clusters()
        duplicates_count = sum(len(c) - 1 for c in clusters)  # Don't count canonical

        return duplicates_count / len(self._minhashes)

    def deduplicate(
        self,
        fragments: list[dict[str, Any]],
        keep: str = "first",
    ) -> list[dict[str, Any]]:
        """Remove duplicate fragments, keeping only canonical versions.

        Args:
            fragments: List of fragment dicts with 'id' and 'text' keys.
            keep: Strategy for choosing canonical: 'first', 'longest', 'shortest'.

        Returns:
            Deduplicated list of fragments.
        """
        # Add all to index
        self.add_batch(fragments)

        # Get clusters
        clusters = self.get_clusters()

        # Build set of IDs to remove
        ids_to_remove: set[str] = set()
        for cluster in clusters:
            members = cluster.fragment_ids

            if keep == "longest":
                # Keep the longest text
                canonical = max(members, key=lambda x: len(self._texts.get(x, "")))
            elif keep == "shortest":
                # Keep the shortest text
                canonical = min(members, key=lambda x: len(self._texts.get(x, "")))
            else:
                # Keep first (default)
                canonical = members[0]

            for frag_id in members:
                if frag_id != canonical:
                    ids_to_remove.add(frag_id)

        # Filter fragments
        return [f for f in fragments if f["id"] not in ids_to_remove]

    def clear(self) -> None:
        """Clear all indexed data."""
        self._lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self._minhashes.clear()
        self._texts.clear()


class SimHash:
    """SimHash implementation for near-duplicate detection.

    SimHash is better for detecting documents with small changes,
    while MinHash is better for set similarity (shared shingles).
    """

    def __init__(self, bit_size: int = 64, shingle_size: int = 3):
        """Initialize SimHash.

        Args:
            bit_size: Number of bits in the hash (64 or 128).
            shingle_size: Size of shingles for tokenization.
        """
        self.bit_size = bit_size
        self.tokenizer = ShingleTokenizer(shingle_size, use_words=True)
        self._hashes: dict[str, int] = {}

    def _hash_token(self, token: str) -> int:
        """Hash a token to a bit_size-bit integer."""
        h = hashlib.md5(token.encode("utf-8")).digest()
        # Take first bit_size/8 bytes
        num_bytes = self.bit_size // 8
        return int.from_bytes(h[:num_bytes], "big")

    def compute(self, text: str) -> int:
        """Compute SimHash for text.

        Args:
            text: Input text.

        Returns:
            SimHash value as integer.
        """
        shingles = self.tokenizer.get_shingles(text)

        if not shingles:
            return 0

        # Initialize vector of bit weights
        weights = [0] * self.bit_size

        for shingle in shingles:
            h = self._hash_token(shingle)

            for i in range(self.bit_size):
                bit = (h >> i) & 1
                if bit:
                    weights[i] += 1
                else:
                    weights[i] -= 1

        # Convert to binary hash
        result = 0
        for i in range(self.bit_size):
            if weights[i] > 0:
                result |= 1 << i

        return result

    def add(self, fragment_id: str, text: str) -> int:
        """Add a fragment and return its SimHash.

        Args:
            fragment_id: Unique identifier.
            text: Fragment text.

        Returns:
            Computed SimHash value.
        """
        h = self.compute(text)
        self._hashes[fragment_id] = h
        return h

    @staticmethod
    def hamming_distance(hash1: int, hash2: int) -> int:
        """Calculate Hamming distance between two hashes.

        Args:
            hash1: First hash.
            hash2: Second hash.

        Returns:
            Number of differing bits.
        """
        xor = hash1 ^ hash2
        return bin(xor).count("1")

    def get_distance(self, id1: str, id2: str) -> int:
        """Get Hamming distance between two indexed fragments.

        Args:
            id1: First fragment ID.
            id2: Second fragment ID.

        Returns:
            Hamming distance (0 = identical).
        """
        if id1 not in self._hashes or id2 not in self._hashes:
            return self.bit_size  # Maximum distance

        return self.hamming_distance(self._hashes[id1], self._hashes[id2])

    def is_similar(self, id1: str, id2: str, max_distance: int = 3) -> bool:
        """Check if two fragments are similar (within Hamming distance threshold).

        Args:
            id1: First fragment ID.
            id2: Second fragment ID.
            max_distance: Maximum Hamming distance to consider similar.

        Returns:
            True if similar.
        """
        return self.get_distance(id1, id2) <= max_distance

    def find_similar(
        self,
        fragment_id: str,
        max_distance: int = 3,
    ) -> list[tuple[str, int]]:
        """Find similar fragments to a given one.

        Args:
            fragment_id: Fragment ID to search for.
            max_distance: Maximum Hamming distance.

        Returns:
            List of (fragment_id, distance) tuples.
        """
        if fragment_id not in self._hashes:
            return []

        target_hash = self._hashes[fragment_id]
        results = []

        for fid, h in self._hashes.items():
            if fid != fragment_id:
                dist = self.hamming_distance(target_hash, h)
                if dist <= max_distance:
                    results.append((fid, dist))

        return sorted(results, key=lambda x: x[1])

    def clear(self) -> None:
        """Clear all indexed hashes."""
        self._hashes.clear()


class HybridDeduplicator:
    """Combines MinHash and SimHash for robust deduplication.

    Uses MinHash for initial candidate detection (high recall),
    then SimHash for verification (high precision).
    """

    def __init__(
        self,
        minhash_threshold: float = 0.5,
        simhash_max_distance: int = 3,
        num_perm: int = 128,
        bit_size: int = 64,
        shingle_size: int = 3,
    ):
        """Initialize hybrid deduplicator.

        Args:
            minhash_threshold: MinHash similarity threshold.
            simhash_max_distance: SimHash maximum Hamming distance.
            num_perm: MinHash permutation count.
            bit_size: SimHash bit size.
            shingle_size: Shingle size for both.
        """
        self.minhash = MinHashDeduplicator(
            num_perm=num_perm,
            threshold=minhash_threshold,
            shingle_size=shingle_size,
        )
        self.simhash = SimHash(bit_size=bit_size, shingle_size=shingle_size)
        self.simhash_max_distance = simhash_max_distance

    def add(self, fragment_id: str, text: str) -> None:
        """Add a fragment to both indexes.

        Args:
            fragment_id: Unique identifier.
            text: Fragment text.
        """
        self.minhash.add(fragment_id, text)
        self.simhash.add(fragment_id, text)

    def add_batch(self, fragments: list[dict[str, Any]]) -> None:
        """Add multiple fragments.

        Args:
            fragments: List of dicts with 'id' and 'text' keys.
        """
        for fragment in fragments:
            self.add(fragment["id"], fragment["text"])

    def find_duplicates(self, fragment_id: str) -> list[tuple[str, float, int]]:
        """Find duplicates using both methods.

        Args:
            fragment_id: Fragment ID to search for.

        Returns:
            List of (fragment_id, minhash_similarity, simhash_distance) tuples.
        """
        # Get MinHash candidates
        minhash_results = self.minhash.find_duplicates(fragment_id)

        # Verify with SimHash
        verified_results = []
        for dup_id, mh_sim in minhash_results:
            sh_dist = self.simhash.get_distance(fragment_id, dup_id)
            if sh_dist <= self.simhash_max_distance:
                verified_results.append((dup_id, mh_sim, sh_dist))

        return verified_results

    def get_duplicate_ratio(self) -> float:
        """Get duplicate ratio from MinHash index."""
        return self.minhash.get_duplicate_ratio()

    def deduplicate(
        self,
        fragments: list[dict[str, Any]],
        keep: str = "first",
    ) -> list[dict[str, Any]]:
        """Remove duplicates using hybrid verification.

        Args:
            fragments: List of fragment dicts.
            keep: Strategy for choosing canonical.

        Returns:
            Deduplicated list.
        """
        return self.minhash.deduplicate(fragments, keep=keep)

    def clear(self) -> None:
        """Clear all indexes."""
        self.minhash.clear()
        self.simhash.clear()


# Global deduplicator instance
_deduplicator: MinHashDeduplicator | None = None


def get_deduplicator() -> MinHashDeduplicator:
    """Get or create the global deduplicator instance.

    Returns:
        MinHashDeduplicator instance.
    """
    global _deduplicator

    if _deduplicator is None:
        get_settings()
        _deduplicator = MinHashDeduplicator(
            num_perm=128,
            threshold=0.5,
            shingle_size=3,
            use_word_shingles=True,
        )

    return _deduplicator


async def deduplicate_fragments(
    fragments: list[dict[str, Any]],
    keep: str = "first",
) -> dict[str, Any]:
    """Deduplicate a list of text fragments.

    Args:
        fragments: List of dicts with 'id' and 'text' keys.
        keep: Strategy: 'first', 'longest', 'shortest'.

    Returns:
        Dict with 'fragments' (deduplicated), 'clusters', and 'duplicate_ratio'.
    """
    deduplicator = get_deduplicator()

    # Process fragments
    deduped = deduplicator.deduplicate(fragments, keep=keep)
    clusters = deduplicator.get_clusters()
    ratio = deduplicator.get_duplicate_ratio()

    logger.info(
        "Deduplication complete",
        original_count=len(fragments),
        deduplicated_count=len(deduped),
        cluster_count=len(clusters),
        duplicate_ratio=f"{ratio:.2%}",
    )

    return {
        "fragments": deduped,
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "canonical_id": c.canonical_id,
                "fragment_ids": c.fragment_ids,
                "similarity": c.similarity,
            }
            for c in clusters
        ],
        "duplicate_ratio": ratio,
        "original_count": len(fragments),
        "deduplicated_count": len(deduped),
    }
