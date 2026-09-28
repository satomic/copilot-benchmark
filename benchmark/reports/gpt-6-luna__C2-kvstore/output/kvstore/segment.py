"""Append-only segment file support."""

from collections.abc import Iterator
from pathlib import Path

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record


class Segment:
    """One append-only file containing encoded records."""

    def __init__(self, path: Path, seg_id: int) -> None:
        self.path = Path(path)
        self._seg_id = seg_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("ab")
        self._closed = False

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        return self.path.stat().st_size

    def append(self, blob: bytes) -> int:
        """Append bytes, flush them, and return their starting offset."""
        if self._closed:
            raise ValueError("segment is closed")
        offset = self.size
        written = self._file.write(blob)
        self._file.flush()
        if written != len(blob):
            raise OSError("incomplete segment write")
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield complete records, ignoring only an incomplete final record."""
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
        """Close the segment file; repeated calls are harmless."""
        if not self._closed:
            self._file.close()
            self._closed = True
