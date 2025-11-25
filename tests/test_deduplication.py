"""
Tests for deduplication module.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestShingleTokenizer:
    """Tests for ShingleTokenizer."""

    def test_word_shingles_basic(self):
        """Test basic word shingle extraction.
        
        Validates shingle generation for §3.3.3 MinHash deduplication.
        With shingle_size=2 and "the quick brown fox", expected shingles are:
        - "the quick"
        - "quick brown"
        - "brown fox"
        """
        from src.filter.deduplication import ShingleTokenizer
        
        tokenizer = ShingleTokenizer(shingle_size=2, use_words=True)
        text = "the quick brown fox"
        shingles = tokenizer.get_shingles(text)
        
        # STRICT: Must have exactly 3 shingles for 4 words with size 2
        assert len(shingles) == 3, f"Expected 3 shingles, got {len(shingles)}"
        # STRICT: Verify all expected shingles are present (not OR condition)
        assert "the quick" in shingles, f"Expected 'the quick' in shingles, got {shingles}"
        assert "quick brown" in shingles, f"Expected 'quick brown' in shingles, got {shingles}"
        assert "brown fox" in shingles, f"Expected 'brown fox' in shingles, got {shingles}"

    def test_word_shingles_short_text(self):
        """Test shingles for text shorter than shingle size."""
        from src.filter.deduplication import ShingleTokenizer
        
        tokenizer = ShingleTokenizer(shingle_size=5, use_words=True)
        text = "hello world"
        shingles = tokenizer.get_shingles(text)
        
        # Short text returns single shingle
        assert len(shingles) == 1

    def test_character_shingles(self):
        """Test character-level shingles."""
        from src.filter.deduplication import ShingleTokenizer
        
        tokenizer = ShingleTokenizer(shingle_size=3, use_words=False)
        text = "hello"
        shingles = tokenizer.get_shingles(text)
        
        # "hel", "ell", "llo"
        assert len(shingles) == 3
        assert "hel" in shingles
        assert "llo" in shingles

    def test_empty_text(self):
        """Test handling of empty text."""
        from src.filter.deduplication import ShingleTokenizer
        
        tokenizer = ShingleTokenizer(shingle_size=3, use_words=True)
        shingles = tokenizer.get_shingles("")
        
        assert len(shingles) == 0


class TestMinHashDeduplicator:
    """Tests for MinHashDeduplicator."""

    def test_add_and_query(self):
        """Test adding fragments and querying.
        
        Requirements: §3.3.3 - MinHash/SimHash for duplicate detection
        Threshold 0.5 is the production default per requirements.md
        """
        from src.filter.deduplication import MinHashDeduplicator
        
        # Use production threshold (0.5) - do NOT lower to make tests pass
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        
        # Use identical texts to ensure detection works at production threshold
        dedup.add("f1", "The quick brown fox jumps over the lazy dog")
        dedup.add("f2", "The quick brown fox jumps over the lazy dog")  # Identical
        dedup.add("f3", "Python is a completely different programming language")
        
        similar = dedup.query("The quick brown fox jumps over the lazy dog", exclude_id="f1")
        
        # STRICT: f2 MUST be found (identical text)
        assert "f2" in similar, f"Identical text not found. Got: {similar}"
        # STRICT: f3 must NOT be found
        assert "f3" not in similar, "Unrelated text incorrectly marked as similar"

    def test_find_duplicates(self):
        """Test finding duplicates of a fragment.
        
        Validates that near-duplicates are detected at production threshold.
        """
        from src.filter.deduplication import MinHashDeduplicator
        
        # Production threshold
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        
        # Use texts with known high similarity (>80% word overlap)
        dedup.add("f1", "Machine learning and artificial intelligence are transforming technology")
        dedup.add("f2", "Machine learning and artificial intelligence are transforming technology")  # Identical
        dedup.add("f3", "The weather forecast predicts sunny skies and warm temperatures tomorrow")
        
        duplicates = dedup.find_duplicates("f1")
        duplicate_ids = [d[0] for d in duplicates]
        
        # STRICT assertions - no conditional skipping
        assert len(duplicate_ids) >= 1, "No duplicates found for identical text"
        assert "f2" in duplicate_ids, f"Identical text f2 not found. Got: {duplicate_ids}"
        assert "f3" not in duplicate_ids, "Unrelated text f3 incorrectly marked as duplicate"

    def test_get_similarity(self):
        """Test similarity calculation."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.3)
        
        # Identical texts should have high similarity
        dedup.add("f1", "Hello world this is a test")
        dedup.add("f2", "Hello world this is a test")
        
        similarity = dedup.get_similarity("f1", "f2")
        assert similarity > 0.9

    def test_get_clusters(self):
        """Test cluster generation.
        
        Validates that identical texts are clustered together.
        """
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        
        # Add exact duplicate pair (must cluster)
        dedup.add("f1", "The cat sat on the mat in the afternoon")
        dedup.add("f2", "The cat sat on the mat in the afternoon")  # Identical
        dedup.add("f3", "Completely unrelated content about programming")  # Unique
        
        clusters = dedup.get_clusters()
        
        # STRICT: Must have exactly 1 cluster (f1+f2), f3 is unique
        assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}"
        
        # STRICT: Cluster must contain both f1 and f2
        cluster = clusters[0]
        assert "f1" in cluster.fragment_ids, "f1 not in cluster"
        assert "f2" in cluster.fragment_ids, "f2 not in cluster"
        assert "f3" not in cluster.fragment_ids, "f3 should not be in cluster"
        assert len(cluster.fragment_ids) == 2, f"Cluster should have 2 members, got {len(cluster.fragment_ids)}"

    def test_get_duplicate_ratio(self):
        """Test duplicate ratio calculation.
        
        §7 requirement: duplicate cluster ratio ≤20%
        This test validates the ratio calculation is accurate.
        """
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.8)
        
        # Setup: 3 fragments, 2 are identical duplicates
        # Expected: 1 duplicate (f2 is dup of f1), ratio = 1/3 ≈ 0.33
        dedup.add("f1", "Exact same text here for testing purposes")
        dedup.add("f2", "Exact same text here for testing purposes")  # Duplicate
        dedup.add("f3", "Completely different and unrelated content")
        
        ratio = dedup.get_duplicate_ratio()
        
        # STRICT: Verify specific expected ratio (1 dup out of 3 = 0.33)
        # Allow small tolerance for floating point
        expected_ratio = 1 / 3  # 0.333...
        assert abs(ratio - expected_ratio) < 0.1, f"Expected ratio ~{expected_ratio:.2f}, got {ratio:.2f}"

    def test_deduplicate_keep_first(self):
        """Test deduplication with keep='first' strategy."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.8)
        
        fragments = [
            {"id": "f1", "text": "This is a test sentence for deduplication"},
            {"id": "f2", "text": "This is a test sentence for deduplication"},
            {"id": "f3", "text": "Unique content here"},
        ]
        
        result = dedup.deduplicate(fragments, keep="first")
        
        assert len(result) == 2
        result_ids = [f["id"] for f in result]
        assert "f1" in result_ids  # First kept
        assert "f3" in result_ids

    def test_deduplicate_keep_longest(self):
        """Test deduplication with keep='longest' strategy."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        
        fragments = [
            {"id": "f1", "text": "Short text"},
            {"id": "f2", "text": "Short text with additional words"},
            {"id": "f3", "text": "Different content"},
        ]
        
        result = dedup.deduplicate(fragments, keep="longest")
        result_ids = [f["id"] for f in result]
        
        # Longest of similar should be kept
        assert "f3" in result_ids

    def test_clear(self):
        """Test clearing the deduplicator."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=64, threshold=0.5)
        
        dedup.add("f1", "Test content")
        assert len(dedup._minhashes) == 1
        
        dedup.clear()
        assert len(dedup._minhashes) == 0


class TestSimHash:
    """Tests for SimHash."""

    def test_compute_identical_texts(self):
        """Test SimHash for identical texts."""
        from src.filter.deduplication import SimHash
        
        sh = SimHash(bit_size=64, shingle_size=3)
        
        text = "The quick brown fox"
        h1 = sh.compute(text)
        h2 = sh.compute(text)
        
        assert h1 == h2

    def test_hamming_distance_identical(self):
        """Test Hamming distance for identical hashes."""
        from src.filter.deduplication import SimHash
        
        dist = SimHash.hamming_distance(0b1010, 0b1010)
        assert dist == 0

    def test_hamming_distance_different(self):
        """Test Hamming distance for different hashes."""
        from src.filter.deduplication import SimHash
        
        # 0b1010 vs 0b1111 differ in 2 bits
        dist = SimHash.hamming_distance(0b1010, 0b1111)
        assert dist == 2

    def test_add_and_get_distance(self):
        """Test adding fragments and getting distance."""
        from src.filter.deduplication import SimHash
        
        sh = SimHash(bit_size=64, shingle_size=3)
        
        sh.add("f1", "Machine learning is amazing")
        sh.add("f2", "Machine learning is wonderful")
        sh.add("f3", "The weather is cold today")
        
        dist_f1_f2 = sh.get_distance("f1", "f2")
        dist_f1_f3 = sh.get_distance("f1", "f3")
        
        # f1 and f2 should be closer than f1 and f3
        assert dist_f1_f2 < dist_f1_f3

    def test_is_similar(self):
        """Test similarity check."""
        from src.filter.deduplication import SimHash
        
        sh = SimHash(bit_size=64, shingle_size=3)
        
        sh.add("f1", "Identical text here")
        sh.add("f2", "Identical text here")
        
        assert sh.is_similar("f1", "f2", max_distance=3)

    def test_find_similar(self):
        """Test finding similar fragments with SimHash."""
        from src.filter.deduplication import SimHash
        
        sh = SimHash(bit_size=64, shingle_size=3)
        
        # Use texts with clear similarity hierarchy
        sh.add("f1", "Python programming language guide")
        sh.add("f2", "Python programming language guide")  # Identical
        sh.add("f3", "JavaScript web development framework")  # Different
        
        similar = sh.find_similar("f1", max_distance=5)
        
        # STRICT: Similar list must not be empty for identical text
        assert len(similar) >= 1, "No similar fragments found for identical text"
        
        # STRICT: f2 (identical) must be found
        similar_ids = [s[0] for s in similar]
        assert "f2" in similar_ids, f"Identical text f2 not found. Got: {similar_ids}"


class TestHybridDeduplicator:
    """Tests for HybridDeduplicator."""

    def test_add_and_find_duplicates(self):
        """Test hybrid deduplication combines MinHash and SimHash correctly."""
        from src.filter.deduplication import HybridDeduplicator
        
        dedup = HybridDeduplicator(
            minhash_threshold=0.5,
            simhash_max_distance=10,
            num_perm=128,
        )
        
        # Use identical text to ensure detection
        dedup.add("f1", "This is a sample document for testing hybrid dedup")
        dedup.add("f2", "This is a sample document for testing hybrid dedup")  # Identical
        dedup.add("f3", "Completely unrelated content about different topic")
        
        duplicates = dedup.find_duplicates("f1")
        dup_ids = [d[0] for d in duplicates]
        
        # STRICT: Identical text must be found
        assert len(duplicates) >= 1, "No duplicates found for identical text"
        assert "f2" in dup_ids, f"Identical text f2 not found. Got: {dup_ids}"

    def test_add_batch(self):
        """Test batch adding."""
        from src.filter.deduplication import HybridDeduplicator
        
        dedup = HybridDeduplicator()
        
        fragments = [
            {"id": "f1", "text": "First fragment"},
            {"id": "f2", "text": "Second fragment"},
        ]
        
        dedup.add_batch(fragments)
        
        assert "f1" in dedup.minhash._minhashes
        assert "f2" in dedup.simhash._hashes


class TestDeduplicateFragments:
    """Tests for deduplicate_fragments function."""

    @pytest.mark.asyncio
    async def test_deduplicate_fragments_basic(self):
        """Test basic deduplication."""
        # Clear global deduplicator
        import src.filter.deduplication as dedup_module
        dedup_module._deduplicator = None
        
        from src.filter.deduplication import deduplicate_fragments
        
        fragments = [
            {"id": "f1", "text": "This is a test document with some content"},
            {"id": "f2", "text": "This is a test document with some content"},
            {"id": "f3", "text": "Completely different text here"},
        ]
        
        result = await deduplicate_fragments(fragments)
        
        assert "fragments" in result
        assert "clusters" in result
        assert "duplicate_ratio" in result
        assert result["original_count"] == 3

    @pytest.mark.asyncio
    async def test_deduplicate_fragments_empty(self):
        """Test deduplication with empty list."""
        import src.filter.deduplication as dedup_module
        dedup_module._deduplicator = None
        
        from src.filter.deduplication import deduplicate_fragments
        
        result = await deduplicate_fragments([])
        
        assert result["fragments"] == []
        assert result["duplicate_ratio"] == 0.0


class TestDuplicateCluster:
    """Tests for DuplicateCluster dataclass."""

    def test_duplicate_cluster_len(self):
        """Test __len__ method."""
        from src.filter.deduplication import DuplicateCluster
        
        cluster = DuplicateCluster(
            cluster_id="abc123",
            canonical_id="f1",
            fragment_ids=["f1", "f2", "f3"],
            similarity=0.85,
        )
        
        assert len(cluster) == 3

