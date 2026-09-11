"""The store itself: recovery, reads, writes and rollover."""

from __future__ import annotations

import dataclasses
import os
import pathlib

from .index import Index, Location
from .record import MAX_KEY_BYTES, decode_record, encode_record
from .segment import SEGMENT_RE, Segment, segment_name

__all__ = ["Stats", "KVStore", "MIN_SEGMENT_BYTES"]

MIN_SEGMENT_BYTES = 16


@dataclasses.dataclass(frozen=True)
class Stats:
    """A snapshot of the store's shape. Field order matches the CLI output."""

    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    """A key-value store over append-only segment files."""

    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        if isinstance(max_segment_bytes, bool) or not isinstance(max_segment_bytes, int):
            raise ValueError("max_segment_bytes must be an int")
        if max_segment_bytes < MIN_SEGMENT_BYTES:
            raise ValueError(f"max_segment_bytes must be >= {MIN_SEGMENT_BYTES}")
        self._root = pathlib.Path(root)
        self._max_segment_bytes = max_segment_bytes
        self._root.mkdir(parents=True, exist_ok=True)
        self._index = Index()
        self._closed = False
        self._total_records = 0
        self._active = self._recover()

    # -- recovery ---------------------------------------------------------------

    def segment_ids(self) -> list[int]:
        """Ids of the segment files present, ascending. Other names are ignored."""
        ids = [
            int(p.name[:6])
            for p in self._root.iterdir()
            if p.is_file() and SEGMENT_RE.match(p.name)
        ]
        return sorted(ids)

    def _recover(self) -> Segment:
        ids = self.segment_ids()
        if not ids:
            return Segment(self._root / segment_name(1), 1)
        for seg_id in ids:
            seg = Segment(self._root / segment_name(seg_id), seg_id)
            for key, value, offset in seg.scan():
                self._index.put(
                    key, Location(seg_id, offset), tombstone=value is None
                )
                self._total_records += 1
        return Segment(self._root / segment_name(ids[-1]), ids[-1])

    # -- helpers ----------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("operation on a closed KVStore")

    @staticmethod
    def _check_key(key: object) -> str:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, not {type(key).__name__}")
        size = len(key.encode("utf-8"))
        if not 1 <= size <= MAX_KEY_BYTES:
            raise ValueError(f"key must encode to 1..{MAX_KEY_BYTES} bytes, got {size}")
        return key

    def _append(self, blob: bytes) -> Location:
        """Append a record, rolling to a new segment first when it will not fit."""
        size = self._active.size
        if size > 0 and size + len(blob) > self._max_segment_bytes:
            self._active.close()
            new_id = self._active.seg_id + 1
            self._active = Segment(self._root / segment_name(new_id), new_id)
        offset = self._active.append(blob)
        self._total_records += 1
        return Location(self._active.seg_id, offset)

    # -- public API -------------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        self._check_open()
        self._check_key(key)
        if not isinstance(value, str):
            raise TypeError(f"value must be str, not {type(value).__name__}")
        loc = self._append(encode_record(key, value))
        self._index.put(key, loc, tombstone=False)

    def get(self, key: str) -> str | None:
        self._check_open()
        self._check_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        path = self._root / segment_name(loc.seg_id)
        with path.open("rb") as handle:
            handle.seek(loc.offset)
            _, value, _ = decode_record(handle.read())
        return value

    def delete(self, key: str) -> bool:
        self._check_open()
        self._check_key(key)
        if self._index.get(key) is None:
            return False
        loc = self._append(encode_record(key, None))
        self._index.put(key, loc, tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._check_open()
        ids = self.segment_ids()
        live = len(self._index)
        tombs = self._index.tombstone_count()
        return Stats(
            live_keys=live,
            tombstones=tombs,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombs,
            segment_count=len(ids),
            bytes_on_disk=sum(
                (self._root / segment_name(i)).stat().st_size for i in ids
            ),
        )

    def close(self) -> None:
        if not self._closed:
            self._active.close()
            self._closed = True

    def __enter__(self) -> "KVStore":
        self._check_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals used by compaction ------------------------------------------

    @property
    def root(self) -> pathlib.Path:
        return self._root

    @property
    def max_segment_bytes(self) -> int:
        return self._max_segment_bytes

    @property
    def active(self) -> Segment:
        return self._active

    @property
    def index(self) -> Index:
        return self._index

    @property
    def total_records(self) -> int:
        return self._total_records

    def _adopt(self, active: Segment, index: Index, total_records: int) -> None:
        """Replace the store's state after compaction has rewritten the files."""
        self._active = active
        self._index = index
        self._total_records = total_records
