"""Compaction: rewrite all live data into one new segment."""
from __future__ import annotations

import os
from typing import NamedTuple

from .index import Index, Location
from .record import encode_record
from .segment import Segment
from .store import KVStore, segment_name


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    store._check_open()
    before = store.stats()
    keys = store.keys()
    old_ids = sorted(store._segments)
    new_id = old_ids[-1] + 1
    final = store.root / segment_name(new_id)
    tmp = store.root / (segment_name(new_id) + ".tmp")

    index = Index()
    offset = 0
    with open(tmp, "wb") as fh:
        for key in keys:
            blob = encode_record(key, store.get(key))
            fh.write(blob)
            index.put(key, Location(new_id, offset), tombstone=False)
            offset += len(blob)
        fh.flush()
        os.fsync(fh.fileno())

    for seg in store._segments.values():
        seg.close()
    os.replace(tmp, final)
    for seg_id in old_ids:
        os.remove(store.root / segment_name(seg_id))

    store._segments = {new_id: Segment(final, new_id)}
    store._index = index
    store._total = len(keys)
    after = store.stats()
    return CompactionResult(
        segments_removed=len(old_ids),
        records_written=len(keys),
        records_dropped=before.total_records - len(keys),
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
