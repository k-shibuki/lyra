"""Tests for database helper utilities.

Per 10.4.5 Phase 2d: Scale resilience for IN clause chunking.

## Test Perspectives Table

| Case ID | Input / Precondition | Perspective | Expected Result | Notes |
|---------|----------------------|-------------|-----------------|-------|
| TC-CHUNK-N-01 | items = 10 | Normal | 1 chunk | Small list |
| TC-CHUNK-N-02 | items = 600 | Normal | 2 chunks (500+100) | Multi-chunk |
| TC-CHUNK-B-01 | items = [] | Boundary | No chunks yielded | Empty |
| TC-CHUNK-B-02 | items = 500 | Boundary | 1 chunk exactly | Boundary |
| TC-CHUNK-B-03 | items = 501 | Boundary | 2 chunks (500+1) | Boundary+1 |
| TC-CHUNK-N-03 | custom size=100 | Normal | Respects custom size | Config |
"""

import pytest

from src.utils.db_helpers import CHUNK_SIZE, chunked

pytestmark = pytest.mark.unit


class TestChunked:
    """Tests for chunked() utility function."""

    def test_small_list_single_chunk(self) -> None:
        """TC-CHUNK-N-01: Small list yields single chunk.

        // Given: A list with 10 items
        // When: chunked() is called
        // Then: Returns 1 chunk with all 10 items
        """
        # Given
        items = list(range(10))

        # When
        chunks = list(chunked(items))

        # Then
        assert len(chunks) == 1
        assert chunks[0] == items

    def test_large_list_multiple_chunks(self) -> None:
        """TC-CHUNK-N-02: Large list yields multiple chunks.

        // Given: A list with 600 items
        // When: chunked() is called with default size (500)
        // Then: Returns 2 chunks (500 + 100)
        """
        # Given
        items = list(range(600))

        # When
        chunks = list(chunked(items))

        # Then
        assert len(chunks) == 2
        assert len(chunks[0]) == 500
        assert len(chunks[1]) == 100
        # Verify all items preserved
        assert chunks[0] + chunks[1] == items

    def test_empty_list_no_chunks(self) -> None:
        """TC-CHUNK-B-01: Empty list yields no chunks.

        // Given: An empty list
        // When: chunked() is called
        // Then: No chunks are yielded (empty iterator)
        """
        # Given
        items: list[int] = []

        # When
        chunks = list(chunked(items))

        # Then
        assert len(chunks) == 0

    def test_exact_chunk_size_single_chunk(self) -> None:
        """TC-CHUNK-B-02: List with exactly CHUNK_SIZE items yields 1 chunk.

        // Given: A list with exactly 500 items
        // When: chunked() is called
        // Then: Returns exactly 1 chunk
        """
        # Given
        items = list(range(CHUNK_SIZE))  # 500

        # When
        chunks = list(chunked(items))

        # Then
        assert len(chunks) == 1
        assert len(chunks[0]) == CHUNK_SIZE

    def test_chunk_size_plus_one_two_chunks(self) -> None:
        """TC-CHUNK-B-03: List with CHUNK_SIZE+1 items yields 2 chunks.

        // Given: A list with 501 items
        // When: chunked() is called
        // Then: Returns 2 chunks (500 + 1)
        """
        # Given
        items = list(range(CHUNK_SIZE + 1))  # 501

        # When
        chunks = list(chunked(items))

        # Then
        assert len(chunks) == 2
        assert len(chunks[0]) == CHUNK_SIZE
        assert len(chunks[1]) == 1

    def test_custom_chunk_size(self) -> None:
        """TC-CHUNK-N-03: Custom chunk size is respected.

        // Given: A list with 250 items
        // When: chunked() is called with size=100
        // Then: Returns 3 chunks (100 + 100 + 50)
        """
        # Given
        items = list(range(250))

        # When
        chunks = list(chunked(items, size=100))

        # Then
        assert len(chunks) == 3
        assert len(chunks[0]) == 100
        assert len(chunks[1]) == 100
        assert len(chunks[2]) == 50

    def test_chunk_size_one(self) -> None:
        """Chunk size of 1 yields individual items.

        // Given: A list with 3 items
        // When: chunked() is called with size=1
        // Then: Returns 3 chunks, each with 1 item
        """
        # Given
        items = ["a", "b", "c"]

        # When
        chunks = list(chunked(items, size=1))

        # Then
        assert len(chunks) == 3
        assert chunks == [["a"], ["b"], ["c"]]

    def test_preserves_order(self) -> None:
        """Chunking preserves item order.

        // Given: A list with ordered items
        // When: chunked() is called
        // Then: Items remain in original order across chunks
        """
        # Given
        items = list(range(1200))

        # When
        chunks = list(chunked(items))

        # Then
        reconstructed = []
        for chunk in chunks:
            reconstructed.extend(chunk)
        assert reconstructed == items

    def test_default_chunk_size_is_500(self) -> None:
        """Verify CHUNK_SIZE constant is 500.

        // Given: The module constant
        // When: Checking its value
        // Then: CHUNK_SIZE == 500
        """
        assert CHUNK_SIZE == 500
