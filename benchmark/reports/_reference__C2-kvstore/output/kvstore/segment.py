"""One append-only segment file."""

from __future__ import annotations

import pathlib
import re
from typing import BinaryIO, Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import decode_record

__all__ = ["SEGMENT_RE", "segment_name", "Segment"]

#: Only names matching this are part of the store. A ``.tmp`` file is invisible,
#: which is what makes compaction safe to interrupt.
SEGMENT_RE = re.compile(r"^\d{6}\.seg$")


def segment_name(seg_id: int) -> str:
    """Return the file name for a segment id, zero padded to six digits."""
    return f"{seg_id:06d}.seg"


class Segment:
    """An append-only file of records, opened lazily on first write."""

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._handle: BinaryIO | None = None
        if not self._path.exists():
            self._path.touch()

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        """Current byte length of the file on disk."""
        if self._handle is not None:
            self._handle.flush()
        return self._path.stat().st_size

    def append(self, blob: bytes) -> int:
        """Append ``blob`` and return the offset it was written at."""
        if self._handle is None:
            self._handle = self._path.open("ab")
        offset = self._path.stat().st_size
        self._handle.write(blob)
        self._handle.flush()
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield ``(key, value, offset)`` for every intact record, in order.

        A truncated tail ends the scan quietly. Damage raises
        :class:`CorruptSegmentError`.
        """
        data = self._path.read_bytes()
        offset = 0
        while offset < len(data):
            try:
                key, value, size = decode_record(data, offset)
            except IncompleteRecordError:
                return
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from None
            yield key, value, offset
            offset += size

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
