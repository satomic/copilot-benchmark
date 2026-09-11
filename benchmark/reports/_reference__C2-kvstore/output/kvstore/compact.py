"""Compaction: rewrite the whole store as one segment of live records."""

from __future__ import annotations

import os
from typing import NamedTuple

from .index import Index, Location
from .record import encode_record
from .segment import Segment, segment_name
from .store import KVStore

__all__ = ["CompactionResult", "compact"]


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    """Merge every segment into one holding the newest record per live key.

    Every segment takes part, so nothing older can survive to shadow a deletion and
    tombstones are dropped outright. The new segment is built under a ``.tmp`` name
    that deliberately does not match the segment pattern, so a crash before the
    ``os.replace`` leaves the pre-compaction store intact and recoverable.
    """
    before = store.stats()
    old_ids = store.segment_ids()
    new_id = (max(old_ids) + 1) if old_ids else 1

    # Read the surviving values before touching the filesystem: keys() order is the
    # contract for the new segment's layout.
    live = [(key, store.get(key)) for key in store.keys()]

    root = store.root
    final_path = root / segment_name(new_id)
    tmp_path = root / f"{segment_name(new_id)}.tmp"

    payload = bytearray()
    layout: list[tuple[str, int]] = []
    for key, value in live:
        layout.append((key, len(payload)))
        payload += encode_record(key, value if value is not None else "")
    tmp_path.write_bytes(bytes(payload))

    # The swap is the commit point. Only after it do the old files go away.
    store.active.close()
    os.replace(tmp_path, final_path)
    removed = 0
    for seg_id in old_ids:
        if seg_id == new_id:
            continue
        (root / segment_name(seg_id)).unlink()
        removed += 1

    index = Index()
    for key, offset in layout:
        index.put(key, Location(new_id, offset), tombstone=False)
    store._adopt(Segment(final_path, new_id), index, len(layout))

    after = store.stats()
    return CompactionResult(
        segments_removed=removed,
        records_written=len(layout),
        records_dropped=before.total_records - len(layout),
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
