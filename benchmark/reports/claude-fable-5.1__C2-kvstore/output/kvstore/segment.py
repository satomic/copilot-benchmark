"""One append-only segment file."""

from __future__ import annotations

import os
import pathlib
import re
from typing import IO, Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record

SEGMENT_NAME_RE = re.compile(r"^\d{6}\.seg$")


def segment_filename(seg_id: int) -> str:
    """Return the canonical file name for a segment id."""
    return f"{seg_id:06d}.seg"


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._fh: IO[bytes] | None = open(self._path, "ab")
        self._size = self._path.stat().st_size

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        return self._size

    def append(self, blob: bytes) -> int:
        if self._fh is None:
            raise ValueError("segment is closed")
        offset = self._size
        self._fh.write(blob)
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._size += len(blob)
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield ``(key, value, offset)`` for every record; stop cleanly at a truncated tail."""
        data = self._path.read_bytes()
        offset = 0
        while offset < len(data):
            try:
                key, value, size = decode_record(data, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += size

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
