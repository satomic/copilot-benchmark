"""Compaction: rewrite a store's live keys into a single fresh segment."""

from __future__ import annotations

import os
from typing import NamedTuple

from .index import Index, Location
from .record import encode_record
from .segment import Segment
from .store import KVStore, _discover_segment_ids, _seg_path


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    """Rewrite store into a single new segment containing only live keys."""
    store._check_open()
    before_stats = store.stats()
    seg_ids = _discover_segment_ids(store._root)
    new_id = (max(seg_ids) if seg_ids else 0) + 1

    keys = store.keys()
    tmp_path = store._root / f"{new_id:06d}.seg.tmp"
    final_path = _seg_path(store._root, new_id)

    new_index = Index()
    records_written = 0
    with open(tmp_path, "wb") as fh:
        offset = 0
        for key in keys:
            value = store.get(key)
            blob = encode_record(key, value)
            fh.write(blob)
            new_index.put(key, Location(new_id, offset), tombstone=False)
            offset += len(blob)
            records_written += 1
        fh.flush()
        os.fsync(fh.fileno())

    store._active.close()
    os.replace(tmp_path, final_path)

    segments_removed = 0
    for seg_id in seg_ids:
        path = _seg_path(store._root, seg_id)
        if path != final_path and path.exists():
            path.unlink()
            segments_removed += 1

    store._index = new_index
    store._active = Segment(final_path, new_id)
    store._total_records = records_written

    after_bytes = store.stats().bytes_on_disk
    return CompactionResult(
        segments_removed=segments_removed,
        records_written=records_written,
        records_dropped=before_stats.total_records - records_written,
        bytes_reclaimed=before_stats.bytes_on_disk - after_bytes,
    )
