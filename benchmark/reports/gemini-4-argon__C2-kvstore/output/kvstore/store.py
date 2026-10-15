from __future__ import annotations

import dataclasses
import os
import pathlib
import re

from .index import Index, Location
from .record import encode_record, validate_key
from .segment import Segment

SEGMENT_PATTERN = re.compile(r"^(\d{6})\.seg$")


@dataclasses.dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(
        self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096
    ) -> None:
        if (
            isinstance(max_segment_bytes, bool)
            or not isinstance(max_segment_bytes, int)
            or max_segment_bytes < 16
        ):
            raise ValueError("max_segment_bytes must be an integer >= 16")
        self._root: pathlib.Path = pathlib.Path(root)
        self._max_segment_bytes: int = max_segment_bytes
        self._index: Index = Index()
        self._segments: dict[int, Segment] = {}
        self._active: Segment | None = None
        self._total_records: int = 0
        self._closed: bool = False

        self._root.mkdir(parents=True, exist_ok=True)
        self._recover()

    def _discover_segment_paths(self) -> list[tuple[int, pathlib.Path]]:
        found: list[tuple[int, pathlib.Path]] = []
        for entry in self._root.iterdir():
            if not entry.is_file():
                continue
            match = SEGMENT_PATTERN.match(entry.name)
            if match is not None:
                seg_id = int(match.group(1))
                if seg_id >= 1:
                    found.append((seg_id, entry))
        found.sort(key=lambda item: item[0])
        return found

    def _recover(self) -> None:
        discovered = self._discover_segment_paths()
        try:
            for seg_id, path in discovered:
                seg = Segment(path, seg_id)
                self._segments[seg_id] = seg
                for key, value, offset in seg.scan():
                    self._index.put(
                        key,
                        Location(seg_id=seg_id, offset=offset),
                        tombstone=(value is None),
                    )
                    self._total_records += 1
        except Exception:
            for seg in self._segments.values():
                seg.close()
            self._segments.clear()
            raise

        if not self._segments:
            first_seg = Segment(self._segment_path(1), 1)
            self._segments[1] = first_seg
            self._active = first_seg
        else:
            max_id = max(self._segments)
            self._active = self._segments[max_id]

    def _segment_path(self, seg_id: int) -> pathlib.Path:
        return self._root / f"{seg_id:06d}.seg"

    def _ensure_open(self) -> Segment:
        if self._closed or self._active is None:
            raise ValueError("KVStore is closed")
        return self._active

    def _append_record(self, blob: bytes) -> tuple[int, int]:
        active = self._ensure_open()
        if active.size > 0 and active.size + len(blob) > self._max_segment_bytes:
            new_id = active.seg_id + 1
            active = Segment(self._segment_path(new_id), new_id)
            self._segments[new_id] = active
            self._active = active
        offset = active.append(blob)
        self._total_records += 1
        return active.seg_id, offset

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        blob = encode_record(key, value)
        seg_id, offset = self._append_record(blob)
        self._index.put(key, Location(seg_id=seg_id, offset=offset), tombstone=False)

    def get(self, key: str) -> str | None:
        self._ensure_open()
        validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        seg = self._segments[loc.seg_id]
        _, value, _ = seg.read_at(loc.offset)
        return value

    def delete(self, key: str) -> bool:
        self._ensure_open()
        validate_key(key)
        if self._index.get(key) is None:
            return False
        blob = encode_record(key, None)
        seg_id, offset = self._append_record(blob)
        self._index.put(key, Location(seg_id=seg_id, offset=offset), tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        live_keys = len(self._index)
        tombstones = self._index.tombstone_count()
        total_records = self._total_records
        dead_records = total_records - live_keys - tombstones
        segment_count = len(self._segments)
        bytes_on_disk = sum(seg.size for seg in self._segments.values())
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
        for seg in self._segments.values():
            seg.close()
        self._active = None
        self._closed = True

    def __enter__(self) -> KVStore:
        self._ensure_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
