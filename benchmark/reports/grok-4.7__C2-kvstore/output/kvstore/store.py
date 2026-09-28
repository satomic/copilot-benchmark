"""Durable key-value store over append-only segment files."""

from __future__ import annotations

import os
import pathlib
import re
from typing import NamedTuple

from kvstore.index import Index, Location
from kvstore.record import encode_record
from kvstore.segment import Segment

# bool is an int subclass, but it is not a segment size.
_SEGMENT_NAME = re.compile(r"^(\d{6})\.seg$")


class Stats(NamedTuple):
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


def list_segments(root: pathlib.Path) -> list[tuple[int, pathlib.Path]]:
    """Return (seg_id, path) for real segment files, in ascending id order."""
    found: list[tuple[int, pathlib.Path]] = []
    if not root.is_dir():
        return found
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        match = _SEGMENT_NAME.match(entry.name)
        if match is None:
            continue
        found.append((int(match.group(1)), entry))
    found.sort(key=lambda item: item[0])
    return found


class KVStore:
    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        self._max_segment_bytes = _require_max_segment_bytes(max_segment_bytes)
        self._root = pathlib.Path(root)
        self._index = Index()
        self._values: dict[str, str] = {}
        self._total_records = 0
        self._active: Segment | None = None
        self._closed = False
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            self._open_segments()
        except Exception:
            self.close()
            raise

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        _require_key(key)
        _require_value(value)
        self._note(key, value, self._append(encode_record(key, value)))

    def get(self, key: str) -> str | None:
        self._ensure_open()
        _require_key(key)
        if self._index.get(key) is None:
            return None
        return self._values[key]

    def delete(self, key: str) -> bool:
        """Append a tombstone and return True only when key is currently live."""
        self._ensure_open()
        _require_key(key)
        if self._index.get(key) is None:
            return False
        self._note(key, None, self._append(encode_record(key, None)))
        return True

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        segments = list_segments(self._root)
        live = len(self._index)
        tombs = self._index.tombstone_count()
        total = self._total_records
        return Stats(
            live_keys=live,
            tombstones=tombs,
            total_records=total,
            dead_records=total - live - tombs,
            segment_count=len(segments),
            bytes_on_disk=self._bytes_on_disk(segments),
        )

    def close(self) -> None:
        active = self._active
        self._active = None
        self._closed = True
        if active is not None:
            active.close()

    def __enter__(self) -> KVStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _open_segments(self) -> None:
        found = list_segments(self._root)
        if not found:
            self._active = Segment(self._segment_path(1), 1)
            self._ingest(self._active)
            return
        for seg_id, path in found[:-1]:
            self._ingest_closed(path, seg_id)
        seg_id, path = found[-1]
        self._active = Segment(path, seg_id)
        self._ingest(self._active)

    def _ingest_closed(self, path: pathlib.Path, seg_id: int) -> None:
        segment = Segment(path, seg_id)
        try:
            self._ingest(segment)
        finally:
            segment.close()

    def _ingest(self, segment: Segment) -> None:
        for key, value, offset in segment.scan():
            self._note(key, value, Location(segment.seg_id, offset))

    def _note(self, key: str, value: str | None, loc: Location) -> None:
        self._index.put(key, loc, tombstone=value is None)
        if value is None:
            self._values.pop(key, None)
        else:
            self._values[key] = value
        self._total_records += 1

    def _append(self, blob: bytes) -> Location:
        active = self._require_active()
        if active.size != 0 and active.size + len(blob) > self._max_segment_bytes:
            self._roll()
            active = self._require_active()
        offset = active.append(blob)
        return Location(active.seg_id, offset)

    def _roll(self) -> None:
        active = self._require_active()
        new_id = active.seg_id + 1
        active.close()
        self._active = Segment(self._segment_path(new_id), new_id)

    def _install_compacted(
        self, final: pathlib.Path, new_id: int, old_paths: list[pathlib.Path]
    ) -> None:
        """Switch to a compacted segment after it has been moved into place."""
        self._ensure_open()
        if self._active is not None:
            self._active.close()
            self._active = None
        for path in old_paths:
            path.unlink()
        self._index = Index()
        self._values = {}
        self._total_records = 0
        self._active = Segment(final, new_id)
        self._closed = False
        self._ingest(self._active)

    def _bytes_on_disk(self, segments: list[tuple[int, pathlib.Path]]) -> int:
        total = 0
        active = self._active
        for seg_id, path in segments:
            if active is not None and seg_id == active.seg_id:
                total += active.size
            else:
                total += path.stat().st_size
        return total

    def _segment_path(self, seg_id: int) -> pathlib.Path:
        if not 0 <= seg_id <= 999999:
            raise ValueError(f"segment id {seg_id} does not fit in six digits")
        return self._root / f"{seg_id:06d}.seg"

    def _require_active(self) -> Segment:
        if self._active is None:
            raise ValueError("KVStore is closed")
        return self._active

    def _ensure_open(self) -> None:
        if self._closed or self._active is None:
            raise ValueError("KVStore is closed")


def _require_max_segment_bytes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 16:
        raise ValueError("max_segment_bytes must be an int >= 16")
    return value


def _require_key(key: object) -> None:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    length = len(key.encode("utf-8"))
    if not 1 <= length <= 65535:
        raise ValueError("key UTF-8 length must be in 1..65535")


def _require_value(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("value must be str")
