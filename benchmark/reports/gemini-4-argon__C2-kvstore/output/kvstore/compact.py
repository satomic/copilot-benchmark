from __future__ import annotations

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
    before_stats = store.stats()
    live_keys = store.keys()
    live_items: list[tuple[str, str]] = []
    for key in live_keys:
        val = store.get(key)
        if val is not None:
            live_items.append((key, val))

    old_segments = list(store._segments.values())
    new_seg_id = max(store._segments) + 1
    final_path = store._segment_path(new_seg_id)
    tmp_path = store._root / f"{new_seg_id:06d}.seg.tmp"

    new_index = Index()
    offset = 0
    with tmp_path.open("wb") as tmp_file:
        for key, value in live_items:
            blob = encode_record(key, value)
            tmp_file.write(blob)
            new_index.put(
                key,
                Location(seg_id=new_seg_id, offset=offset),
                tombstone=False,
            )
            offset += len(blob)
        tmp_file.flush()

    os.replace(tmp_path, final_path)

    for seg in old_segments:
        seg.close()
        seg.path.unlink()

    new_seg = Segment(final_path, new_seg_id)
    store._segments = {new_seg_id: new_seg}
    store._active = new_seg
    store._index = new_index
    store._total_records = len(live_items)

    bytes_after = new_seg.size
    return CompactionResult(
        segments_removed=len(old_segments),
        records_written=len(live_items),
        records_dropped=before_stats.total_records - len(live_items),
        bytes_reclaimed=before_stats.bytes_on_disk - bytes_after,
    )
