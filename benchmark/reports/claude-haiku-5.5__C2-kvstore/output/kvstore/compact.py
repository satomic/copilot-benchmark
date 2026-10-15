"""Compaction: rewrite the store into one segment holding one record per live key."""

from __future__ import annotations

import os
from typing import NamedTuple

from .record import encode_record
from .segment import Segment, list_segment_ids, segment_name
from .store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    store._ensure_open()
    before = store.stats()
    live = [(key, store.get(key)) for key in store.keys()]
    old_ids = list_segment_ids(store._root)
    new_id = max(old_ids) + 1
    tmp = store._root / f"{new_id:06d}.seg.tmp"
    final = store._root / segment_name(new_id)
    tmp.unlink(missing_ok=True)
    writer = Segment(tmp, new_id)
    try:
        for key, value in live:
            writer.append(encode_record(key, value))
    finally:
        writer.close()
    store._close_segments()
    os.replace(tmp, final)
    # Old segments are removed only after the new one is in place.
    for seg_id in old_ids:
        (store._root / segment_name(seg_id)).unlink(missing_ok=True)
    store._reload()
    after = store.stats()
    return CompactionResult(
        segments_removed=len(old_ids),
        records_written=len(live),
        records_dropped=before.total_records - len(live),
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
