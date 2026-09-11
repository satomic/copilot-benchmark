"""KVStore: durable key-value store built on append-only segments."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re

from .index import Index, Location
from .record import decode_record, encode_record
from .segment import Segment

_SEG_NAME_RE = re.compile(r"^(\d{6})\.seg$")


@dataclasses.dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


def _seg_path(root: pathlib.Path, seg_id: int) -> pathlib.Path:
    return root / f"{seg_id:06d}.seg"


def _discover_segment_ids(root: pathlib.Path) -> list[int]:
    ids = []
    for entry in root.iterdir():
        if entry.is_file():
            m = _SEG_NAME_RE.match(entry.name)
            if m:
                ids.append(int(m.group(1)))
    return sorted(ids)


class KVStore:
    """A durable, append-only key-value store."""

    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        if not isinstance(max_segment_bytes, int) or isinstance(max_segment_bytes, bool):
            raise ValueError("max_segment_bytes must be an int >= 16")
        if max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an int >= 16")
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_segment_bytes = max_segment_bytes
        self._index = Index()
        self._total_records = 0
        self._closed = False

        seg_ids = _discover_segment_ids(self._root)
        for seg_id in seg_ids:
            seg = Segment(_seg_path(self._root, seg_id), seg_id)
            try:
                for key, value, offset in seg.scan():
                    self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                    self._total_records += 1
            finally:
                seg.close()

        if seg_ids:
            active_id = seg_ids[-1]
        else:
            active_id = 1
        self._active = Segment(_seg_path(self._root, active_id), active_id)

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    @staticmethod
    def _validate_key(key: str) -> bytes:
        if not isinstance(key, str):
            raise TypeError("key must be a str")
        key_bytes = key.encode("utf-8")
        if not (1 <= len(key_bytes) <= 65535):
            raise ValueError("key byte length must be in 1..65535")
        return key_bytes

    def _append(self, blob: bytes) -> Location:
        n = len(blob)
        if self._active.size != 0 and self._active.size + n > self._max_segment_bytes:
            new_id = self._active.seg_id + 1
            self._active.close()
            self._active = Segment(_seg_path(self._root, new_id), new_id)
        offset = self._active.append(blob)
        return Location(self._active.seg_id, offset)

    def set(self, key: str, value: str) -> None:
        self._check_open()
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        blob = encode_record(key, value)
        loc = self._append(blob)
        self._index.put(key, loc, tombstone=False)
        self._total_records += 1

    def get(self, key: str) -> str | None:
        self._check_open()
        self._validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        seg = Segment(_seg_path(self._root, loc.seg_id), loc.seg_id)
        try:
            with open(seg.path, "rb") as fh:
                fh.seek(loc.offset)
                data = fh.read()
            _, value, _ = decode_record(data, 0)
            return value
        finally:
            seg.close()

    def delete(self, key: str) -> bool:
        self._check_open()
        self._validate_key(key)
        if self._index.get(key) is None:
            return False
        blob = encode_record(key, None)
        loc = self._append(blob)
        self._index.put(key, loc, tombstone=True)
        self._total_records += 1
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        seg_ids = _discover_segment_ids(self._root)
        bytes_on_disk = sum(_seg_path(self._root, sid).stat().st_size for sid in seg_ids)
        return Stats(
            live_keys=live,
            tombstones=tombstones,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombstones,
            segment_count=len(seg_ids),
            bytes_on_disk=bytes_on_disk,
        )

    def close(self) -> None:
        if not self._closed:
            self._active.close()
            self._closed = True

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
