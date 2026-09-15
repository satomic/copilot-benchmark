"""Whole-store compaction: rewrite live records into one fresh segment."""

from __future__ import annotations

import os
import pathlib
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
    """Rewrite ``store`` into one new segment holding exactly the live keys.

    Tombstones are dropped entirely (no older segment survives to shadow a
    deletion).  The new segment is written to ``<newid>.seg.tmp`` and moved
    into place with ``os.replace``; old segments are deleted only after the
    move succeeds, so a crash before the move recovers the pre-compaction
    state (the ``.tmp`` name never matches the segment pattern).
    """
    store._require_open()
    before = store.stats()
    old_paths = store._segment_paths()
    new_id = max(int(p.stem) for p in old_paths) + 1
    tmp_path = store._root / f"{new_id:06d}.seg.tmp"
    new_index, written = _write_live_records(store, tmp_path, new_id)
    store._active.close()
    os.replace(tmp_path, store._segment_path(new_id))
    removed = _remove_old_segments(old_paths)
    store._active = Segment(store._segment_path(new_id), new_id)
    store._active_tail = None
    store._index = new_index
    store._total_records = written
    after = store.stats()
    return CompactionResult(
        segments_removed=removed,
        records_written=written,
        records_dropped=before.total_records - written,
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )


def _write_live_records(
    store: KVStore, tmp_path: pathlib.Path, new_id: int
) -> tuple[Index, int]:
    index = Index()
    written = 0
    offset = 0
    with open(tmp_path, "wb") as fh:
        for key in store.keys():  # preserve keys() ordering
            value = store.get(key)
            assert value is not None  # keys() only yields live keys
            blob = encode_record(key, value)
            fh.write(blob)
            index.put(key, Location(new_id, offset), tombstone=False)
            offset += len(blob)
            written += 1
    return index, written


def _remove_old_segments(old_paths: list[pathlib.Path]) -> int:
    removed = 0
    for path in old_paths:
        path.unlink()
        removed += 1
    return removed
