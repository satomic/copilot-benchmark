"""KVStore: a durable key-value store on append-only segment files."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import struct
from typing import Iterator

from .index import Index, Location
from .record import HEADER_FMT, HEADER_SIZE, decode_record, encode_record
from .segment import SEGMENT_NAME_RE, Segment, segment_filename

MAX_KEY_BYTES = 0xFFFF


@dataclasses.dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(self, root: str | os.PathLike, *, max_segment_bytes: int = 4096) -> None:
        if not isinstance(max_segment_bytes, int) or isinstance(max_segment_bytes, bool):
            raise ValueError("max_segment_bytes must be an int >= 16")
        if max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an int >= 16")
        self._root = pathlib.Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_segment_bytes = max_segment_bytes
        self._index = Index()
        # seg_id -> number of records recovered/appended in that segment
        self._record_counts: dict[int, int] = {}
        self._active: Segment | None = None
        self._closed = False
        self._recover()

    # ----------------------------------------------------------------- internals

    @property
    def root(self) -> pathlib.Path:
        return self._root

    @property
    def index(self) -> Index:
        return self._index

    @property
    def active_segment(self) -> Segment:
        self._check_open()
        assert self._active is not None
        return self._active

    def segment_ids(self) -> list[int]:
        """Ids of every ``<id>.seg`` file in the root, ascending."""
        ids = [
            int(p.name[:6])
            for p in self._root.iterdir()
            if p.is_file() and SEGMENT_NAME_RE.match(p.name)
        ]
        return sorted(ids)

    def segment_path(self, seg_id: int) -> pathlib.Path:
        return self._root / segment_filename(seg_id)

    def total_records(self) -> int:
        return sum(self._record_counts.values())

    def _recover(self) -> None:
        ids = self.segment_ids()
        for seg_id in ids:
            self._load_segment(seg_id)
        active_id = ids[-1] if ids else 1
        self._activate(active_id)

    def _load_segment(self, seg_id: int) -> int:
        """Feed every record of a segment into the index; return the record count."""
        seg = Segment(self.segment_path(seg_id), seg_id)
        count = 0
        try:
            for key, value, offset in seg.scan():
                self._index.put(key, Location(seg_id, offset), tombstone=value is None)
                count += 1
        finally:
            seg.close()
        self._record_counts[seg_id] = count
        return count

    def _activate(self, seg_id: int) -> None:
        if self._active is not None:
            self._active.close()
        self._active = Segment(self.segment_path(seg_id), seg_id)
        self._record_counts.setdefault(seg_id, 0)

    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")

    def _validate_key(self, key: object) -> None:
        if not isinstance(key, str):
            raise TypeError("key must be str")
        if not 1 <= len(key.encode("utf-8")) <= MAX_KEY_BYTES:
            raise ValueError("key must encode to 1..65535 UTF-8 bytes")

    def _append(self, key: str, blob: bytes, *, tombstone: bool) -> None:
        active = self.active_segment
        if active.size != 0 and active.size + len(blob) > self._max_segment_bytes:
            self._activate(active.seg_id + 1)
            active = self.active_segment
        offset = active.append(blob)
        self._record_counts[active.seg_id] = self._record_counts.get(active.seg_id, 0) + 1
        self._index.put(key, Location(active.seg_id, offset), tombstone=tombstone)

    def _read_at(self, loc: Location) -> tuple[str, str | None]:
        with open(self.segment_path(loc.seg_id), "rb") as fh:
            fh.seek(loc.offset)
            header = fh.read(HEADER_SIZE)
            _, _, key_len, value_len, _ = struct.unpack(HEADER_FMT, header)
            body = fh.read(key_len + value_len)
        key, value, _ = decode_record(header + body)
        return key, value

    def reset_after_compaction(self, new_id: int, record_count: int) -> None:
        """Rebuild state so that ``new_id`` is the only, active segment."""
        self._check_open()
        if self._active is not None:
            self._active.close()
            self._active = None
        self._index = Index()
        self._record_counts = {}
        self._load_segment(new_id)
        self._record_counts[new_id] = record_count
        self._activate(new_id)

    # ------------------------------------------------------------------- public

    def set(self, key: str, value: str) -> None:
        self._check_open()
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError("value must be str")
        self._append(key, encode_record(key, value), tombstone=False)

    def get(self, key: str) -> str | None:
        self._check_open()
        self._validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        _, value = self._read_at(loc)
        return value

    def delete(self, key: str) -> bool:
        self._check_open()
        self._validate_key(key)
        if self._index.get(key) is None:
            return False
        self._append(key, encode_record(key, None), tombstone=True)
        return True

    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()

    def items(self) -> Iterator[tuple[str, str]]:
        """Yield ``(key, value)`` for live keys in ``keys()`` order."""
        for key in self.keys():
            loc = self._index.get(key)
            assert loc is not None
            _, value = self._read_at(loc)
            assert value is not None
            yield key, value

    def stats(self) -> Stats:
        self._check_open()
        ids = self.segment_ids()
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        total = self.total_records()
        return Stats(
            live_keys=live,
            tombstones=tombstones,
            total_records=total,
            dead_records=total - live - tombstones,
            segment_count=len(ids),
            bytes_on_disk=sum(self.segment_path(i).stat().st_size for i in ids),
        )

    def close(self) -> None:
        if self._closed:
            return
        if self._active is not None:
            self._active.close()
        self._closed = True

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
