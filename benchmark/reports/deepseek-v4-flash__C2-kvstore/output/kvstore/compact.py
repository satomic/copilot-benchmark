import os
import pathlib
import typing

from kvstore.record import encode_record
from kvstore.segment import Segment
from kvstore.index import Location


class CompactionResult(typing.NamedTuple):
    segments_removed: int
    records_written: int
    records_dropped: int
    bytes_reclaimed: int


def _write_new_segment(
    store: typing.Any,
    tmp_path: pathlib.Path,
    new_id: int,
    live_keys: list[str],
) -> int:
    """Write live records to a temporary segment file. Returns count written."""
    if not live_keys:
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT, 0o666)
            os.close(fd)
            return 0
    seg = Segment(tmp_path, new_id)
    written = 0
    for key in live_keys:
            value = store.get(key)
            if value is not None:
                seg.append(encode_record(key, value))
                written += 1
    seg.close()
    return written


def _remove_old_segments(store: typing.Any) -> list[tuple[int, pathlib.Path]]:
    """Close and remove all old segments from the store. Returns list of (sid, path)."""
    old: list[tuple[int, pathlib.Path]] = []
    for sid in list(store._segments_ref.keys()):
            seg = store._segments_ref.pop(sid)
            seg.close()
            old.append((sid, store._root_path / f"{sid:06d}.seg"))
    for sid in list(store._reader_fds.keys()):
            os.close(store._reader_fds.pop(sid))
    for sid, path in old:
            try:
                os.remove(str(path))
            except FileNotFoundError:
                pass
    return old


def _rebuild_index(store: typing.Any, new_seg: Segment) -> int:
    """Rebuild the store's index from a segment. Returns total record count."""
    idx = store._index_ref.__class__()
    total = 0
    for key, value, offset in new_seg.scan():
            total += 1
            idx.put(key, Location(new_seg.seg_id, offset), tombstone=(value is None))
    store._index_ref._entries = idx._entries  # type: ignore[attr-defined]
    store._total_records_ref = total
    return total


def compact(store: typing.Any) -> CompactionResult:
    """Compact the store into one segment with one record per live key."""
    stats_before = store.stats()
    live_keys = store.keys()
    seg_ids = sorted(store._segments_ref.keys())
    new_id = max(seg_ids) + 1 if seg_ids else 1

    tmp_path = store._root_path / f"{new_id:06d}.seg.tmp"
    new_seg_path = store._root_path / f"{new_id:06d}.seg"

    records_written = _write_new_segment(store, tmp_path, new_id, live_keys)
    os.replace(str(tmp_path), str(new_seg_path))

    bytes_before = sum(seg.size for seg in store._segments_ref.values())
    old_fds = _remove_old_segments(store)

    new_seg = Segment(new_seg_path, new_id)
    store._segments_ref[new_id] = new_seg
    total_records = _rebuild_index(store, new_seg)

    return CompactionResult(
            segments_removed=len(old_fds),
            records_written=records_written,
            records_dropped=stats_before.total_records - records_written,
            bytes_reclaimed=bytes_before - new_seg.size,
    )