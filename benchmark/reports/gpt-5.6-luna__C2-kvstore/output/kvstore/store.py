import re
from dataclasses import dataclass
from pathlib import Path
from os import PathLike

from .index import Index, Location
from .record import encode_record
from .segment import Segment

_SEGMENT_NAME = re.compile(r"^(\d{6})\.seg$")


@dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(self, root: str | PathLike[str], *, max_segment_bytes: int = 4096) -> None:
        if (isinstance(max_segment_bytes, bool) or
                not isinstance(max_segment_bytes, int) or max_segment_bytes < 16):
            raise ValueError("max_segment_bytes must be an integer >= 16")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_segment_bytes = max_segment_bytes
        self.index = Index()
        self._segments: dict[int, Segment] = {}
        self._total_records = 0
        self._closed = False
        self._recover()

    def _segment_paths(self) -> list[tuple[int, Path]]:
        found = []
        for path in self.root.iterdir():
            match = _SEGMENT_NAME.fullmatch(path.name)
            if match:
                found.append((int(match.group(1)), path))
        return sorted(found)

    def _recover(self) -> None:
        paths = self._segment_paths()
        for seg_id, path in paths:
            segment = Segment(path, seg_id)
            self._segments[seg_id] = segment
            for key, value, offset in segment.scan():
                self.index.put(key, Location(seg_id, offset), tombstone=value is None)
                self._total_records += 1
        if not self._segments:
            self._create_segment(1)

    def _create_segment(self, seg_id: int) -> Segment:
        path = self.root / f"{seg_id:06d}.seg"
        segment = Segment(path, seg_id)
        self._segments[seg_id] = segment
        return segment

    @property
    def active(self) -> Segment:
        return self._segments[max(self._segments)]

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _check_key(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be str")
        size = len(key.encode("utf-8"))
        if not 1 <= size <= 65535:
            raise ValueError("key UTF-8 length must be 1..65535")

    def _append(self, key: str, value: str | None) -> Location:
        blob = encode_record(key, value)
        if self.active.size and self.active.size + len(blob) > self.max_segment_bytes:
            self._create_segment(self.active.seg_id + 1)
        offset = self.active.append(blob)
        self._total_records += 1
        loc = Location(self.active.seg_id, offset)
        self.index.put(key, loc, tombstone=value is None)
        return loc

    def set(self, key: str, value: str) -> None:
        self._check_open()
        self._check_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be str")
        self._append(key, value)

    def get(self, key: str) -> str | None:
        self._check_open()
        self._check_key(key)
        loc = self.index.get(key)
        if loc is None:
            return None
        for found_key, value, offset in self._segments[loc.seg_id].scan():
            if offset == loc.offset and found_key == key:
                return value
        return None

    def delete(self, key: str) -> bool:
        self._check_open()
        self._check_key(key)
        if self.index.get(key) is None:
            return False
        self._append(key, None)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self.index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        live = len(self.index)
        tombstones = self.index.tombstone_count()
        paths = self._segment_paths()
        total_bytes = sum(path.stat().st_size for _, path in paths)
        dead = self._total_records - live - tombstones
        return Stats(live, tombstones, self._total_records, dead, len(paths), total_bytes)

    def close(self) -> None:
        if not self._closed:
            for segment in self._segments.values():
                segment.close()
            self._closed = True

    def __enter__(self) -> "KVStore":
        self._check_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
