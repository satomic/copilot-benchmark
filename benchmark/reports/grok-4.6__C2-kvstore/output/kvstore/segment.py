"""One append-only segment file (`NNNNNN.seg`)."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from kvstore.errors import CorruptRecordError, CorruptSegmentError, IncompleteRecordError
from kvstore.record import decode_record

SEG_NAME_RE = re.compile(r"^\d{6}\.seg$")


def segment_filename(seg_id: int) -> str:
    return f"{seg_id:06d}.seg"


def segment_path(root: Path, seg_id: int) -> Path:
    return Path(root) / segment_filename(seg_id)


def list_segment_ids(root: Path) -> list[int]:
    ids: list[int] = []
    if not root.exists():
        return ids
    for entry in root.iterdir():
        if entry.is_file() and SEG_NAME_RE.match(entry.name):
            ids.append(int(entry.name[:6]))
    ids.sort()
    return ids


class Segment:
    def __init__(self, path: Path, seg_id: int) -> None:
        self._path = Path(path)
        self._seg_id = seg_id
        self._file = open(self._path, "a+b")
        self._file.seek(0, os.SEEK_END)
        self._committed = self._file.tell()
        self._closed = False

    @property
    def seg_id(self) -> int:
        return self._seg_id

    @property
    def path(self) -> Path:
        return self._path

    @property
    def size(self) -> int:
        if self._closed:
            return self._path.stat().st_size
        self._file.flush()
        return os.fstat(self._file.fileno()).st_size

    def append(self, blob: bytes) -> int:
        self._ensure_open()
        self._file.seek(self._committed)
        self._file.truncate(self._committed)
        offset = self._committed
        self._file.write(blob)
        self._file.flush()
        os.fsync(self._file.fileno())
        self._committed += len(blob)
        return offset

    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        self._ensure_open()
        self._file.seek(0)
        data = self._file.read()
        offset = 0
        while True:
            try:
                key, value, size = decode_record(data, offset)
            except IncompleteRecordError:
                break
            except CorruptRecordError as exc:
                raise CorruptSegmentError(self._path, offset, str(exc)) from exc
            yield key, value, offset
            offset += size
        self._committed = offset
        self._file.seek(0, os.SEEK_END)

    def close(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("segment is closed")
