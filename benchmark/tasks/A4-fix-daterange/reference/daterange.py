"""Split a date range into consecutive chunks.

A range is always **inclusive** on both ends: ``[start, end]``.
``split_range`` cuts it into consecutive, non-overlapping chunks that together
cover exactly the whole range. Every chunk covers at most ``days`` calendar days;
only the final chunk may be shorter.
"""

from datetime import date, timedelta


def split_range(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Split the inclusive range [start, end] into chunks of at most `days` days.

    Returns a list of ``(chunk_start, chunk_end)`` tuples, both ends inclusive.
    Returns an empty list when ``end`` is before ``start``.
    Raises ``ValueError`` when ``days`` is not positive.
    """
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValueError(f"days must be a positive int, got {days!r}")
    if days < 1:
        raise ValueError(f"days must be positive, got {days}")
    if end < start:
        return []

    # The range is inclusive, so it spans one more day than the difference.
    span = (end - start).days + 1

    chunks: list[tuple[date, date]] = []
    for offset in range(0, span, days):
        chunk_start = start + timedelta(days=offset)
        chunk_end = min(chunk_start + timedelta(days=days - 1), end)
        chunks.append((chunk_start, chunk_end))
    return chunks
