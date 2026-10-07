import os
import re
from dataclasses import dataclass
from pathlib import Path

from .index import Index, Location
from .record import _key_bytes, encode_record
from .segment import Segment


@dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


def _segment_path(root: Path, seg_id: int) -> Path:
    if not 1 <= seg_id <= 999999:
        raise ValueError("segment id must fit six digits and start at 1")
    return root / f"{seg_id:06d}.seg"


class KVStore:
    def __init__(
        self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096
    ) -> None:
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an integer >= 16")
        self.root = Path(root)
        self.max_segment_bytes = max_segment_bytes
        self._closed = False
        self._segments: dict[int, Segment] = {}
        self._index = Index()
        self._total_records = 0
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._recover()
        except BaseException:
            self.close()
            raise

    def _recover(self) -> None:
        paths = sorted(
            (
                path for path in self.root.iterdir()
                if re.fullmatch(r"\d{6}\.seg", path.name) and path.is_file()
            ),
            key=lambda path: int(path.stem),
        )
        for path in paths:
            seg_id = int(path.stem)
            if seg_id == 0:
                raise ValueError("segment ids start at 1")
            segment = Segment(path, seg_id)
            self._segments[seg_id] = segment
            for key, value, offset in segment.scan():
                self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                self._total_records += 1
        if not self._segments:
            self._segments[1] = Segment(_segment_path(self.root, 1), 1)
        self._active = self._segments[max(self._segments)]

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _append(self, key: str, value: str | None, blob: bytes) -> None:
        size = self._active.size
        # Preserve an ignored tail for statistics; never append behind partial bytes.
        has_tail = self._active._valid_size != size
        if has_tail or (size != 0 and size + len(blob) > self.max_segment_bytes):
            seg_id = self._active.seg_id + 1
            segment = Segment(_segment_path(self.root, seg_id), seg_id)
            self._segments[seg_id] = segment
            self._active = segment
        offset = self._active.append(blob)
        self._index.put(
            key, Location(self._active.seg_id, offset), tombstone=value is None
        )
        self._total_records += 1

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        blob = encode_record(key, value)
        self._append(key, value, blob)

    def get(self, key: str) -> str | None:
        self._ensure_open()
        _key_bytes(key)
        location = self._index.get(key)
        if location is None:
            return None
        _, value, _ = self._segments[location.seg_id]._read_record(location.offset)
        return value

    def delete(self, key: str) -> bool:
        self._ensure_open()
        _key_bytes(key)
        if self._index.get(key) is None:
            return False
        self._append(key, None, encode_record(key, None))
        return True

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        return Stats(
            live, tombstones, self._total_records,
            self._total_records - live - tombstones, len(self._segments),
            sum(segment.size for segment in self._segments.values()),
        )

    def close(self) -> None:
        if not self._closed:
            for segment in self._segments.values():
                segment.close()
            self._closed = True

    def __enter__(self) -> "KVStore":
        self._ensure_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
