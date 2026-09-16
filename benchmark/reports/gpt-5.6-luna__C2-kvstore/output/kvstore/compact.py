import os
from typing import NamedTuple

from .record import encode_record
from .segment import Segment


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: "KVStore") -> CompactionResult:
    store._check_open()
    old_paths = store._segment_paths()
    before_records = store._total_records
    before_bytes = sum(path.stat().st_size for _, path in old_paths)
    new_id = max(seg_id for seg_id, _ in old_paths) + 1
    temp_path = store.root / f"{new_id:06d}.seg.tmp"
    temp = Segment(temp_path, new_id)
    entries = [(key, store.get(key)) for key in store.keys()]
    for key, value in entries:
        temp.append(encode_record(key, value))
    temp.close()
    for segment in store._segments.values():
        segment.close()
    final_path = store.root / f"{new_id:06d}.seg"
    os.replace(temp_path, final_path)
    for _, path in old_paths:
        path.unlink()
    store._segments = {new_id: Segment(final_path, new_id)}
    store.index = type(store.index)()
    store._total_records = 0
    for key, value, offset in store.active.scan():
        store.index.put(key, store_location(new_id, offset), tombstone=value is None)
        store._total_records += 1
    after_bytes = final_path.stat().st_size
    return CompactionResult(len(old_paths), len(entries), before_records - len(entries),
                            before_bytes - after_bytes)


def store_location(seg_id: int, offset: int) -> "Location":
    from .index import Location
    return Location(seg_id, offset)
