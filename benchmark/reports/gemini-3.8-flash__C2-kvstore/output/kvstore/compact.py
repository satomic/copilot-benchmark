import os
from typing import TYPE_CHECKING, NamedTuple

from kvstore.index import Index, Location
from kvstore.record import encode_record
from kvstore.segment import Segment

if TYPE_CHECKING:
    from kvstore.store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: "KVStore") -> CompactionResult:
    store._ensure_open()

    seg_files = store._get_segment_files()
    total_records_before = store.stats().total_records
    bytes_before = sum(p.stat().st_size for _, p in seg_files)
    segments_removed = len(seg_files)

    max_id = max((sid for sid, _ in seg_files), default=0)
    new_id = max_id + 1
    tmp_path = store._root / f"{new_id:06d}.seg.tmp"
    final_path = store._root / f"{new_id:06d}.seg"

    new_locations: list[tuple[str, Location]] = []
    with open(tmp_path, "wb") as f:
        for key in store.keys():
            val = store.get(key)
            if val is None:
                continue
            blob = encode_record(key, val)
            offset = f.tell()
            f.write(blob)
            new_locations.append((key, Location(new_id, offset)))
        f.flush()

    store._active_segment.close()
    os.replace(tmp_path, final_path)

    for _, p in seg_files:
        if p.exists() and p != final_path:
            p.unlink()

    store._active_segment = Segment(final_path, new_id)
    new_index = Index()
    for key, loc in new_locations:
        new_index.put(key, loc, tombstone=False)
    store._index = new_index
    store._total_records = len(new_locations)

    bytes_after = final_path.stat().st_size
    records_written = len(new_locations)
    records_dropped = total_records_before - records_written
    bytes_reclaimed = bytes_before - bytes_after

    return CompactionResult(
        segments_removed=segments_removed,
        records_written=records_written,
        records_dropped=records_dropped,
        bytes_reclaimed=bytes_reclaimed,
    )
