"""Whole-store compaction."""

from __future__ import annotations

import os
import pathlib
from typing import NamedTuple

from .record import encode_record
from .segment import segment_ids, segment_path
from .store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def _write_temp(tmp: pathlib.Path, pairs: list[tuple[str, str]]) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    offset = 0
    with open(tmp, "wb") as fh:
        for key, value in pairs:
            blob = encode_record(key, value)
            fh.write(blob)
            entries.append((key, offset))
            offset += len(blob)
        fh.flush()
        os.fsync(fh.fileno())
    return entries


def compact(store: KVStore) -> CompactionResult:
    """Rewrite every live key into one new segment and delete the old ones."""
    before = store.stats()
    pairs: list[tuple[str, str]] = []
    for key in store.keys():
        value = store.get(key)
        assert value is not None
        pairs.append((key, value))
    root = store.root
    new_id = max(segment_ids(root), default=0) + 1
    final = segment_path(root, new_id)
    tmp = final.with_name(final.name + ".tmp")
    try:
        entries = _write_temp(tmp, pairs)
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    # A crash between here and the deletions leaves old segments that recovery
    # replays first; the new segment (highest id) then wins for every live key.
    removed = store._install_compacted(new_id, entries)
    after = store.stats()
    return CompactionResult(
        segments_removed=removed,
        records_written=len(entries),
        records_dropped=before.total_records - len(entries),
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )
