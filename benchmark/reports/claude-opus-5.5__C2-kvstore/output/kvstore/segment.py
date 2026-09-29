"""A single append-only segment file."""

from __future__ import annotations

import os
import pathlib
import re
from typing import BinaryIO, Iterator

from .errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from .record import HEADER_SIZE, decode_record, record_size

SEGMENT_RE = re.compile(r"[0-9]{6}\.seg")


def segment_path(root: pathlib.Path, seg_id: int) -> pathlib.Path:
    """Return the path of segment ``seg_id`` inside ``root``."""
    return root / f"{seg_id:06d}.seg"


def segment_ids(root: pathlib.Path) -> list[int]:
    """Return the ids of every ``<id>.seg`` file in ``root``, ascending."""
    ids = [
        int(entry.name[:6])
        for entry in root.iterdir()
        if SEGMENT_RE.fullmatch(entry.name) and entry.is_file()
    ]
    return sorted(ids)


class Segment:
    """One append-only file of records. The file is created if missing."""

    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self._path = pathlib.Path(path)
        self._seg_id = seg_id
        self._path.touch(exist_ok=True)
        self._size = self._path.stat().st_size
        self._fh: BinaryIO | None = None
        self._closed = False
        # Byte length of the well-formed prefix, known once scan() has finished.
        self._valid_size: int | None = None

    @property
    def path(self) -> pathlib.Path:
        return self._path

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def size(self) -> int:
        return self._size

    def discard_tail(self) -> None:
        """Truncate a partial record found at the end of the file by scan()."""
        if self._valid_size is not None and self._valid_size < self._size:
            self._close_handle()
            os.truncate(self._path, self._valid_size)
            self._size = self._valid_size

    def append(self, blob: bytes) -> int:
        """Append ``blob`` at the end of the file and return its offset."""
        if self._closed:
            raise ValueError("segment is closed")
        if self._fh is None:
            self._fh = open(self._path, "ab")
        offset = self._size
        self._fh.write(blob)
        self._fh.flush()
        self._size += len(blob)
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        """Yield ``(key, value, offset)`` for every record, tolerating a partial tail."""
        data = self._path.read_bytes()
        offset = 0
        while offset < len(data):
            try:
                key, value, total = decode_record(data, offset)
            except IncompleteRecordError:
                break
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from None
            yield key, value, offset
            offset += total
        self._valid_size = offset

    def read_at(self, offset: int) -> tuple[str, str | None, int]:
        """Decode the single record stored at ``offset``."""
        with open(self._path, "rb") as fh:
            fh.seek(offset)
            header = fh.read(HEADER_SIZE)
            try:
                total = record_size(header)
                data = header + fh.read(total - HEADER_SIZE)
                return decode_record(data)
            except (CorruptRecordError, IncompleteRecordError) as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from None

    def _close_handle(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def close(self) -> None:
        self._close_handle()
        self._closed = True
