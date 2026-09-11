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
    span = (end - start).days
    count = span // days

    chunks = []
    for i in range(count):
        chunk_start = start + timedelta(days=i * days)
        chunk_end = chunk_start + timedelta(days=days)
        chunks.append((chunk_start, chunk_end))
    return chunks
