"""KVStore: a durable key-value store over append-only segment files."""

from __future__ import annotations

import dataclasses
import os
import pathlib

from .index import Index, Location
from .record import encode_key, encode_record
from .segment import Segment, list_segment_ids, segment_name

MIN_SEGMENT_BYTES = 16


@dataclasses.dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096) -> None:
        if (
            isinstance(max_segment_bytes, bool)
            or not isinstance(max_segment_bytes, int)
            or max_segment_bytes < MIN_SEGMENT_BYTES
        ):
            raise ValueError(
                f"max_segment_bytes must be an int >= {MIN_SEGMENT_BYTES}, got {max_segment_bytes!r}"
            )
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_segment_bytes = max_segment_bytes
        self._closed = False
        self._index = Index()
        self._segments: dict[int, Segment] = {}
        self._active_id = 1
        self._total_records = 0
        try:
            self._load()
        except BaseException:
            self._close_segments()
            raise

    # ----- recovery -------------------------------------------------------

    def _load(self) -> None:
        ids = list_segment_ids(self._root) or [1]
        for seg_id in ids:
            segment = Segment(self._root / segment_name(seg_id), seg_id)
            self._segments[seg_id] = segment
            for key, value, offset in segment.scan():
                self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                self._total_records += 1
        self._active_id = ids[-1]

    def _reload(self) -> None:
        """Discard in-memory state and rebuild it from the files on disk."""
        self._close_segments()
        self._index = Index()
        self._total_records = 0
        self._load()

    def _close_segments(self) -> None:
        for segment in self._segments.values():
            segment.close()
        self._segments = {}

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("KVStore is closed")

    # ----- writes ---------------------------------------------------------

    def _writable_segment(self, size: int) -> Segment:
        active = self._segments[self._active_id]
        if active.size != 0 and active.size + size > self._max_segment_bytes:
            self._active_id += 1
            active = Segment(self._root / segment_name(self._active_id), self._active_id)
            self._segments[self._active_id] = active
        return active

    def _append(self, key: str, value: str | None) -> None:
        blob = encode_record(key, value)
        segment = self._writable_segment(len(blob))
        offset = segment.append(blob)
        self._total_records += 1
        self._index.put(key, Location(segment.seg_id, offset), tombstone=value is None)

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        encode_key(key)
        if not isinstance(value, str):
            raise TypeError(f"value must be str, not {type(value).__name__}")
        self._append(key, value)

    def delete(self, key: str) -> bool:
        self._ensure_open()
        encode_key(key)
        if self._index.get(key) is None:
            return False
        self._append(key, None)
        return True

    # ----- reads ----------------------------------------------------------

    def get(self, key: str) -> str | None:
        self._ensure_open()
        if not isinstance(key, str):
            raise TypeError(f"key must be str, not {type(key).__name__}")
        loc = self._index.get(key)
        if loc is None:
            return None
        _, value, _ = self._segments[loc.seg_id].read_at(loc.offset)
        return value

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        return Stats(
            live_keys=live,
            tombstones=tombstones,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombstones,
            segment_count=len(self._segments),
            bytes_on_disk=sum(seg.size for seg in self._segments.values()),
        )

    # ----- lifecycle ------------------------------------------------------

    def close(self) -> None:
        if not self._closed:
            self._close_segments()
            self._closed = True

    def __enter__(self) -> KVStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
