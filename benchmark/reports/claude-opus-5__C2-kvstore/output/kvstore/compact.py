"""Compaction: rewrite every live key into a single fresh segment."""

from __future__ import annotations

import os
from typing import NamedTuple

from .record import encode_record
from .segment import segment_name
from .store import KVStore

__all__ = ["CompactionResult", "compact"]


class CompactionResult(NamedTuple):
    """What a compaction did."""

    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    """Rewrite ``store`` into one segment with exactly one record per live key."""
    before = store.stats()
    old_segments = store.segment_files()
    new_id = max((seg_id for seg_id, _path in old_segments), default=0) + 1
    root = store.root
    # The temporary name deliberately does not match ^\d{6}\.seg$, so a crash
    # before os.replace leaves the pre-compaction store intact.
    tmp_path = root / (segment_name(new_id) + ".tmp")
    keys = store.keys()
    records_written = 0
    with open(tmp_path, "wb") as fh:
        for key in keys:
            value = store.get(key)
            if value is None:
                continue
            fh.write(encode_record(key, value))
            records_written += 1
        fh.flush()
        os.fsync(fh.fileno())
    store.close()
    os.replace(tmp_path, root / segment_name(new_id))
    segments_removed = 0
    for _seg_id, path in old_segments:
        os.unlink(path)
        segments_removed += 1
    store._reopen()
    after = store.stats()
    return CompactionResult(
        segments_removed=segments_removed,
        records_written=records_written,
        records_dropped=before.total_records - records_written,
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
