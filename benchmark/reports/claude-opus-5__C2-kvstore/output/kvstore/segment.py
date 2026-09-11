"""One append-only segment file."""

from __future__ import annotations

import pathlib
import re
from typing import Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record

SEGMENT_PATTERN: re.Pattern[str] = re.compile(r"^\d{6}\.seg$")

__all__ = ["Segment", "SEGMENT_PATTERN", "segment_name"]


def segment_name(seg_id: int) -> str:
    """Return the canonical file name for ``seg_id`` (six zero-padded digits)."""
    return f"{seg_id:06d}.seg"


class Segment:
    """An append-only file holding encoded records."""

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._closed = False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # "a+b" creates the file if missing and always appends at the end.
        self._fh = open(self._path, "a+b")
        self._size = self._path.stat().st_size

    @property
    def path(self) -> pathlib.Path:
        """Filesystem path of this segment."""
        return self._path

    @property
    def seg_id(self) -> int:
        """Numeric id of this segment."""
        return self._seg_id

    @property
    def size(self) -> int:
        """Current byte length of the file."""
        if self._closed:
            return self._path.stat().st_size if self._path.exists() else self._size
        return self._size

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    def append(self, blob: bytes) -> int:
        """Append ``blob`` and return the offset it was written at."""
        if self._closed:
            raise ValueError("segment is closed")
        offset = self._size
        self._fh.write(blob)
        self._fh.flush()
        self._size += len(blob)
        return offset

    def truncate(self, size: int) -> None:
        """Cut the file down to ``size`` bytes, discarding a partial write."""
        if self._closed:
            raise ValueError("segment is closed")
        self._fh.truncate(size)
        self._fh.flush()
        self._size = size

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield ``(key, value, offset)`` for every record, ascending by offset.

        A truncated tail ends the scan silently; corruption raises
        :class:`CorruptSegmentError`.
        """
        with open(self._path, "rb") as fh:
            buf = fh.read()
        offset = 0
        total = len(buf)
        while offset < total:
            try:
                key, value, size = decode_record(buf, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += size

    def close(self) -> None:
        """Close the underlying file handle. Idempotent."""
        if not self._closed:
            self._fh.close()
            self._closed = True
