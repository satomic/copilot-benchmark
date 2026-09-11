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
    Raises ``ValueError`` when ``days`` is not a positive integer.
    """
    # Booleans are not calendar-day counts, despite being int subclasses.
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a positive integer")
    span = (end - start).days + 1

    chunks = []
    for offset in range(0, span, days):
        chunk_start = start + timedelta(days=offset)
        chunk_end = start + timedelta(days=min(offset + days, span) - 1)
        chunks.append((chunk_start, chunk_end))
    return chunks
