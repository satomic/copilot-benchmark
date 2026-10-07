"""The KVStore."""
from __future__ import annotations

import os
import pathlib
import re
from typing import NamedTuple

from .index import Index, Location
from .record import MAX_KEY_LEN, encode_record
from .segment import Segment

SEGMENT_RE = re.compile(r"^\d{6}\.seg$")


class Stats(NamedTuple):
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


def segment_name(seg_id: int) -> str:
    return f"{seg_id:06d}.seg"


def _check_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    if not 1 <= len(key.encode("utf-8")) <= MAX_KEY_LEN:
        raise ValueError("key must be 1..65535 bytes when UTF-8 encoded")


class KVStore:
    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        if (not isinstance(max_segment_bytes, int) or isinstance(max_segment_bytes, bool)
                or max_segment_bytes < 16):
            raise ValueError("max_segment_bytes must be an int >= 16")
        self._max = max_segment_bytes
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index = Index()
        self._segments: dict[int, Segment] = {}
        self._total = 0
        self._closed = False
        self._recover()

    def _recover(self) -> None:
        ids = sorted(int(p.name[:6]) for p in self._root.iterdir()
                     if SEGMENT_RE.match(p.name) and p.is_file())
        try:
            for seg_id in ids:
                seg = Segment(self._root / segment_name(seg_id), seg_id)
                self._segments[seg_id] = seg
                for key, value, offset in seg.scan():
                    self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                    self._total += 1
        except BaseException:
            self._close_segments()
            raise
        if not ids:
            self._segments[1] = Segment(self._root / segment_name(1), 1)

    def _close_segments(self) -> None:
        for seg in self._segments.values():
            seg.close()

    @property
    def root(self) -> pathlib.Path:
        return self._root

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _active(self) -> Segment:
        return self._segments[max(self._segments)]

    def _write(self, key: str, value: str | None) -> None:
        blob = encode_record(key, value)
        active = self._active()
        if active.size > 0 and active.size + len(blob) > self._max:
            active = Segment(self._root / segment_name(active.seg_id + 1), active.seg_id + 1)
            self._segments[active.seg_id] = active
        offset = active.append(blob)
        self._index.put(key, Location(active.seg_id, offset), tombstone=value is None)
        self._total += 1

    def set(self, key: str, value: str) -> None:
        self._check_open()
        _check_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be str")
        value.encode("utf-8")
        self._write(key, value)

    def get(self, key: str) -> str | None:
        self._check_open()
        _check_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        return self._segments[loc.seg_id].read_record(loc.offset)[1]

    def delete(self, key: str) -> bool:
        self._check_open()
        _check_key(key)
        if self._index.get(key) is None:
            return False
        self._write(key, None)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        live = len(self._index)
        tombs = self._index.tombstone_count()
        size = sum(seg.size for seg in self._segments.values())
        return Stats(live, tombs, self._total, self._total - live - tombs,
                     len(self._segments), size)

    def close(self) -> None:
        if not self._closed:
            self._close_segments()
            self._closed = True

    def __enter__(self) -> "KVStore":
        self._check_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
