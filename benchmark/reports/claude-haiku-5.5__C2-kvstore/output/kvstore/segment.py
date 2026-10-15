"""Segment: one append-only file of records."""

from __future__ import annotations

import pathlib
import re
from typing import BinaryIO, Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError, RecordError
from .record import HEADER, HEADER_SIZE, decode_record

_SEGMENT_NAME_RE = re.compile(r"[0-9]{6}\.seg")


def segment_name(seg_id: int) -> str:
    """File name for a segment id, e.g. ``000001.seg``."""
    return f"{seg_id:06d}.seg"


def list_segment_ids(root: pathlib.Path) -> list[int]:
    """Ids of every ``<id>.seg`` file in ``root``, ascending. Other files are ignored."""
    return sorted(
        int(p.name[:6])
        for p in root.iterdir()
        if p.is_file() and _SEGMENT_NAME_RE.fullmatch(p.name)
    )


class Segment:
    """An append-only file of records.

    A torn write at the tail is ignored by ``scan``; it is physically truncated
    lazily, on the next ``append``, so that new records never follow garbage bytes.
    """

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._fh: BinaryIO | None = open(self._path, "a+b")
        self._size = self._path.stat().st_size
        self._truncate_to: int | None = None

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        return self._size

    def _handle(self) -> BinaryIO:
        if self._fh is None:
            raise ValueError(f"segment {self._path.name} is closed")
        return self._fh

    def append(self, blob: bytes) -> int:
        """Write ``blob`` at the end of the file and flush. Returns its offset."""
        fh = self._handle()
        if self._truncate_to is not None:
            fh.truncate(self._truncate_to)
            self._size = self._truncate_to
            self._truncate_to = None
        offset = self._size
        fh.write(blob)
        fh.flush()
        self._size += len(blob)
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield ``(key, value, offset)`` for every record in offset order."""
        self._handle()
        data = self._path.read_bytes()
        self._truncate_to = None
        offset = 0
        while offset < len(data):
            try:
                key, value, n = decode_record(data, offset)
            except IncompleteRecordError:
                # Torn tail: remember where valid data ends so append can cut it off.
                self._truncate_to = offset
                return
            except RecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += n

    def read_at(self, offset: int) -> tuple[str, str | None, int]:
        """Decode the single record stored at ``offset``."""
        self._handle().flush()
        with open(self._path, "rb") as f:
            f.seek(offset)
            head = f.read(HEADER_SIZE)
            if len(head) < HEADER_SIZE:
                raise CorruptSegmentError(self._path, offset, "truncated header")
            _, _, key_len, value_len, _ = HEADER.unpack(head)
            body = f.read(key_len + value_len)
        try:
            return decode_record(head + body, 0)
        except CorruptRecordError as exc:
            raise CorruptSegmentError(self._path, offset, str(exc)) from exc
        except RecordError as exc:
            raise CorruptSegmentError(self._path, offset, f"truncated record: {exc}") from exc

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
