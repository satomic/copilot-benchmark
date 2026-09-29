import os
import pathlib
import re
from typing import Optional

from kvstore.errors import CorruptSegmentError
from kvstore.record import encode_record, decode_record
from kvstore.segment import Segment
from kvstore.index import Index, Location

_SEG_PATTERN = re.compile(r"^\d{6}\.seg$")


class Stats:
    """Immutable snapshot of store statistics."""

    __slots__ = ("live_keys", "tombstones", "total_records",
                 "dead_records", "segment_count", "bytes_on_disk")

    def __init__(
        self,
        live_keys: int,
        tombstones: int,
        total_records: int,
        dead_records: int,
        segment_count: int,
        bytes_on_disk: int,
    ) -> None:
        self.live_keys = live_keys
        self.tombstones = tombstones
        self.total_records = total_records
        self.dead_records = dead_records
        self.segment_count = segment_count
        self.bytes_on_disk = bytes_on_disk

    def __repr__(self) -> str:
        return (
            f"Stats(live_keys={self.live_keys}, tombstones={self.tombstones}, "
            f"total_records={self.total_records}, dead_records={self.dead_records}, "
            f"segment_count={self.segment_count}, bytes_on_disk={self.bytes_on_disk})"
        )


class KVStore:
    """An append-only key-value store backed by segment files."""

    def __init__(
        self, root: str | os.PathLike, *, max_segment_bytes: int = 4096
    ) -> None:
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < 16:
            raise ValueError(
                f"max_segment_bytes must be an int >= 16, got {max_segment_bytes!r}"
            )
        self._max_seg = max_segment_bytes
        self._index = Index()
        self._segments: dict[int, Segment] = {}
        self._closed = False
        self._reader_fds: dict[int, int] = {}
        self._recover()

    def _recover(self) -> None:
        seg_ids = []
        for entry in self._root.iterdir():
            if entry.is_file() and _SEG_PATTERN.match(entry.name):
                seg_ids.append(int(entry.stem))
        seg_ids.sort()

        total_count = 0
        for sid in seg_ids:
            path = self._root / f"{sid:06d}.seg"
            seg = Segment(path, sid)
            self._segments[sid] = seg
            for key, value, offset in seg.scan():
                total_count += 1
                self._index.put(key, Location(sid, offset), tombstone=(value is None))
        self._total_records = total_count

        if not seg_ids:
            sid = 1
            path = self._root / f"{sid:06d}.seg"
            seg = Segment(path, sid)
            self._segments[sid] = seg

    # -- public API -----------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        if self._closed:
            raise ValueError("store is closed")
        if not isinstance(key, str):
            raise TypeError(f"key must be str, not {type(key).__name__}")
        if not isinstance(value, str):
            raise TypeError(f"value must be str, not {type(value).__name__}")
        key_bytes = key.encode("utf-8")
        if not (1 <= len(key_bytes) <= 65535):
            raise ValueError(
                f"key UTF-8 byte length must be 1..65535, got {len(key_bytes)}"
            )
        blob = encode_record(key, value)
        self._append_to_active(key, blob, tombstone=False)

    def get(self, key: str) -> str | None:
        if self._closed:
            raise ValueError("store is closed")
        loc = self._index.get(key)
        if loc is None:
            return None
        _, value, _ = self._read_record(loc.seg_id, loc.offset)
        return value

    def delete(self, key: str) -> bool:
        if self._closed:
            raise ValueError("store is closed")
        if self._index.get(key) is None:
            return False
        blob = encode_record(key, None)
        self._append_to_active(key, blob, tombstone=True)
        return True

    def keys(self) -> list[str]:
        if self._closed:
            raise ValueError("store is closed")
        return self._index.live_keys()

    def stats(self) -> Stats:
        if self._closed:
            raise ValueError("store is closed")
        live = len(self._index)
        tombs = self._index.tombstone_count()
        seg_count = len(self._segments)
        bytes_total = sum(seg.size for seg in self._segments.values())
        return Stats(
            live_keys=live,
            tombstones=tombs,
            total_records=self._total_records,
            dead_records=self._total_records - live - tombs,
            segment_count=seg_count,
            bytes_on_disk=bytes_total,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for seg in self._segments.values():
            seg.close()
        for fd in self._reader_fds.values():
            os.close(fd)
        self._reader_fds.clear()

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internal helpers -----------------------------------------------------

    def _append_to_active(self, key: str, blob: bytes, *, tombstone: bool) -> None:
        max_sid = max(self._segments)
        active = self._segments[max_sid]
        n = len(blob)
        # Rollover: if segment is non-empty and would overflow
        if active.size != 0 and active.size + n > self._max_seg:
            active.close()
            new_sid = max_sid + 1
            path = self._root / f"{new_sid:06d}.seg"
            active = Segment(path, new_sid)
            self._segments[new_sid] = active
        offset = active.append(blob)
        self._total_records += 1
        self._index.put(key, Location(active.seg_id, offset), tombstone=tombstone)

    def _read_record(
        self, seg_id: int, offset: int
    ) -> tuple[str, str | None, int]:
        path = self._root / f"{seg_id:06d}.seg"
        fd = self._reader_fds.get(seg_id)
        if fd is None:
            fd = os.open(str(path), os.O_RDONLY)
            self._reader_fds[seg_id] = fd
        # Determine file size to read enough bytes
        file_size = os.lseek(fd, 0, os.SEEK_END) - offset
        os.lseek(fd, offset, os.SEEK_SET)
        buf = os.read(fd, file_size)
        return decode_record(buf, 0)

    # exposed for compact to use (hacky but keeps things contained)
    @property
    def _root_path(self) -> pathlib.Path:
        return self._root

    @property
    def _max_seg_bytes(self) -> int:
        return self._max_seg

    @property
    def _index_ref(self) -> Index:
        return self._index

    @property
    def _segments_ref(self) -> dict[int, Segment]:
        return self._segments

    @property
    def _total_records_ref(self) -> int:
        return self._total_records

    @_total_records_ref.setter
    def _total_records_ref(self, val: int) -> None:
        self._total_records = val