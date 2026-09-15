"""One append-only segment file."""

from __future__ import annotations

import os
import pathlib
from typing import Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record


class Segment:
    """A single append-only ``<id>.seg`` file."""

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._file = open(self._path, "a+b")  # creates the file if missing

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        """Current byte length of the file."""
        return os.fstat(self._file.fileno()).st_size

    def append(self, blob: bytes) -> int:
        """Write ``blob`` at the end of the file; returns its offset."""
        offset = self.size
        self._file.write(blob)
        self._file.flush()
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield ``(key, value, offset)`` for every record, in offset order.

        A truncated tail (partial write from a crashed process) stops the
        scan cleanly; any other defect raises ``CorruptSegmentError``.
        """
        with open(self._path, "rb") as fh:
            buf = fh.read()
        offset = 0
        while offset < len(buf):
            try:
                key, value, size = decode_record(buf, offset)
            except IncompleteRecordError:
                return  # truncated tail: stop cleanly, no error
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += size

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
