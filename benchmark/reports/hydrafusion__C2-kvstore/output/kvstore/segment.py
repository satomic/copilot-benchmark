from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from .errors import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
)
from .record import decode_record


class Segment:
    def __init__(self, path: Path, seg_id: int) -> None:
        self.path = path
        self._seg_id = seg_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: BinaryIO = path.open("a+b")
        self._closed = False

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        self._ensure_open()
        return self.path.stat().st_size

    def append(self, blob: bytes) -> int:
        self._ensure_open()
        self._file.seek(0, 2)
        offset = self._file.tell()
        self._file.write(blob)
        self._file.flush()
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        self._ensure_open()
        self._file.flush()
        data = self.path.read_bytes()
        offset = 0
        while offset < len(data):
            try:
                key, value, size = decode_record(data, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self.path, offset, str(exc)) from exc
            yield key, value, offset
            offset += size

    def close(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("segment is closed")
