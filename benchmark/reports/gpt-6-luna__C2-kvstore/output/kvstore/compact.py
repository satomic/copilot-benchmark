"""Store compaction support."""

import os
from typing import NamedTuple

from .index import Index, Location
from .record import encode_record
from .segment import Segment
from .store import KVStore


class CompactionResult(NamedTuple):
    """Summary of records rewritten and disk space reclaimed."""

    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    """Rewrite live key/value pairs into one atomically installed segment."""
    store._ensure_open()
    before = store.stats()
    old_paths = store._segment_paths()
    new_id = max((seg_id for seg_id, _ in old_paths), default=0) + 1
    temp_path = store.root / f"{new_id:06d}.seg.tmp"
    final_path = store.root / f"{new_id:06d}.seg"
    temp_path.unlink(missing_ok=True)
    temp = Segment(temp_path, new_id)
    new_index = Index()
    new_values: dict[str, str] = {}
    written = 0
    try:
        for key in store.keys():
            value = store.get(key)
            if value is None:
                continue
            offset = temp.append(encode_record(key, value))
            new_index.put(key, Location(new_id, offset), tombstone=False)
            new_values[key] = value
            written += 1
    finally:
        temp.close()
    os.replace(temp_path, final_path)
    store._active.close()
    removed = 0
    for _, path in old_paths:
        path.unlink()
        removed += 1
    store._active = Segment(final_path, new_id)
    store._active_needs_rollover = False
    store.index = new_index
    store._values = new_values
    store._total_records = written
    after = store.stats()
    return CompactionResult(
        removed,
        written,
        before.total_records - written,
        before.bytes_on_disk - after.bytes_on_disk,
    )
