"""KVStore: a durable key-value store on append-only segments."""

from __future__ import annotations

import dataclasses
import os
import pathlib

from .index import Index, Location
from .record import encode_key, encode_record
from .segment import Segment, segment_ids, segment_path


@dataclasses.dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        if (
            not isinstance(max_segment_bytes, int)
            or isinstance(max_segment_bytes, bool)
            or max_segment_bytes < 16
        ):
            raise ValueError("max_segment_bytes must be an int >= 16")
        self._root = pathlib.Path(root)
        self._max = max_segment_bytes
        self._closed = False
        self._segments: dict[int, Segment] = {}
        self._index = Index()
        self._total_records = 0
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            self._recover()
        except BaseException:
            self._close_segments()
            raise

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def _recover(self) -> None:
        for seg_id in segment_ids(self._root):
            seg = Segment(segment_path(self._root, seg_id), seg_id)
            self._segments[seg_id] = seg
            for key, value, offset in seg.scan():
                self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                self._total_records += 1
        if not self._segments:
            self._segments[1] = Segment(segment_path(self._root, 1), 1)
        self._active = self._segments[max(self._segments)]

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _append(self, key: str, value: str | None) -> None:
        blob = encode_record(key, value)
        # A partial record left by a crash must go before new bytes follow it.
        self._active.discard_tail()
        active = self._active
        if active.size > 0 and active.size + len(blob) > self._max:
            new_id = active.seg_id + 1
            active = Segment(segment_path(self._root, new_id), new_id)
            self._segments[new_id] = active
            self._active.close()
            self._active = active
        offset = active.append(blob)
        self._index.put(key, Location(active.seg_id, offset), tombstone=value is None)
        self._total_records += 1

    def set(self, key: str, value: str) -> None:
        self._check_open()
        encode_key(key)
        if not isinstance(value, str):
            raise TypeError(f"value must be str, not {type(value).__name__}")
        self._append(key, value)

    def get(self, key: str) -> str | None:
        self._check_open()
        encode_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        _, value, _ = self._segments[loc.seg_id].read_at(loc.offset)
        return value

    def delete(self, key: str) -> bool:
        self._check_open()
        encode_key(key)
        if self._index.get(key) is None:
            return False
        self._append(key, None)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        ids = segment_ids(self._root)
        size = sum(segment_path(self._root, i).stat().st_size for i in ids)
        live = len(self._index)
        tombs = self._index.tombstone_count()
        return Stats(
            live_keys=live,
            tombstones=tombs,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombs,
            segment_count=len(ids),
            bytes_on_disk=size,
        )

    def _install_compacted(self, seg_id: int, entries: list[tuple[str, int]]) -> int:
        """Swap in compacted segment ``seg_id``; delete older segment files.

        ``entries`` lists ``(key, offset)`` pairs of the new segment. Returns the
        number of old segment files removed.
        """
        self._close_segments()
        removed = 0
        for old_id in segment_ids(self._root):
            if old_id != seg_id:
                segment_path(self._root, old_id).unlink()
                removed += 1
        seg = Segment(segment_path(self._root, seg_id), seg_id)
        self._segments = {seg_id: seg}
        self._active = seg
        self._index = Index()
        for key, offset in entries:
            self._index.put(key, Location(seg_id, offset), tombstone=False)
        self._total_records = len(entries)
        return removed

    def _close_segments(self) -> None:
        for seg in self._segments.values():
            seg.close()

    def close(self) -> None:
        if not self._closed:
            self._close_segments()
            self._closed = True

    def __enter__(self) -> "KVStore":
        self._check_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
