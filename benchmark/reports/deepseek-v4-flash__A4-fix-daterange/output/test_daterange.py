"""Behavioural tests for daterange.split_range. Do not modify this file."""
from datetime import date

import pytest

from daterange import split_range

D = date


def test_uneven_split_keeps_trailing_partial_chunk():
    assert split_range(D(2026, 1, 1), D(2026, 1, 10), 3) == [
        (D(2026, 1, 1), D(2026, 1, 3)),
        (D(2026, 1, 4), D(2026, 1, 6)),
        (D(2026, 1, 7), D(2026, 1, 9)),
        (D(2026, 1, 10), D(2026, 1, 10)),
    ]


def test_exact_multiple():
    assert split_range(D(2026, 1, 1), D(2026, 1, 9), 3) == [
        (D(2026, 1, 1), D(2026, 1, 3)),
        (D(2026, 1, 4), D(2026, 1, 6)),
        (D(2026, 1, 7), D(2026, 1, 9)),
    ]


def test_single_day_range():
    assert split_range(D(2026, 5, 4), D(2026, 5, 4), 7) == [
        (D(2026, 5, 4), D(2026, 5, 4)),
    ]


def test_chunk_larger_than_range():
    assert split_range(D(2026, 3, 1), D(2026, 3, 5), 30) == [
        (D(2026, 3, 1), D(2026, 3, 5)),
    ]


def test_daily_chunks():
    assert split_range(D(2026, 2, 27), D(2026, 3, 1), 1) == [
        (D(2026, 2, 27), D(2026, 2, 27)),
        (D(2026, 2, 28), D(2026, 2, 28)),
        (D(2026, 3, 1), D(2026, 3, 1)),
    ]


def test_leap_year_boundary():
    assert split_range(D(2024, 2, 27), D(2024, 3, 2), 2) == [
        (D(2024, 2, 27), D(2024, 2, 28)),
        (D(2024, 2, 29), D(2024, 3, 1)),
        (D(2024, 3, 2), D(2024, 3, 2)),
    ]


def test_end_before_start_is_empty():
    assert split_range(D(2026, 1, 10), D(2026, 1, 1), 3) == []


@pytest.mark.parametrize("days", [0, -1, -7])
def test_non_positive_days_raises(days):
    with pytest.raises(ValueError):
        split_range(D(2026, 1, 1), D(2026, 1, 10), days)


def test_chunks_are_contiguous_and_cover_the_range():
    start, end, days = D(2026, 1, 1), D(2026, 4, 15), 11
    chunks = split_range(start, end, days)
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert (next_start - prev_end).days == 1
    for lo, hi in chunks:
        assert lo <= hi
        assert (hi - lo).days + 1 <= days
