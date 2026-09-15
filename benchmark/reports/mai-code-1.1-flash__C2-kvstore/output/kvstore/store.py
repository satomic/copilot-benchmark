from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import CorruptSegmentError
from .index import Index, Location
from .record import decode_record, encode_record
from .segment import Segment

_SEG_RE = re.compile(r"^\d{6}\.seg$")


@dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        if type(max_segment_bytes) is not int or max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an int >= 16")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_segment_bytes = max_segment_bytes
        self._closed = False
        self._segments: dict[int, Segment] = {}
        self._index = Index()
        self._total_records = 0
        self._recover()

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _validate_key(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be str")
        key_bytes = key.encode("utf-8")
        if not 1 <= len(key_bytes) <= 65535:
            raise ValueError("key byte length must be 1..65535")

    def _recover(self) -> None:
        segment_paths = []
        for item in sorted(self.root.iterdir(), key=lambda p: p.name):
            if _SEG_RE.fullmatch(item.name):
                segment_paths.append(int(item.name[:6]))
        for seg_id in segment_paths:
            seg = Segment(self.root / f"{seg_id:06d}.seg", seg_id)
            self._segments[seg_id] = seg
            for key, value, offset in seg.scan():
                self._index.put(key, Location(seg_id, offset), tombstone=(value is None))
                self._total_records += 1
        if not self._segments:
            first = Segment(self.root / "000001.seg", 1)
            self._segments[1] = first
        self._active = self._segments[max(self._segments)]

    def _append_record(self, key: str, blob: bytes, *, tombstone: bool) -> None:
        active = self._active
        if active.size != 0 and active.size + len(blob) > self.max_segment_bytes:
            next_id = active.seg_id + 1
            active.close()
            new_seg = Segment(self.root / f"{next_id:06d}.seg", next_id)
            self._segments[next_id] = new_seg
            self._active = new_seg
        offset = self._active.append(blob)
        self._index.put(key, Location(self._active.seg_id, offset), tombstone=tombstone)
        self._total_records += 1

    def _read_location(self, loc: Location) -> tuple[str, str | None]:
        segment = self._segments.get(loc.seg_id)
        if segment is None:
            raise FileNotFoundError(f"segment {loc.seg_id} is missing")
        with open(segment._path, "rb") as fh:
            fh.seek(loc.offset)
            data = fh.read()
        key, value, _ = decode_record(data, 0)
        return (key, value)

    def set(self, key: str, value: str) -> None:
        self._check_open()
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be str")
        self._append_record(key, encode_record(key, value), tombstone=False)

    def get(self, key: str) -> str | None:
        self._check_open()
        self._validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        _, value = self._read_location(loc)
        return value

    def delete(self, key: str) -> bool:
        self._check_open()
        self._validate_key(key)
        if self.get(key) is None:
            return False
        self._append_record(key, encode_record(key, None), tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        live_keys = len(self._index)
        tombstones = self._index.tombstone_count()
        total_records = self._total_records
        dead_records = total_records - live_keys - tombstones
        segment_count = len(self._segments)
        bytes_on_disk = sum(
            item.stat().st_size for item in self.root.iterdir() if _SEG_RE.fullmatch(item.name)
        )
        return Stats(
            live_keys=live_keys,
            tombstones=tombstones,
            total_records=total_records,
            dead_records=dead_records,
            segment_count=segment_count,
            bytes_on_disk=bytes_on_disk,
        )

    def close(self) -> None:
        if self._closed:
            return
        for segment in self._segments.values():
            segment.close()
        self._closed = True

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
