"""Compaction: rewrite the whole store into a single new segment."""

from __future__ import annotations

import os
from typing import NamedTuple

from .record import encode_record
from .segment import segment_filename
from .store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    before = store.stats()
    old_ids = store.segment_ids()
    new_id = (max(old_ids) if old_ids else 0) + 1
    final_path = store.segment_path(new_id)
    tmp_path = store.root / (segment_filename(new_id) + ".tmp")

    written = 0
    with open(tmp_path, "wb") as fh:
        for key, value in store.items():
            fh.write(encode_record(key, value))
            written += 1
        fh.flush()
        os.fsync(fh.fileno())

    # Close the active handle before touching files: Windows refuses to delete open files.
    store.active_segment.close()
    os.replace(tmp_path, final_path)

    removed = 0
    for seg_id in old_ids:
        os.remove(store.segment_path(seg_id))
        removed += 1

    store.reset_after_compaction(new_id, written)
    after = store.stats()
    return CompactionResult(
        segments_removed=removed,
        records_written=written,
        records_dropped=before.total_records - written,
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
