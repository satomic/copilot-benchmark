import os
import pathlib
from typing import Iterator

from kvstore.errors import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
)
from kvstore.record import decode_record


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self._path, "a+b")

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        if self._file.closed:
            return self._path.stat().st_size if self._path.exists() else 0
        self._file.flush()
        return os.fstat(self._file.fileno()).st_size

    def append(self, blob: bytes) -> int:
        if self._file.closed:
            raise ValueError("Segment is closed")
        self._file.seek(0, os.SEEK_END)
        offset = self._file.tell()
        self._file.write(blob)
        self._file.flush()
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        if self._file.closed:
            raise ValueError("Segment is closed")
        self._file.flush()
        self._file.seek(0)
        data = self._file.read()
        curr = 0
        data_len = len(data)
        while curr < data_len:
            if data_len - curr < 15:
                break
            try:
                key, value, total_size = decode_record(data, curr)
            except IncompleteRecordError:
                break
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, curr, str(exc)) from exc

            yield key, value, curr
            curr += total_size

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
