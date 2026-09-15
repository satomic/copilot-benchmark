"""Durable key-value store over append-only segment files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from kvstore.index import Index, Location
from kvstore.record import encode_record
from kvstore.segment import Segment, list_segment_ids, segment_path


@dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096) -> None:
        if not isinstance(max_segment_bytes, int) or isinstance(max_segment_bytes, bool):
            raise ValueError("max_segment_bytes must be an int")
        if max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be >= 16")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_segment_bytes = max_segment_bytes
        self._index = Index()
        self._cache: dict[str, str] = {}
        self._total_records = 0
        self._closed = False
        self._active = self._recover()

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        _validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be str")
        self._write(key, value)

    def get(self, key: str) -> str | None:
        self._ensure_open()
        _validate_key(key)
        if self._index.get(key) is None:
            return None
        return self._cache.get(key)

    def delete(self, key: str) -> bool:
        self._ensure_open()
        _validate_key(key)
        if self._index.get(key) is None:
            return False
        self._write(key, None)
        return True

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        live = len(self._index)
        tombs = self._index.tombstone_count()
        ids = list_segment_ids(self._root)
        nbytes = sum(segment_path(self._root, i).stat().st_size for i in ids)
        return Stats(live, tombs, self._total_records, self._total_records - live - tombs, len(ids), nbytes)

    def close(self) -> None:
        if not self._closed:
            self._active.close()
            self._closed = True

    def __enter__(self) -> KVStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _recover(self) -> Segment:
        ids = list_segment_ids(self._root)
        if not ids:
            return Segment(segment_path(self._root, 1), 1)
        for seg_id in ids[:-1]:
            seg = Segment(segment_path(self._root, seg_id), seg_id)
            try:
                self._ingest(seg)
            finally:
                seg.close()
        active = Segment(segment_path(self._root, ids[-1]), ids[-1])
        self._ingest(active)
        return active

    def _ingest(self, seg: Segment) -> None:
        for key, value, offset in seg.scan():
            self._total_records += 1
            self._apply(key, value, Location(seg.seg_id, offset))

    def _write(self, key: str, value: str | None) -> None:
        blob = encode_record(key, value)
        n = len(blob)
        if self._active.size != 0 and self._active.size + n > self._max_segment_bytes:
            new_id = self._active.seg_id + 1
            self._active.close()
            self._active = Segment(segment_path(self._root, new_id), new_id)
        offset = self._active.append(blob)
        self._total_records += 1
        self._apply(key, value, Location(self._active.seg_id, offset))

    def _apply(self, key: str, value: str | None, loc: Location) -> None:
        self._index.put(key, loc, tombstone=value is None)
        if value is None:
            self._cache.pop(key, None)
        else:
            self._cache[key] = value

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _install_compacted(
        self,
        active: Segment,
        index: Index,
        cache: dict[str, str],
        total_records: int,
    ) -> None:
        self._active = active
        self._index = index
        self._cache = cache
        self._total_records = total_records


def _validate_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    n = len(key.encode("utf-8"))
    if n < 1 or n > 65535:
        raise ValueError("key UTF-8 length must be in 1..65535")
