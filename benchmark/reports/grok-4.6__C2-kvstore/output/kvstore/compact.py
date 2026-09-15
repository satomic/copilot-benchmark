"""Rewrite live keys into a single new segment and drop tombstones."""

from __future__ import annotations

import os
from typing import NamedTuple

from kvstore.index import Index, Location
from kvstore.record import encode_record
from kvstore.segment import Segment, list_segment_ids, segment_path
from kvstore.store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def compact(store: KVStore) -> CompactionResult:
    store._ensure_open()
    before = store.stats()
    keys = store.keys()
    values = {key: store.get(key) for key in keys}
    root = store._root
    ids = list_segment_ids(root)
    new_id = (max(ids) if ids else 0) + 1
    tmp_path = root / f"{new_id:06d}.seg.tmp"
    final_path = segment_path(root, new_id)
    index, cache, written = _write_tmp(tmp_path, new_id, keys, values)
    os.replace(tmp_path, final_path)
    store._active.close()
    removed = _delete_old(root, ids, new_id)
    store._install_compacted(Segment(final_path, new_id), index, cache, written)
    after = store.stats()
    return CompactionResult(
        segments_removed=removed,
        records_written=written,
        records_dropped=before.total_records - written,
        bytes_reclaimed=before.bytes_on_disk - after.bytes_on_disk,
    )


def _write_tmp(
    tmp_path: os.PathLike[str],
    new_id: int,
    keys: list[str],
    values: dict[str, str | None],
) -> tuple[Index, dict[str, str], int]:
    index = Index()
    cache: dict[str, str] = {}
    offset = 0
    with open(tmp_path, "wb") as fh:
        for key in keys:
            value = values[key]
            assert value is not None
            blob = encode_record(key, value)
            fh.write(blob)
            index.put(key, Location(new_id, offset), tombstone=False)
            cache[key] = value
            offset += len(blob)
        fh.flush()
        os.fsync(fh.fileno())
    return index, cache, len(keys)


def _delete_old(root: os.PathLike[str], ids: list[int], keep_id: int) -> int:
    removed = 0
    for seg_id in ids:
        if seg_id == keep_id:
            continue
        os.remove(segment_path(root, seg_id))
        removed += 1
    return removed
