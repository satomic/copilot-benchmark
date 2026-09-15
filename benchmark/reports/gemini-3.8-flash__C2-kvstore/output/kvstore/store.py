import dataclasses
import os
import pathlib
import re
import struct

from kvstore.errors import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
)
from kvstore.index import Index, Location
from kvstore.record import decode_record, encode_record
from kvstore.segment import Segment

_SEGMENT_RE = re.compile(r"^(\d{6})\.seg$")


@dataclasses.dataclass(frozen=True)
class Stats:
    live_keys: int
    tombstones: int
    total_records: int
    dead_records: int
    segment_count: int
    bytes_on_disk: int


class KVStore:
    def __init__(
        self, root: str | os.PathLike[str], *, max_segment_bytes: int = 4096
    ) -> None:
        if (
            type(max_segment_bytes) is not int
            or max_segment_bytes < 16
        ):
            raise ValueError("max_segment_bytes must be an int >= 16")

        self._root = pathlib.Path(root)
        self._max_segment_bytes = max_segment_bytes
        self._closed = False
        self._index = Index()
        self._total_records = 0

        self._root.mkdir(parents=True, exist_ok=True)
        seg_files = self._get_segment_files()

        for seg_id, path in seg_files:
            seg = Segment(path, seg_id)
            for key, val, offset in seg.scan():
                self._total_records += 1
                self._index.put(
                    key, Location(seg_id, offset), tombstone=(val is None)
                )
            seg.close()

        if seg_files:
            active_id, active_path = seg_files[-1]
        else:
            active_id = 1
            active_path = self._root / "000001.seg"
        self._active_segment = Segment(active_path, active_id)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("KVStore is closed")

    def _validate_key(self, key: str) -> None:
        if not isinstance(key, str):
            raise TypeError(f"Key must be str, got {type(key).__name__}")
        key_len = len(key.encode("utf-8"))
        if key_len < 1 or key_len > 65535:
            raise ValueError(f"Key byte length must be in 1..65535, got {key_len}")

    def _get_segment_files(self) -> list[tuple[int, pathlib.Path]]:
        files: list[tuple[int, pathlib.Path]] = []
        if not self._root.exists():
            return files
        for entry in self._root.iterdir():
            if entry.is_file():
                match = _SEGMENT_RE.match(entry.name)
                if match:
                    files.append((int(match.group(1)), entry))
        files.sort(key=lambda x: x[0])
        return files

    def _prepare_write(self, n: int) -> None:
        if self._active_segment.size == 0:
            return
        if self._active_segment.size + n > self._max_segment_bytes:
            self._active_segment.close()
            new_id = self._active_segment.seg_id + 1
            new_path = self._root / f"{new_id:06d}.seg"
            self._active_segment = Segment(new_path, new_id)

    def _read_value_at(self, loc: Location) -> str:
        path = self._root / f"{loc.seg_id:06d}.seg"
        if loc.seg_id == self._active_segment.seg_id:
            self._active_segment._file.flush()
        with open(path, "rb") as f:
            f.seek(loc.offset)
            header = f.read(15)
            if len(header) < 15:
                raise CorruptSegmentError(
                    path, loc.offset, "Incomplete record header"
                )
            magic, flags, key_len, value_len, _ = struct.unpack(
                ">4sBHII", header
            )
            rest = f.read(key_len + value_len)
            try:
                _, val, _ = decode_record(header + rest, 0)
            except (IncompleteRecordError, CorruptRecordError) as exc:
                raise CorruptSegmentError(path, loc.offset, str(exc)) from exc
            if val is None:
                raise CorruptSegmentError(
                    path, loc.offset, "Expected value record, got tombstone"
                )
            return val

    def set(self, key: str, value: str) -> None:
        self._ensure_open()
        self._validate_key(key)
        if not isinstance(value, str):
            raise TypeError(f"Value must be str, got {type(value).__name__}")
        blob = encode_record(key, value)
        self._prepare_write(len(blob))
        offset = self._active_segment.append(blob)
        self._index.put(
            key, Location(self._active_segment.seg_id, offset), tombstone=False
        )
        self._total_records += 1

    def get(self, key: str) -> str | None:
        self._ensure_open()
        self._validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return None
        return self._read_value_at(loc)

    def delete(self, key: str) -> bool:
        self._ensure_open()
        self._validate_key(key)
        loc = self._index.get(key)
        if loc is None:
            return False
        blob = encode_record(key, None)
        self._prepare_write(len(blob))
        offset = self._active_segment.append(blob)
        self._index.put(
            key, Location(self._active_segment.seg_id, offset), tombstone=True
        )
        self._total_records += 1
        return True

    def keys(self) -> list[str]:
        self._ensure_open()
        return self._index.live_keys()

    def stats(self) -> Stats:
        self._ensure_open()
        if not self._active_segment._file.closed:
            self._active_segment._file.flush()
        seg_files = self._get_segment_files()
        bytes_on_disk = sum(p.stat().st_size for _, p in seg_files)
        live = len(self._index)
        tombstones = self._index.tombstone_count()
        total = self._total_records
        dead = total - live - tombstones
        return Stats(
            live_keys=live,
            tombstones=tombstones,
            total_records=total,
            dead_records=dead,
            segment_count=len(seg_files),
            bytes_on_disk=bytes_on_disk,
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._active_segment.close()

    def __enter__(self) -> "KVStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
