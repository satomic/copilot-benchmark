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
    # Validate `days` before checking the range, so a bad `days` is always
    # reported even for an empty range. Bools and non-ints are rejected too.
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError(f"days must be a positive integer, got {days!r}")
    if end < start:
        return []

    one_day = timedelta(days=1)
    chunks = []
    chunk_start = start
    while True:
        # Compare remaining span in days (not dates) to avoid overflowing date.max.
        remaining = (end - chunk_start).days + 1
        chunk_end = chunk_start + timedelta(days=min(days, remaining) - 1)
        chunks.append((chunk_start, chunk_end))
        if chunk_end == end:
            return chunks
        chunk_start = chunk_end + one_day
