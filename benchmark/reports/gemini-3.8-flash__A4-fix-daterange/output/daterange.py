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
    if days <= 0:
        raise ValueError("days must be positive")
    if end < start:
        return []

    chunks = []
    current = start
    step = timedelta(days=days - 1)
    one_day = timedelta(days=1)

    while current <= end:
        chunk_end = min(end, current + step)
        chunks.append((current, chunk_end))
        current = chunk_end + one_day

    return chunks
