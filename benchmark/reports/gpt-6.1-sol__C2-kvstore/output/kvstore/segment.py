import os
from pathlib import Path
from typing import BinaryIO, Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import HEADER_SIZE, _parse_header, decode_record


class Segment:
    def __init__(self, path: Path, seg_id: int) -> None:
        self.path = Path(path)
        self._seg_id = seg_id
        self._file = self.path.open("r+b" if self.path.exists() else "x+b")
        self._valid_size = 0

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        return os.fstat(self._file.fileno()).st_size

    def append(self, blob: bytes) -> int:
        self._file.seek(0, os.SEEK_END)
        offset = self._file.tell()
        written = self._file.write(blob)
        if written != len(blob):
            raise OSError("incomplete segment write")
        self._file.flush()
        os.fsync(self._file.fileno())
        self._valid_size = offset + len(blob)
        return offset

    def _decode_at(self, stream: BinaryIO, offset: int) -> tuple[str, str | None, int]:
        stream.seek(offset)
        header = stream.read(HEADER_SIZE)
        try:
            _, key_len, value_len, _ = _parse_header(header)
            remaining = os.fstat(stream.fileno()).st_size - offset - HEADER_SIZE
            if remaining < key_len + value_len:
                raise IncompleteRecordError("incomplete record payload")
            payload = stream.read(key_len + value_len)
            return decode_record(header + payload)
        except CorruptRecordError as exc:
            raise CorruptSegmentError(self.path, offset, str(exc)) from exc

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        if self._file.closed:
            raise ValueError("segment is closed")
        self._valid_size = 0
        with self.path.open("rb") as stream:
            offset = 0
            while offset < os.fstat(stream.fileno()).st_size:
                try:
                    key, value, size = self._decode_at(stream, offset)
                except IncompleteRecordError:
                    return
                self._valid_size = offset + size
                yield key, value, offset
                offset += size

    def _read_record(self, offset: int) -> tuple[str, str | None, int]:
        if self._file.closed:
            raise ValueError("segment is closed")
        return self._decode_at(self._file, offset)

    def close(self) -> None:
        self._file.close()
