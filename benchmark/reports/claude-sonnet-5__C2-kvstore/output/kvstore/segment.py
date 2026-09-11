"""Segment: a single append-only log file."""

from __future__ import annotations

import os
import pathlib
from typing import Iterator

from .errors import CorruptRecordError, IncompleteRecordError
from .errors import CorruptSegmentError
from .record import decode_record


class Segment:
    """One append-only segment file on disk."""

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = path
        self._seg_id = seg_id
        self._file = open(path, "a+b")
        # Resolved lazily on first append: the offset at which the last
        # valid record ends. A crash can leave a truncated tail after that
        # offset; it must stay on disk (for stats) until we actually write
        # again, at which point it is truncated away before the new record
        # is appended, so appends never land inside garbage bytes.
        self._append_offset: int | None = None

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def size(self) -> int:
        return os.fstat(self._file.fileno()).st_size

    def append(self, blob: bytes) -> int:
        """Append blob to the end of the file, flush, and return its offset.

        Before the first append, discards any truncated tail left by a
        crashed write, so new records never land after garbage bytes.
        """
        if self._append_offset is None:
            self._append_offset = self._valid_end()
        offset = self._append_offset
        self._file.seek(offset)
        self._file.truncate(offset)
        self._file.write(blob)
        self._file.flush()
        os.fsync(self._file.fileno())
        self._append_offset = offset + len(blob)
        return offset

    def _valid_end(self) -> int:
        """Return the offset where the last complete, valid record ends."""
        with open(self._path, "rb") as fh:
            data = fh.read()
        offset = 0
        length = len(data)
        while offset < length:
            try:
                _, _, total_size = decode_record(data, offset)
            except IncompleteRecordError:
                break
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            offset += total_size
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield (key, value, offset) for every complete record in the file.

        Stops cleanly on a truncated tail. Raises CorruptSegmentError on any
        other malformed record, including a bad record at the very end.
        """
        with open(self._path, "rb") as fh:
            data = fh.read()
        offset = 0
        length = len(data)
        while offset < length:
            try:
                key, value, total_size = decode_record(data, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += total_size

    def close(self) -> None:
        self._file.close()
