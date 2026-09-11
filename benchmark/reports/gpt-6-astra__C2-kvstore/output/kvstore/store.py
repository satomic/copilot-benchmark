import os
import re
from dataclasses import dataclass
from pathlib import Path

from .index import Index, Location
from .record import _encode_key, encode_record
from .segment import Segment


@dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(
        self, root: str | os.PathLike, *, max_segment_bytes: int = 4096,
    ) -> None:
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an integer >= 16")
        self._root = Path(root)
        self._max_segment_bytes = max_segment_bytes
        self._segments: dict[int, Segment] = {}
        self._active: Segment
        self._closed = False
        self._root.mkdir(parents=True, exist_ok=True)
        self._reload()

    def _segment_path(self, seg_id: int) -> Path:
        if not 1 <= seg_id <= 999999:
            raise ValueError("six-digit segment ids are exhausted")
        return self._root / f"{seg_id:06d}.seg"

    def _reload(self) -> None:
        for segment in self._segments.values():
            segment.close()
        self._segments.clear()
        self._index = Index()
        self._total_records = 0
        try:
            self._recover()
        except BaseException:
            self.close()
            raise

    def _recover(self) -> None:
        paths = [
            path for path in self._root.iterdir()
            if re.fullmatch(r"\d{6}\.seg", path.name)
        ]
        for path in sorted(paths, key=lambda path: int(path.stem)):
            seg_id = int(path.stem)
            segment = Segment(path, seg_id)
            self._segments[seg_id] = segment
            for key, value, offset in segment.scan():
                self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                self._total_records += 1
        if not self._segments:
            self._segments[1] = Segment(self._segment_path(1), 1)
        self._active = self._segments[max(self._segments)]

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _append(self, key: str, blob: bytes, *, tombstone: bool) -> None:
        size = self._active.size
        # Preserve ignored tail bytes for stats; never append behind a partial record.
        if self._active._has_truncated_tail or (
            size > 0 and size + len(blob) > self._max_segment_bytes
        ):
            seg_id = self._active.seg_id + 1
            segment = Segment(self._segment_path(seg_id), seg_id)
            self._segments[seg_id] = segment
            self._active = segment
        offset = self._active.append(blob)
        self._index.put(key, Location(self._active.seg_id, offset), tombstone=tombstone)
        self._total_records += 1

    def set(self, key: str, value: str) -> None:
        self._check_open()
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        blob = encode_record(key, value)
        self._append(key, blob, tombstone=False)

    def get(self, key: str) -> str | None:
        self._check_open()
        _encode_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        return self._segments[loc.seg_id]._read_record(loc.offset)[1]

    def delete(self, key: str) -> bool:
        self._check_open()
        blob = encode_record(key, None)
        if self._index.get(key) is None:
            return False
        self._append(key, blob, tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        return Stats(
            live, tombstones, self._total_records,
            self._total_records - live - tombstones,
            len(self._segments), sum(segment.size for segment in self._segments.values()),
        )

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
