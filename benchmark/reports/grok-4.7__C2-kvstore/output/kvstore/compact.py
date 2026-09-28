"""Rewrite a store into one segment of live keys."""

from __future__ import annotations

import os
import pathlib
from typing import NamedTuple

from kvstore.errors import KVStoreError
from kvstore.record import encode_record
from kvstore.segment import Segment
from kvstore.store import KVStore, list_segments


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    """Rewrite live keys into a new segment, then delete the old ones.

    The new file is written as ``<id>.seg.tmp`` and moved with ``os.replace``.
    That temporary name does not match ``^\\d{6}\\.seg$``, so a crash before the
    move recovers the pre-compaction store.
    """
    before = store.stats()
    pairs = _live_pairs(store)
    segments = list_segments(store._root)
    new_id = max(seg_id for seg_id, _ in segments) + 1
    final = store._segment_path(new_id)
    tmp = store._root / f"{new_id:06d}.seg.tmp"
    _write_segment(tmp, new_id, pairs)
    os.replace(tmp, final)
    old_paths = [path for _, path in segments]
    store._install_compacted(final, new_id, old_paths)
    after = store.stats()
    written = len(pairs)
    return CompactionResult(
        segments_removed=len(old_paths),
        records_written=written,
        records_dropped=before.total_records - written,
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )


def _live_pairs(store: KVStore) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key in store.keys():
        value = store.get(key)
        if value is None:
            raise KVStoreError(f"live key {key!r} has no value")
        pairs.append((key, value))
    return pairs


def _write_segment(path: pathlib.Path, seg_id: int, pairs: list[tuple[str, str]]) -> None:
    if path.exists():
        path.unlink()
    segment = Segment(path, seg_id)
    try:
        for key, value in pairs:
            segment.append(encode_record(key, value))
    finally:
        segment.close()
