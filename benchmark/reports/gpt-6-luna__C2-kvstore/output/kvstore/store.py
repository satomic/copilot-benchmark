"""Persistent append-only key-value store."""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .index import Index, Location
from .record import decode_record, encode_record
from .segment import Segment

_SEGMENT_NAME = re.compile(r"^(\d{6})\.seg$")


@dataclass(frozen=True)
class Stats:
    """Snapshot of live data and physical log usage."""

    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    """A durable string-to-string store backed by append-only segments."""

    def __init__(self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096) -> None:
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an int of at least 16")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_segment_bytes = max_segment_bytes
        self.index = Index()
        self._values: dict[str, str] = {}
        self._total_records = 0
        self._closed = False
        self._active_needs_rollover = False
        segments = self._segment_paths()
        for seg_id, path in segments:
            segment = Segment(path, seg_id)
            consumed = 0
            try:
                for key, value, offset in segment.scan():
                    record_size = len(encode_record(key, value))
                    consumed = offset + record_size
                    self._record(key, value, Location(seg_id, offset))
            finally:
                segment.close()
            if path.stat().st_size != consumed and seg_id == (segments[-1][0] if segments else 0):
                # Keep crash-tail bytes for stats, but do not append behind an unreadable tail.
                self._active_needs_rollover = True
        active_id = segments[-1][0] if segments else 1
        active_path = segments[-1][1] if segments else self.root / "000001.seg"
        self._active = Segment(active_path, active_id)
        if not segments:
            self._active_needs_rollover = False

    def _segment_paths(self) -> list[tuple[int, Path]]:
        """Find valid segment filenames in ascending id order."""
        found: list[tuple[int, Path]] = []
        for path in self.root.iterdir():
            match = _SEGMENT_NAME.fullmatch(path.name)
            if match and path.is_file():
                found.append((int(match.group(1)), path))
        return sorted(found)

    def _record(self, key: str, value: str | None, loc: Location) -> None:
        """Update the index and value cache from one decoded log record."""
        self.index.put(key, loc, tombstone=value is None)
        if value is None:
            self._values.pop(key, None)
        else:
            self._values[key] = value
        self._total_records += 1

    def _ensure_open(self) -> None:
        """Reject operations after close."""
        if self._closed:
            raise ValueError("store is closed")

    def _validate_key(self, key: str) -> None:
        """Validate the public key type and encoded length."""
        if not isinstance(key, str):
            raise TypeError("key must be a string")
        if not 1 <= len(key.encode("utf-8")) <= 65535:
            raise ValueError("UTF-8 key length must be in 1..65535 bytes")

    def set(self, key: str, value: str) -> None:
        """Append a value record and make it the newest value."""
        self._ensure_open()
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be a string")
        blob = encode_record(key, value)
        self._append(key, value, blob)

    def _append(self, key: str, value: str | None, blob: bytes) -> None:
        """Append a validated record, rolling over when necessary."""
        if self._active_needs_rollover or (
            self._active.size and self._active.size + len(blob) > self.max_segment_bytes
        ):
            self._active.close()
            seg_id = self._active.seg_id + 1
            self._active = Segment(self.root / f"{seg_id:06d}.seg", seg_id)
            self._active_needs_rollover = False
        offset = self._active.append(blob)
        self._record(key, value, Location(self._active.seg_id, offset))

    def get(self, key: str) -> str | None:
        """Return a live key's value, preserving empty strings."""
        self._ensure_open()
        self._validate_key(key)
        return self._values.get(key)

    def delete(self, key: str) -> bool:
        """Append a tombstone only when the key is currently live."""
        self._ensure_open()
        self._validate_key(key)
        if self.index.get(key) is None:
            return False
        self._append(key, None, encode_record(key, None))
        return True

    def keys(self) -> list[str]:
        """Return live keys in newest-record order."""
        self._ensure_open()
        return self.index.live_keys()

    def stats(self) -> Stats:
        """Return logical record counts and physical segment usage."""
        self._ensure_open()
        paths = self._segment_paths()
        live = len(self.index)
        tombstones = self.index.tombstone_count()
        return Stats(
            live,
            tombstones,
            self._total_records,
            self._total_records - live - tombstones,
            len(paths),
            sum(path.stat().st_size for _, path in paths),
        )

    def close(self) -> None:
        """Close the active file; repeated calls are harmless."""
        if not self._closed:
            self._active.close()
            self._closed = True

    def __enter__(self) -> Self:
        """Return this open store as a context manager."""
        self._ensure_open()
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the store on context exit."""
        self.close()
