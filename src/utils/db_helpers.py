"""Database helper utilities for SQLite operations.

Provides utilities for handling SQLite limitations such as
SQLITE_MAX_VARIABLE_NUMBER (default 999) for IN clauses.
"""

from collections.abc import Iterator

# Conservative chunk size for IN clauses.
# SQLite's SQLITE_MAX_VARIABLE_NUMBER is typically 999.
# Use 500 to leave headroom for other query parameters.
CHUNK_SIZE = 500


def chunked[T](items: list[T], size: int = CHUNK_SIZE) -> Iterator[list[T]]:
    """Yield successive chunks of items for batch processing.

    This is useful for splitting large lists for SQL IN clauses
    to avoid SQLite's SQLITE_MAX_VARIABLE_NUMBER limit.

    Args:
        items: List of items to chunk.
        size: Maximum chunk size (default: CHUNK_SIZE = 500).

    Yields:
        Lists of at most `size` items each.

    Example:
        >>> list(chunked([1, 2, 3, 4, 5], size=2))
        [[1, 2], [3, 4], [5]]
        >>> list(chunked([], size=2))
        []
    """
    for i in range(0, len(items), size):
        yield items[i : i + size]
