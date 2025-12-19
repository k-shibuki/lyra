"""
Tests for deduplication module.
"""

import pytest

# All tests in this module are unit tests (no external dependencies)
pytestmark = pytest.mark.unit


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
        Threshold 0.5 is the production default per docs/REQUIREMENTS.md
        """
        from src.filter.deduplication import MinHashDeduplicator

        # Given: A MinHashDeduplicator with production threshold and test fragments
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        dedup.add("f1", "The quick brown fox jumps over the lazy dog")
        dedup.add("f2", "The quick brown fox jumps over the lazy dog")  # Identical
        dedup.add("f3", "Python is a completely different programming language")

        # When: Querying for similar fragments (excluding the query fragment itself)
        similar = dedup.query("The quick brown fox jumps over the lazy dog", exclude_id="f1")

        # Then: Identical text is found, unrelated text is not
        assert "f2" in similar, f"Identical text not found. Got: {similar}"
        assert "f3" not in similar, "Unrelated text incorrectly marked as similar"

    def test_find_duplicates(self):
        """Test finding duplicates of a fragment.
        
        Validates that near-duplicates are detected at production threshold.
        """
        from src.filter.deduplication import MinHashDeduplicator

        # Given: A deduplicator with identical and unrelated fragments
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        dedup.add("f1", "Machine learning and artificial intelligence are transforming technology")
        dedup.add("f2", "Machine learning and artificial intelligence are transforming technology")  # Identical
        dedup.add("f3", "The weather forecast predicts sunny skies and warm temperatures tomorrow")

        # When: Finding duplicates of f1
        duplicates = dedup.find_duplicates("f1")
        duplicate_ids = [d[0] for d in duplicates]

        # Then: Identical text is found as duplicate, unrelated text is not
        assert len(duplicate_ids) >= 1, "No duplicates found for identical text"
        assert "f2" in duplicate_ids, f"Identical text f2 not found. Got: {duplicate_ids}"
        assert "f3" not in duplicate_ids, "Unrelated text f3 incorrectly marked as duplicate"

    def test_get_similarity(self):
        """Test similarity calculation."""
        from src.filter.deduplication import MinHashDeduplicator

        # Given: A deduplicator with two identical text fragments
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.3)
        dedup.add("f1", "Hello world this is a test")
        dedup.add("f2", "Hello world this is a test")

        # When: Calculating similarity between the fragments
        similarity = dedup.get_similarity("f1", "f2")

        # Then: Similarity is very high (>0.9) for identical texts
        assert similarity > 0.9

    def test_get_clusters(self):
        """Test cluster generation.
        
        Validates that identical texts are clustered together.
        """
        from src.filter.deduplication import MinHashDeduplicator

        # Given: A deduplicator with duplicate pair and one unique fragment
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        dedup.add("f1", "The cat sat on the mat in the afternoon")
        dedup.add("f2", "The cat sat on the mat in the afternoon")  # Identical
        dedup.add("f3", "Completely unrelated content about programming")  # Unique

        # When: Getting duplicate clusters
        clusters = dedup.get_clusters()

        # Then: Exactly one cluster containing the duplicate pair
        assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}"
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

        # Given: 3 fragments where 2 are identical duplicates
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.8)
        dedup.add("f1", "Exact same text here for testing purposes")
        dedup.add("f2", "Exact same text here for testing purposes")  # Duplicate
        dedup.add("f3", "Completely different and unrelated content")

        # When: Calculating the duplicate ratio
        ratio = dedup.get_duplicate_ratio()

        # Then: Ratio is approximately 1/3 (one duplicate out of three)
        expected_ratio = 1 / 3
        assert abs(ratio - expected_ratio) < 0.1, f"Expected ratio ~{expected_ratio:.2f}, got {ratio:.2f}"

    def test_deduplicate_keep_first(self):
        """Test deduplication with keep='first' strategy."""
        from src.filter.deduplication import MinHashDeduplicator

        # Given: A list of fragments with duplicates
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.8)
        fragments = [
            {"id": "f1", "text": "This is a test sentence for deduplication"},
            {"id": "f2", "text": "This is a test sentence for deduplication"},
            {"id": "f3", "text": "Unique content here"},
        ]

        # When: Deduplicating with keep='first' strategy
        result = dedup.deduplicate(fragments, keep="first")

        # Then: First occurrence and unique fragments are kept
        assert len(result) == 2
        result_ids = [f["id"] for f in result]
        assert "f1" in result_ids  # First kept
        assert "f3" in result_ids

    def test_deduplicate_keep_longest(self):
        """Test deduplication with keep='longest' strategy."""
        from src.filter.deduplication import MinHashDeduplicator

        # Given: Fragments with similar content of varying lengths
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        fragments = [
            {"id": "f1", "text": "Short text"},
            {"id": "f2", "text": "Short text with additional words"},
            {"id": "f3", "text": "Different content"},
        ]

        # When: Deduplicating with keep='longest' strategy
        result = dedup.deduplicate(fragments, keep="longest")
        result_ids = [f["id"] for f in result]

        # Then: Unique content is preserved
        assert "f3" in result_ids

    def test_clear(self):
        """Test clearing the deduplicator."""
        from src.filter.deduplication import MinHashDeduplicator

        # Given: A deduplicator with one fragment added
        dedup = MinHashDeduplicator(num_perm=64, threshold=0.5)
        dedup.add("f1", "Test content")
        assert len(dedup._minhashes) == 1

        # When: Clearing the deduplicator
        dedup.clear()

        # Then: All stored minhashes are removed
        assert len(dedup._minhashes) == 0


class TestSimHash:
    """Tests for SimHash."""

    def test_compute_identical_texts(self):
        """Test SimHash for identical texts."""
        from src.filter.deduplication import SimHash

        # Given: A SimHash instance and identical text inputs
        sh = SimHash(bit_size=64, shingle_size=3)
        text = "The quick brown fox"

        # When: Computing hash for the same text twice
        h1 = sh.compute(text)
        h2 = sh.compute(text)

        # Then: Hashes are identical
        assert h1 == h2

    def test_hamming_distance_identical(self):
        """Test Hamming distance for identical hashes."""
        from src.filter.deduplication import SimHash

        # Given: Two identical binary values
        # When: Calculating Hamming distance
        dist = SimHash.hamming_distance(0b1010, 0b1010)

        # Then: Distance is zero
        assert dist == 0

    def test_hamming_distance_different(self):
        """Test Hamming distance for different hashes."""
        from src.filter.deduplication import SimHash

        # Given: Two binary values differing in 2 bits (0b1010 vs 0b1111)
        # When: Calculating Hamming distance
        dist = SimHash.hamming_distance(0b1010, 0b1111)

        # Then: Distance equals the number of differing bits
        assert dist == 2

    def test_add_and_get_distance(self):
        """Test adding fragments and getting distance."""
        from src.filter.deduplication import SimHash

        # Given: Three fragments with varying similarity
        sh = SimHash(bit_size=64, shingle_size=3)
        sh.add("f1", "Machine learning is amazing")
        sh.add("f2", "Machine learning is wonderful")
        sh.add("f3", "The weather is cold today")

        # When: Getting distances between fragments
        dist_f1_f2 = sh.get_distance("f1", "f2")
        dist_f1_f3 = sh.get_distance("f1", "f3")

        # Then: Similar texts have lower distance than dissimilar texts
        assert dist_f1_f2 < dist_f1_f3

    def test_is_similar(self):
        """Test similarity check."""
        from src.filter.deduplication import SimHash

        # Given: Two identical text fragments
        sh = SimHash(bit_size=64, shingle_size=3)
        sh.add("f1", "Identical text here")
        sh.add("f2", "Identical text here")

        # When: Checking if fragments are similar
        # Then: Identical texts are considered similar
        assert sh.is_similar("f1", "f2", max_distance=3)

    def test_find_similar(self):
        """Test finding similar fragments with SimHash."""
        from src.filter.deduplication import SimHash

        # Given: Fragments with identical and different texts
        sh = SimHash(bit_size=64, shingle_size=3)
        sh.add("f1", "Python programming language guide")
        sh.add("f2", "Python programming language guide")  # Identical
        sh.add("f3", "JavaScript web development framework")  # Different

        # When: Finding similar fragments to f1
        similar = sh.find_similar("f1", max_distance=5)

        # Then: Identical text is found in similar results
        assert len(similar) >= 1, "No similar fragments found for identical text"
        similar_ids = [s[0] for s in similar]
        assert "f2" in similar_ids, f"Identical text f2 not found. Got: {similar_ids}"


class TestHybridDeduplicator:
    """Tests for HybridDeduplicator."""

    def test_add_and_find_duplicates(self):
        """Test hybrid deduplication combines MinHash and SimHash correctly."""
        from src.filter.deduplication import HybridDeduplicator

        # Given: A hybrid deduplicator with identical and different fragments
        dedup = HybridDeduplicator(
            minhash_threshold=0.5,
            simhash_max_distance=10,
            num_perm=128,
        )
        dedup.add("f1", "This is a sample document for testing hybrid dedup")
        dedup.add("f2", "This is a sample document for testing hybrid dedup")  # Identical
        dedup.add("f3", "Completely unrelated content about different topic")

        # When: Finding duplicates of f1
        duplicates = dedup.find_duplicates("f1")
        dup_ids = [d[0] for d in duplicates]

        # Then: Identical text is detected as duplicate
        assert len(duplicates) >= 1, "No duplicates found for identical text"
        assert "f2" in dup_ids, f"Identical text f2 not found. Got: {dup_ids}"

    def test_add_batch(self):
        """Test batch adding."""
        from src.filter.deduplication import HybridDeduplicator

        # Given: A hybrid deduplicator and a list of fragments
        dedup = HybridDeduplicator()
        fragments = [
            {"id": "f1", "text": "First fragment"},
            {"id": "f2", "text": "Second fragment"},
        ]

        # When: Adding fragments in batch
        dedup.add_batch(fragments)

        # Then: All fragments are added to both MinHash and SimHash indices
        assert "f1" in dedup.minhash._minhashes
        assert "f2" in dedup.simhash._hashes


class TestDeduplicateFragments:
    """Tests for deduplicate_fragments function."""

    @pytest.mark.asyncio
    async def test_deduplicate_fragments_basic(self):
        """Test basic deduplication."""
        # Given: A list of fragments with duplicates
        import src.filter.deduplication as dedup_module
        dedup_module._deduplicator = None

        from src.filter.deduplication import deduplicate_fragments

        fragments = [
            {"id": "f1", "text": "This is a test document with some content"},
            {"id": "f2", "text": "This is a test document with some content"},
            {"id": "f3", "text": "Completely different text here"},
        ]

        # When: Running the deduplication function
        result = await deduplicate_fragments(fragments)

        # Then: Result contains expected keys and original count
        assert "fragments" in result
        assert "clusters" in result
        assert "duplicate_ratio" in result
        assert result["original_count"] == 3

    @pytest.mark.asyncio
    async def test_deduplicate_fragments_empty(self):
        """Test deduplication with empty list."""
        # Given: An empty list of fragments
        import src.filter.deduplication as dedup_module
        dedup_module._deduplicator = None

        from src.filter.deduplication import deduplicate_fragments

        # When: Running deduplication on empty input
        result = await deduplicate_fragments([])

        # Then: Result is empty with zero duplicate ratio
        assert result["fragments"] == []
        assert result["duplicate_ratio"] == 0.0


class TestDuplicateCluster:
    """Tests for DuplicateCluster dataclass."""

    def test_duplicate_cluster_len(self):
        """Test __len__ method."""
        from src.filter.deduplication import DuplicateCluster

        # Given: A DuplicateCluster with 3 fragment IDs
        cluster = DuplicateCluster(
            cluster_id="abc123",
            canonical_id="f1",
            fragment_ids=["f1", "f2", "f3"],
            similarity=0.85,
        )

        # When: Getting the length of the cluster
        # Then: Length equals the number of fragment IDs
        assert len(cluster) == 3

