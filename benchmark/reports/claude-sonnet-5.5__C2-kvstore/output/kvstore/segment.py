"""One append-only segment file."""
from __future__ import annotations

import os
import pathlib
from typing import Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._fh = open(self._path, "a+b")

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        self._fh.flush()
        return os.path.getsize(self._path)

    def append(self, blob: bytes) -> int:
        """Append ``blob`` at the end of the file; return its offset."""
        offset = self.size
        self._fh.seek(0, os.SEEK_END)
        self._fh.write(blob)
        self._fh.flush()
        return offset

    def read_record(self, offset: int) -> tuple[str, str | None, int]:
        """Decode the record stored at ``offset``."""
        data = self._read_all()
        try:
            return decode_record(data, offset)
        except (CorruptRecordError, IncompleteRecordError) as exc:
            raise CorruptSegmentError(self._path, offset, str(exc)) from exc

    def _read_all(self) -> bytes:
        self._fh.flush()
        self._fh.seek(0)
        return self._fh.read()

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield (key, value, offset); stop silently at a truncated tail."""
        data = self._read_all()
        offset = 0
        while offset < len(data):
            try:
                key, value, total = decode_record(data, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += total

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()
