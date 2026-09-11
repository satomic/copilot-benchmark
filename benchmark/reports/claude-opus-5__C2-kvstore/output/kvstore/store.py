"""The key-value store itself."""

from __future__ import annotations

import dataclasses
import os
import pathlib

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .index import Index, Location
from .record import MAX_KEY_BYTES, decode_record, encode_record
from .segment import SEGMENT_PATTERN, Segment, segment_name

__all__ = ["Stats", "KVStore"]


@dataclasses.dataclass(frozen=True)
class Stats:
    """A snapshot of the store's shape."""

    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    """A durable store of ``str`` keys and ``str`` values on append-only segments."""

    def __init__(
        self, root: str | os.PathLike, *, max_segment_bytes: int = 4096
    ) -> None:
        if not isinstance(max_segment_bytes, int) or isinstance(
            max_segment_bytes, bool
        ):
            raise ValueError("max_segment_bytes must be an int")
        if max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be >= 16")
        self._root = pathlib.Path(root)
        self._max_segment_bytes = max_segment_bytes
        self._root.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._index = Index()
        self._total_records = 0
        self._active: Segment | None = None
        self._pending_truncate: int | None = None
        self._reload()

    @property
    def root(self) -> pathlib.Path:
        """Directory holding the segment files."""
        return self._root

    @property
    def max_segment_bytes(self) -> int:
        """Soft size limit that triggers segment rollover."""
        return self._max_segment_bytes

    def segment_files(self) -> list[tuple[int, pathlib.Path]]:
        """Every ``<id>.seg`` in the root, ascending by id. Other names are ignored."""
        found: list[tuple[int, pathlib.Path]] = []
        for entry in self._root.iterdir():
            if entry.is_file() and SEGMENT_PATTERN.match(entry.name):
                found.append((int(entry.name[:6]), entry))
        found.sort()
        return found

    def _reload(self) -> None:
        """Rebuild the index from disk and open the highest-id segment."""
        if self._active is not None:
            self._active.close()
            self._active = None
        self._index = Index()
        self._total_records = 0
        segments = self.segment_files()
        valid_end = 0
        for seg_id, path in segments:
            segment = Segment(path, seg_id)
            valid_end = 0
            try:
                for key, value, offset in segment.scan():
                    self._index.put(
                        key, Location(seg_id, offset), tombstone=value is None
                    )
                    self._total_records += 1
                    valid_end = offset + len(encode_record(key, value))
            finally:
                segment.close()
        active_id = segments[-1][0] if segments else 1
        self._active = Segment(self._root / segment_name(active_id), active_id)
        # A partial write at the end of the active segment stays on disk (stats
        # must report it) but is truncated away before the next append.
        self._pending_truncate: int | None = (
            valid_end if valid_end != self._active.size else None
        )

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _reopen(self) -> None:
        """Re-run recovery on a store whose files changed underneath it."""
        self._closed = False
        self._reload()

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, got {type(key).__name__}")
        n = len(key.encode("utf-8"))
        if not 1 <= n <= MAX_KEY_BYTES:
            raise ValueError(f"key must encode to 1..{MAX_KEY_BYTES} bytes, got {n}")

    def _append(self, blob: bytes) -> Location:
        """Append ``blob``, rolling over to a fresh segment when needed."""
        assert self._active is not None
        active = self._active
        if self._pending_truncate is not None:
            active.truncate(self._pending_truncate)
            self._pending_truncate = None
        if active.size != 0 and active.size + len(blob) > self._max_segment_bytes:
            new_id = active.seg_id + 1
            active.close()
            active = Segment(self._root / segment_name(new_id), new_id)
            self._active = active
        offset = active.append(blob)
        self._total_records += 1
        return Location(active.seg_id, offset)

    def set(self, key: str, value: str) -> None:
        """Store ``value`` under ``key``."""
        self._check_open()
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError(f"value must be str, got {type(value).__name__}")
        loc = self._append(encode_record(key, value))
        self._index.put(key, loc, tombstone=False)

    def get(self, key: str) -> str | None:
        """Return the stored value, or ``None`` when absent or deleted."""
        self._check_open()
        self._validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        return self._read_value(loc)

    def _read_value(self, loc: Location) -> str | None:
        path = self._root / segment_name(loc.seg_id)
        with open(path, "rb") as fh:
            fh.seek(loc.offset)
            buf = fh.read()
        try:
            _key, value, _size = decode_record(buf, 0)
        except (IncompleteRecordError, CorruptRecordError) as exc:
            raise CorruptSegmentError(path, loc.offset, str(exc)) from exc
        return value

    def delete(self, key: str) -> bool:
        """Delete a live key. Returns ``False`` and writes nothing otherwise."""
        self._check_open()
        self._validate_key(key)
        if self._index.get(key) is None:
            return False
        loc = self._append(encode_record(key, None))
        self._index.put(key, loc, tombstone=True)
        return True

    def keys(self) -> list[str]:
        """Live keys in newest-record position order."""
        self._check_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        """Report counts and on-disk size."""
        self._check_open()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        files = self.segment_files()
        return Stats(
            live_keys=live,
            tombstones=tombstones,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombstones,
            segment_count=len(files),
            bytes_on_disk=sum(path.stat().st_size for _seg_id, path in files),
        )

    def close(self) -> None:
        """Close the active segment. Idempotent."""
        if self._active is not None:
            self._active.close()
            self._active = None
        self._closed = True

    def __enter__(self) -> "KVStore":
        self._check_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
