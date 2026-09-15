import os
import pathlib
from collections.abc import Iterator

from .errors import CorruptRecordError, CorruptSegmentError
from .record import decode_record, IncompleteRecordError


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = int(seg_id)
        self._file = open(self._path, "ab+")

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        self._file.seek(0, os.SEEK_END)
        return int(self._file.tell())

    def append(self, blob: bytes) -> int:
        offset = self.size
        self._file.seek(0, os.SEEK_END)
        self._file.write(blob)
        self._file.flush()
        os.fsync(self._file.fileno())
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        self._file.seek(0)
        data = self._file.read()
        pos = 0
        while pos < len(data):
            remaining = len(data) - pos
            if remaining < 15:
                break
            try:
                key, value, total_size = decode_record(data, pos)
            except IncompleteRecordError:
                break
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, pos, str(exc)) from exc
            yield (key, value, pos)
            pos += total_size

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
