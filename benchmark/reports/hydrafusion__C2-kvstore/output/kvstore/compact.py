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


def _write_temp(
    path: Path, records: list[tuple[str, str]]
) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    offset = 0
    with path.open("wb") as file:
        for key, value in records:
            blob = encode_record(key, value)
            file.write(blob)
            entries.append((key, offset))
            offset += len(blob)
        file.flush()
        os.fsync(file.fileno())
    return entries


def compact(store: KVStore) -> CompactionResult:
    store._ensure_open()
    before = store.stats()
    old_paths = [path for _, path in store._segment_paths()]
    old_ids = [int(path.stem) for path in old_paths]
    new_id = max(old_ids) + 1
    records = [(key, store.get(key)) for key in store.keys()]
    live_records = [(key, value) for key, value in records if value is not None]
    final_path = store.root / f"{new_id:06d}.seg"
    temp_path = store.root / f"{new_id:06d}.seg.tmp"
    entries = _write_temp(temp_path, live_records)
    store._active.close()
    try:
        os.replace(temp_path, final_path)
        for path in old_paths:
            path.unlink()
    except Exception:
        if final_path.exists():
            store._active = store._active.__class__(final_path, new_id)
        else:
            active_path = old_paths[-1]
            store._active = store._active.__class__(active_path, int(active_path.stem))
        raise
    store._install_compaction(new_id, entries, len(live_records))
    after = store.stats()
    return CompactionResult(
        len(old_paths),
        len(live_records),
        before.total_records - len(live_records),
        before.bytes_on_disk - after.bytes_on_disk,
    )
