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
    # bool is an int subclass; reject it so True/False are not silently accepted.
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError("days must be a positive integer")
    if end < start:
        return []

    step = timedelta(days=days)
    one_day = timedelta(days=1)
    chunks = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + step - one_day, end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end + one_day
    return chunks
