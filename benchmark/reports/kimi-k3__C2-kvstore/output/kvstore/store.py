"""KVStore: a durable key-value store over append-only segment files."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re

from .index import Index, Location
from .record import decode_record, encode_record
from .segment import Segment

_SEGMENT_NAME = re.compile(r"^\d{6}\.seg$")
MIN_SEGMENT_BYTES = 16
_HEADER_SIZE = 15


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
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < MIN_SEGMENT_BYTES:
            raise ValueError("max_segment_bytes must be an int >= 16")
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_segment_bytes = max_segment_bytes
        self._index = Index()
        self._total_records = 0
        self._closed = False
        self._active: Segment
        # Logical end of the active segment when it has a truncated tail,
        # else None.  See _append_record.
        self._active_tail: int | None = None
        self._recover()

    # -- public API ------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        self._require_open()
        _validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be str")
        loc = self._append_record(encode_record(key, value))
        self._index.put(key, loc, tombstone=False)

    def get(self, key: str) -> str | None:
        self._require_open()
        _validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        return self._read_value(loc)

    def delete(self, key: str) -> bool:
        self._require_open()
        _validate_key(key)
        if self._index.get(key) is None:
            return False  # no-op delete writes nothing
        loc = self._append_record(encode_record(key, None))
        self._index.put(key, loc, tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._require_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._require_open()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        paths = self._segment_paths()
        return Stats(
            live_keys=live,
            tombstones=tombstones,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombstones,
            segment_count=len(paths),
            bytes_on_disk=sum(p.stat().st_size for p in paths),
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._active.close()

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- recovery --------------------------------------------------------

    def _recover(self) -> None:
        paths = self._segment_paths()
        if not paths:
            self._active = Segment(self._segment_path(1), 1)
            return
        last_id = int(paths[-1].stem)
        for path in paths:
            seg_id = int(path.stem)
            segment = Segment(path, seg_id)
            end = self._load_segment(segment)
            if seg_id == last_id:
                self._active = segment
                if end < segment.size:
                    # Truncated tail from a crashed write.  The bytes stay on
                    # disk (stats() counts bytes really on disk) until the
                    # next append overwrites them; see _append_record.
                    self._active_tail = end
            else:
                segment.close()

    def _load_segment(self, segment: Segment) -> int:
        """Feed every record into the index; returns the logical end offset."""
        end = 0
        for key, value, offset in segment.scan():
            self._index.put(
                key, Location(segment.seg_id, offset), tombstone=value is None
            )
            self._total_records += 1
            end = offset + _record_size(key, value)
        return end

    # -- appending ---------------------------------------------------------

    def _append_record(self, blob: bytes) -> Location:
        if self._active_tail is not None:
            # Overwrite the ignored truncated tail so that new records stay
            # reachable by scan() (which stops at a partial record).
            os.truncate(self._segment_path(self._active.seg_id), self._active_tail)
            self._active_tail = None
        size = self._active.size
        if size > 0 and size + len(blob) > self._max_segment_bytes:
            new_id = self._active.seg_id + 1
            self._active.close()
            self._active = Segment(self._segment_path(new_id), new_id)
        offset = self._active.append(blob)
        self._total_records += 1
        return Location(self._active.seg_id, offset)

    # -- helpers -----------------------------------------------------------

    def _read_value(self, loc: Location) -> str:
        with open(self._segment_path(loc.seg_id), "rb") as fh:
            buf = fh.read()
        _key, value, _size = decode_record(buf, loc.offset)
        assert value is not None  # the index only returns live locations
        return value

    def _segment_paths(self) -> list[pathlib.Path]:
        return sorted(
            (p for p in self._root.iterdir() if _SEGMENT_NAME.match(p.name)),
            key=lambda p: int(p.stem),
        )

    def _segment_path(self, seg_id: int) -> pathlib.Path:
        return self._root / f"{seg_id:06d}.seg"

    def _require_open(self) -> None:
        if self._closed:
            raise ValueError("KVStore is closed")


def _validate_key(key: str) -> None:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    n = len(key.encode("utf-8"))
    if not 1 <= n <= 65535:
        raise ValueError(f"key must encode to 1..65535 bytes, got {n}")


def _record_size(key: str, value: str | None) -> int:
    n = _HEADER_SIZE + len(key.encode("utf-8"))
    if value is not None:
        n += len(value.encode("utf-8"))
    return n
