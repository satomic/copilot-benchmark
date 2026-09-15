import os
from typing import NamedTuple

from .index import Index, Location
from .record import encode_record
from .segment import Segment
from .store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    before = store.stats()
    live_keys = store.keys()
    new_id = max(store._segments) + 1
    temp_path = store.root / f"{new_id:06d}.seg.tmp"
    new_index = Index()
    offset = 0
    with open(temp_path, "wb") as handle:
        for key in live_keys:
            value = store.get(key)
            if value is None:
                continue
            blob = encode_record(key, value)
            handle.write(blob)
            new_index.put(key, Location(new_id, offset), tombstone=False)
            offset += len(blob)
    final_path = store.root / f"{new_id:06d}.seg"
    os.replace(temp_path, final_path)

    for seg in store._segments.values():
        if seg._path != final_path:
            seg.close()
    old_paths = [seg._path for seg in store._segments.values() if seg._path != final_path]
    for path in old_paths:
        path.unlink(missing_ok=True)

    new_segment = Segment(final_path, new_id)
    store._segments = {new_id: new_segment}
    store._active = new_segment
    store._index = new_index
    store._total_records = len(live_keys)

    after = store.stats()
    return CompactionResult(
        segments_removed=before.segment_count,
        records_written=len(live_keys),
        records_dropped=before.total_records - len(live_keys),
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
