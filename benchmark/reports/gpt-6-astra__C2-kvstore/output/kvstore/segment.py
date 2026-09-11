import os
from pathlib import Path
from typing import Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import _HEADER_SIZE, _decode_header, decode_record


class Segment:
    def __init__(self, path: Path, seg_id: int) -> None:
        self._path = Path(path)
        self._seg_id = seg_id
        self._file = self._path.open("a+b")
        self._has_truncated_tail = False

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        return os.fstat(self._file.fileno()).st_size

    def append(self, blob: bytes) -> int:
        self._file.seek(0, os.SEEK_END)
        offset = self._file.tell()
        self._file.write(blob)
        self._file.flush()
        os.fsync(self._file.fileno())
        return offset

    def _read_record(self, offset: int) -> tuple[str, str | None, int]:
        self._file.seek(offset)
        header = self._file.read(_HEADER_SIZE)
        try:
            _, key_len, value_len, _ = _decode_header(header)
            payload_size = key_len + value_len
            if self.size - offset - _HEADER_SIZE < payload_size:
                raise IncompleteRecordError("incomplete record payload")
            payload = self._file.read(payload_size)
            return decode_record(header + payload)
        except CorruptRecordError as exc:
            raise CorruptSegmentError(self._path, offset, str(exc)) from exc

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        offset = 0
        self._has_truncated_tail = False
        while offset < self.size:
            try:
                key, value, total_size = self._read_record(offset)
            except IncompleteRecordError:
                self._has_truncated_tail = True
                return
            yield key, value, offset
            offset += total_size

    def close(self) -> None:
        self._file.close()
