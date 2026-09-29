import os
import pathlib
from typing import Iterator

from kvstore.errors import CorruptSegmentError
from kvstore.record import decode_record
from kvstore.errors import IncompleteRecordError, CorruptRecordError


class Segment:
    """An append-only segment file."""

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = path
        self._seg_id = seg_id
        self._file: int | None = None  # file descriptor

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        try:
            return os.path.getsize(self._path)
        except FileNotFoundError:
            return 0

    def append(self, blob: bytes) -> int:
            """Write *blob* at the end of the file and flush.

            Returns the offset the blob was written at.
            """
            if self._file is None:
                self._file = os.open(
                    str(self._path),
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                    0o666,
                )
            offset = os.lseek(self._file, 0, os.SEEK_END)
            os.write(self._file, blob)
            os.fsync(self._file)
            return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield every record in ascending offset order.

        Stops cleanly on a truncated tail (partial write at the end).
        Raises CorruptSegmentError on any other corruption.
        """
        try:
            with open(self._path, "rb") as f:
                buf = f.read()
        except FileNotFoundError:
            return

        offset = 0
        while offset < len(buf):
            try:
                key, value, total = decode_record(buf, offset)
                yield key, value, offset
                offset += total
            except IncompleteRecordError:
                # Truncated tail — stop cleanly
                return
            except CorruptRecordError as e:
                raise CorruptSegmentError(
                    self._path,
                    offset,
                    str(e),
                ) from e

    def close(self) -> None:
        if self._file is not None:
            os.close(self._file)
            self._file = None