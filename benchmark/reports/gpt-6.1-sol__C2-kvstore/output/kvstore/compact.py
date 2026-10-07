import os
from typing import NamedTuple

from .index import Index, Location
from .record import encode_record
from .segment import Segment
from .store import KVStore, _segment_path


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    store._ensure_open()
    before = store.stats()
    new_id = max(store._segments) + 1
    final_path = _segment_path(store.root, new_id)
    temp_path = final_path.with_name(final_path.name + ".tmp")
    # A previous interrupted compaction's temporary file is never part of recovery.
    with temp_path.open("wb"):
        pass
    new_index = Index()
    temporary = Segment(temp_path, new_id)
    try:
        for key in store.keys():
            value = store.get(key)
            if value is None:
                raise ValueError("live key disappeared during compaction")
            offset = temporary.append(encode_record(key, value))
            new_index.put(key, Location(new_id, offset), tombstone=False)
        temporary._file.flush()
        os.fsync(temporary._file.fileno())
    finally:
        temporary.close()
    os.replace(temp_path, final_path)
    new_segment = Segment(final_path, new_id)
    new_segment._valid_size = new_segment.size
    old_segments = list(store._segments.values())
    store._segments[new_id] = new_segment
    store._active = new_segment
    for segment in old_segments:
        segment.close()
        segment.path.unlink()
        del store._segments[segment.seg_id]
    store._index = new_index
    store._total_records = len(new_index)
    after = store.stats()
    return CompactionResult(
        len(old_segments), after.total_records,
        before.total_records - after.total_records,
        before.bytes_on_disk - after.bytes_on_disk,
    )
