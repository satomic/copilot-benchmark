from __future__ import annotations

import os
import pathlib
from typing import BinaryIO, Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path: pathlib.Path = pathlib.Path(path)
        self._seg_id: int = seg_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._file: BinaryIO | None = self._path.open("r+b")

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        if self._file is not None and not self._file.closed:
            self._file.flush()
        return os.path.getsize(self._path)

    def append(self, blob: bytes) -> int:
        if self._file is None or self._file.closed:
            raise ValueError("Segment is closed")
        self._file.seek(0, os.SEEK_END)
        offset = self._file.tell()
        self._file.write(blob)
        self._file.flush()
        return offset

    def read_at(self, offset: int) -> tuple[str, str | None, int]:
        if self._file is None or self._file.closed:
            raise ValueError("Segment is closed")
        self._file.flush()
        data = self._path.read_bytes()
        try:
            return decode_record(data, offset)
        except (IncompleteRecordError, CorruptRecordError) as exc:
            raise CorruptSegmentError(self._path, offset, str(exc)) from exc

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        if self._file is not None and not self._file.closed:
            self._file.flush()
        data = self._path.read_bytes()
        offset = 0
        total_len = len(data)
        while offset < total_len:
            try:
                key, value, record_size = decode_record(data, offset)
            except IncompleteRecordError:
                break
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += record_size

    def close(self) -> None:
        if self._file is not None and not self._file.closed:
            self._file.close()
        self._file = None
