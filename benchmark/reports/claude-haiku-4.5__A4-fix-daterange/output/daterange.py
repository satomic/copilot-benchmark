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
        raise ValueError("days must be a positive integer")
    
    if end < start:
        return []

    chunks = []
    current_start = start
    while current_start <= end:
        # Calculate the end of this chunk: at most `days` days after the start
        # But we need to be inclusive on both ends, so if current_start is day 1,
        # adding `days` days takes us to day 1+days (not day 1+(days-1))
        # But the chunk spans at most `days` calendar days inclusive, so:
        # chunk spans days: current_start, current_start+1, ..., current_start+(days-1)
        # which means chunk_end = current_start + (days-1)
        chunk_end = current_start + timedelta(days=days - 1)
        
        # But don't extend past the end of the range
        if chunk_end > end:
            chunk_end = end
        
        chunks.append((current_start, chunk_end))
        
        # Move to the next chunk, starting exactly one day after this chunk ends
        current_start = chunk_end + timedelta(days=1)
    
    return chunks
