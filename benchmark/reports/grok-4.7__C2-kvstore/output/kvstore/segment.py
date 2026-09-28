"""One append-only segment file."""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator
from typing import BinaryIO

from kvstore.errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from kvstore.record import decode_record

# A torn tail is left on disk so its bytes still count. The next append to this
# segment truncates back to the last complete record first; otherwise a later
# scan would stop at the tail and miss the new record.


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._fh = self._open()
        self._fh.seek(0, os.SEEK_END)
        self._size = self._fh.tell()
        self._logical: int | None = None

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def size(self) -> int:
        """Current byte length of the file, including any torn tail."""
        return self._size

    def append(self, blob: bytes) -> int:
        """Append blob and return the offset it was written at."""
        self._discard_torn_tail()
        offset = self._size
        fh = self._require_open()
        fh.seek(offset)
        fh.write(blob)
        fh.flush()
        os.fsync(fh.fileno())
        self._size = offset + len(blob)
        self._logical = self._size
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield complete records. A torn tail stops the scan; corruption raises."""
        data = self._read_all()
        offset = 0
        limit = len(data)
        while offset < limit:
            try:
                key, value, total = decode_record(data, offset)
            except IncompleteRecordError:
                self._logical = offset
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += total
        self._logical = offset

    def close(self) -> None:
        fh = self._fh
        self._fh = None
        if fh is not None and not fh.closed:
            fh.close()

    def _open(self) -> BinaryIO:
        if self._path.exists():
            return self._path.open("r+b")
        return self._path.open("w+b")

    def _require_open(self) -> BinaryIO:
        if self._fh is None or self._fh.closed:
            raise ValueError("segment is closed")
        return self._fh

    def _read_all(self) -> bytes:
        fh = self._require_open()
        fh.flush()
        fh.seek(0)
        data = fh.read()
        self._size = len(data)
        fh.seek(self._size)
        return data

    def _discard_torn_tail(self) -> None:
        logical = self._logical_end()
        if logical == self._size:
            return
        fh = self._require_open()
        fh.truncate(logical)
        fh.flush()
        self._size = logical
        self._logical = logical

    def _logical_end(self) -> int:
        if self._logical is not None:
            return self._logical
        data = self._read_all()
        self._logical = _logical_end(data)
        return self._logical


def _logical_end(data: bytes) -> int:
    offset = 0
    limit = len(data)
    while offset < limit:
        try:
            _, _, total = decode_record(data, offset)
        except IncompleteRecordError:
            return offset
        except CorruptRecordError:
            return offset
        offset += total
    return offset
