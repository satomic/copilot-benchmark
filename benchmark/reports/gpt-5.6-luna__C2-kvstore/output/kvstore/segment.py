from pathlib import Path
from typing import Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record


class Segment:
    def __init__(self, path: Path, seg_id: int) -> None:
        self._path = Path(path)
        self._seg_id = seg_id
        self._file = self._path.open("a+b")

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        self._file.flush()
        return self._path.stat().st_size

    def append(self, blob: bytes) -> int:
        self._file.seek(0, 2)
        offset = self._file.tell()
        self._file.write(blob)
        self._file.flush()
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        data = self._path.read_bytes()
        offset = 0
        while offset < len(data):
            try:
                key, value, size = decode_record(data, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += size

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()
