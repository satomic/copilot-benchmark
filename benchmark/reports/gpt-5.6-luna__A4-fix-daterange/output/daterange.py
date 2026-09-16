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
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        raise ValueError("days must be a positive integer")

    if end < start:
        return []

    chunks = []
    chunk_start = start
    while chunk_start <= end:
        remaining = (end - chunk_start).days + 1
        chunk_length = min(days, remaining)
        chunk_end = chunk_start + timedelta(days=chunk_length - 1)
        chunks.append((chunk_start, chunk_end))
        if chunk_end == end:
            break
        chunk_start = chunk_end + timedelta(days=1)
    return chunks
