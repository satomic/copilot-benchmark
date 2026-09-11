import os
from pathlib import Path
from typing import NamedTuple

from .record import encode_record
from .store import KVStore


class CompactionResult(NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def _write_compacted(store: KVStore, path: Path) -> int:
    keys = store.keys()
    with path.open("wb") as output:
        for key in keys:
            value = store.get(key)
            if value is None:
                raise RuntimeError("live key disappeared during compaction")
            output.write(encode_record(key, value))
        output.flush()
        os.fsync(output.fileno())
    return len(keys)


def compact(store: KVStore) -> CompactionResult:
    store._check_open()
    before = store.stats()
    old_segments = sorted(store._segments.items())
    new_id = old_segments[-1][0] + 1
    destination = store._segment_path(new_id)
    temporary = destination.with_suffix(".seg.tmp")
    written = _write_compacted(store, temporary)
    os.replace(temporary, destination)
    removed = 0
    try:
        # Delete oldest first so a crash cannot leave values without their tombstones.
        for seg_id, segment in old_segments:
            segment.close()
            store._segment_path(seg_id).unlink()
            removed += 1
    finally:
        # Also restore a usable store if deleting an old segment fails.
        store._reload()
    after = store.stats()
    return CompactionResult(
        removed, written, before.total_records - written,
        before.bytes_on_disk - after.bytes_on_disk,
    )
