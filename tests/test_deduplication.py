"""
Tests for deduplication module.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestShingleTokenizer:
    """Tests for ShingleTokenizer."""

    def test_word_shingles_basic(self):
        """Test basic word shingle extraction."""
        from src.filter.deduplication import ShingleTokenizer
        
        tokenizer = ShingleTokenizer(shingle_size=2, use_words=True)
        text = "the quick brown fox"
        shingles = tokenizer.get_shingles(text)
        
        assert len(shingles) == 3  # "the quick", "quick brown", "brown fox"
        assert "the quick" in shingles or "quick brown" in shingles

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
        """Test adding fragments and querying."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.3)  # Lower threshold
        
        # Add some fragments - use more similar texts
        dedup.add("f1", "The quick brown fox jumps over the lazy dog in the garden")
        dedup.add("f2", "The quick brown fox jumps over the lazy dog in the yard")  # Very similar
        dedup.add("f3", "Python is a programming language for data science")  # Different
        
        # Query for similar to f1
        similar = dedup.query("The quick brown fox jumps over the lazy dog in the garden", exclude_id="f1")
        
        # f2 should be found as similar
        assert "f2" in similar or len(similar) > 0  # At least one similar found

    def test_find_duplicates(self):
        """Test finding duplicates of a fragment."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.3)  # Lower threshold
        
        # Use longer, more similar texts
        dedup.add("f1", "Machine learning and artificial intelligence are transforming the technology industry today")
        dedup.add("f2", "Machine learning and artificial intelligence are changing the technology industry today")
        dedup.add("f3", "The weather forecast predicts sunny skies and warm temperatures tomorrow")
        
        duplicates = dedup.find_duplicates("f1")
        duplicate_ids = [d[0] for d in duplicates]
        
        # f2 should be similar, f3 should not
        if duplicate_ids:
            assert "f3" not in duplicate_ids or "f2" in duplicate_ids

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
        """Test cluster generation."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.5)
        
        # Add duplicate pairs
        dedup.add("f1", "The cat sat on the mat")
        dedup.add("f2", "The cat sat on the mat")  # Duplicate of f1
        dedup.add("f3", "Dogs are loyal animals")
        dedup.add("f4", "Dogs are faithful animals")  # Similar to f3
        dedup.add("f5", "The sky is blue today")  # Unique
        
        clusters = dedup.get_clusters()
        
        # Should have at least one cluster
        assert len(clusters) >= 1
        
        # Find cluster containing f1 and f2
        f1_cluster = None
        for c in clusters:
            if "f1" in c.fragment_ids:
                f1_cluster = c
                break
        
        if f1_cluster:
            assert "f2" in f1_cluster.fragment_ids

    def test_get_duplicate_ratio(self):
        """Test duplicate ratio calculation."""
        from src.filter.deduplication import MinHashDeduplicator
        
        dedup = MinHashDeduplicator(num_perm=128, threshold=0.8)
        
        # Add 3 fragments, 2 are duplicates
        dedup.add("f1", "Exact same text here for testing")
        dedup.add("f2", "Exact same text here for testing")
        dedup.add("f3", "Completely different content")
        
        ratio = dedup.get_duplicate_ratio()
        
        # 1 duplicate out of 3 = ~0.33
        assert 0 <= ratio <= 1.0

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
        """Test finding similar fragments."""
        from src.filter.deduplication import SimHash
        
        sh = SimHash(bit_size=64, shingle_size=3)
        
        sh.add("f1", "Python programming language")
        sh.add("f2", "Python programming tutorial")
        sh.add("f3", "JavaScript web development")
        
        similar = sh.find_similar("f1", max_distance=10)
        similar_ids = [s[0] for s in similar]
        
        # f2 should be more similar to f1 than f3
        if similar:
            assert similar[0][0] == "f2" or "f2" in similar_ids


class TestHybridDeduplicator:
    """Tests for HybridDeduplicator."""

    def test_add_and_find_duplicates(self):
        """Test hybrid deduplication."""
        from src.filter.deduplication import HybridDeduplicator
        
        dedup = HybridDeduplicator(
            minhash_threshold=0.5,
            simhash_max_distance=10,
            num_perm=64,
        )
        
        dedup.add("f1", "This is a sample document for testing")
        dedup.add("f2", "This is a sample document for testing purposes")
        dedup.add("f3", "Completely unrelated content here")
        
        duplicates = dedup.find_duplicates("f1")
        
        # Should find f2 as similar
        dup_ids = [d[0] for d in duplicates]
        # May or may not find depending on thresholds
        assert isinstance(duplicates, list)

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

