import os
import re
from dataclasses import dataclass
from pathlib import Path

from .index import Index, Location
from .record import decode_record, encode_record
from .segment import Segment


_SEGMENT_RE = re.compile(r"^(\d{6})\.seg$")


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
        self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096
    ) -> None:
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an int of at least 16")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_segment_bytes = max_segment_bytes
        self._index = Index()
        self._total_records = 0
        self._closed = False
        self._tail_is_truncated = False
        paths = self._segment_paths()
        if not paths:
            paths = [(1, self.root / "000001.seg")]
        self._recover(paths)

    def _segment_paths(self) -> list[tuple[int, Path]]:
        paths: list[tuple[int, Path]] = []
        for path in self.root.iterdir():
            match = _SEGMENT_RE.fullmatch(path.name)
            if match and path.is_file():
                paths.append((int(match.group(1)), path))
        return sorted(paths)

    def _recover(self, paths: list[tuple[int, Path]]) -> None:
        for seg_id, path in paths:
            segment = Segment(path, seg_id)
            valid_end = 0
            try:
                for key, value, offset in segment.scan():
                    self._index.put(
                        key, Location(seg_id, offset), tombstone=value is None
                    )
                    valid_end = offset + len(encode_record(key, value))
                    self._total_records += 1
            finally:
                segment.close()
            if seg_id == paths[-1][0]:
                self._tail_is_truncated = valid_end < path.stat().st_size
        active_id, active_path = paths[-1]
        self._active = Segment(active_path, active_id)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _rollover(self) -> None:
        new_id = self._active.seg_id + 1
        self._active.close()
        self._active = Segment(self.root / f"{new_id:06d}.seg", new_id)
        self._tail_is_truncated = False

    def _append(self, blob: bytes) -> Location:
        if self._tail_is_truncated:
            self._rollover()
        elif self._active.size and (
            self._active.size + len(blob) > self.max_segment_bytes
        ):
            self._rollover()
        offset = self._active.append(blob)
        self._total_records += 1
        return Location(self._active.seg_id, offset)

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        blob = encode_record(key, value)
        loc = self._append(blob)
        self._index.put(key, loc, tombstone=False)

    def get(self, key: str) -> str | None:
        self._ensure_open()
        key_blob = encode_record(key, None)
        del key_blob
        loc = self._index.get(key)
        if loc is None:
            return None
        data = (self.root / f"{loc.seg_id:06d}.seg").read_bytes()
        found_key, value, _ = decode_record(data, loc.offset)
        if found_key != key:
            raise RuntimeError("index points to a different key")
        return value

    def delete(self, key: str) -> bool:
        self._ensure_open()
        blob = encode_record(key, None)
        if self._index.get(key) is None:
            return False
        loc = self._append(blob)
        self._index.put(key, loc, tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        paths = self._segment_paths()
        live_keys = len(self._index)
        tombstones = self._index.tombstone_count()
        return Stats(
            live_keys,
            tombstones,
            self._total_records,
            self._total_records - live_keys - tombstones,
            len(paths),
            sum(path.stat().st_size for _, path in paths),
        )

    def close(self) -> None:
        if not self._closed:
            self._active.close()
            self._closed = True

    def __enter__(self) -> "KVStore":
        self._ensure_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _install_compaction(
        self, new_id: int, entries: list[tuple[str, int]], records: int
    ) -> None:
        self._index = Index()
        for key, offset in entries:
            self._index.put(key, Location(new_id, offset), tombstone=False)
        self._active = Segment(self.root / f"{new_id:06d}.seg", new_id)
        self._total_records = records
        self._tail_is_truncated = False
