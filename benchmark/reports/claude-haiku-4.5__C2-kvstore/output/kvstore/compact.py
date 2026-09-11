from typing import NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .store import KVStore

from .record import encode_record
from .segment import Segment
from .index import Index, Location


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def _rebuild_index(store: "KVStore", new_seg_id: int, new_segment: Segment) -> Index:
    new_index = Index()
    for key in store.keys():
        offset = None
        for k, v, off in new_segment.scan():
            if k == key:
                offset = off
                break
        if offset is not None:
            new_index.put(key, Location(new_seg_id, offset), tombstone=False)
    return new_index


def compact(store: "KVStore") -> CompactionResult:
    live_keys = store.keys()
    old_segment_count = len(store._segments)
    old_bytes = sum(seg.size for seg in store._segments.values())
    
    new_seg_id = max(store._segments.keys()) + 1
    new_seg_path = store.root / f"{new_seg_id:06d}.seg"
    new_segment = Segment(new_seg_path, new_seg_id)
    
    for key in live_keys:
        value = store.get(key)
        record = encode_record(key, value)
        new_segment.append(record)
    
    old_segments = list(store._segments.values())
    old_record_count = sum(1 for seg in old_segments for _ in seg.scan())
    records_dropped = old_record_count - len(live_keys)
    
    store._segments.clear()
    store._segments[new_seg_id] = new_segment
    store._active_seg = new_segment
    store._index = _rebuild_index(store, new_seg_id, new_segment)
    
    for segment in old_segments:
        segment.close()
        segment.path.unlink()
    
    bytes_reclaimed = old_bytes - new_segment.size
    
    return CompactionResult(
        segments_removed=old_segment_count,
        records_written=len(live_keys),
        records_dropped=records_dropped,
        bytes_reclaimed=bytes_reclaimed
    )
