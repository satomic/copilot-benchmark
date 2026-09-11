import dataclasses
import os
import pathlib
import re

from .record import encode_record
from .segment import Segment
from .index import Index, Location
from .errors import CorruptSegmentError


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
        if not isinstance(max_segment_bytes, int) or max_segment_bytes < 16:
            raise ValueError("max_segment_bytes must be an int >= 16")
        
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._max_segment_bytes = max_segment_bytes
        self._index = Index()
        self._segments: dict[int, Segment] = {}
        self._active_seg: Segment | None = None
        self._closed = False
        
        self._recover()
    
    def _recover(self) -> None:
        seg_files = sorted(
            f for f in self.root.iterdir()
            if re.match(r"^\d{6}\.seg$", f.name)
        )
        
        for seg_file in seg_files:
            seg_id = int(seg_file.stem)
            segment = Segment(seg_file, seg_id)
            self._segments[seg_id] = segment
            
            try:
                for key, value, offset in segment.scan():
                    is_tombstone = value is None
                    self._index.put(
                        key,
                        Location(seg_id, offset),
                        tombstone=is_tombstone
                    )
            except CorruptSegmentError:
                raise
        
        if not self._segments:
            seg_id = 1
            seg_path = self.root / f"{seg_id:06d}.seg"
            self._active_seg = Segment(seg_path, seg_id)
            self._segments[seg_id] = self._active_seg
        else:
            max_id = max(self._segments.keys())
            self._active_seg = self._segments[max_id]
    
    def _check_open(self) -> None:
        if self._closed:
            raise ValueError("store is closed")
    
    def set(self, key: str, value: str) -> None:
        self._check_open()
        
        if not isinstance(key, str):
            raise TypeError("key must be str")
        if not isinstance(value, str):
            raise TypeError("value must be str")
        
        key_bytes = key.encode("utf-8")
        if len(key_bytes) == 0 or len(key_bytes) > 65535:
            raise ValueError(f"key byte length must be in 1..65535")
        
        record = encode_record(key, value)
        self._append_record(key, record, is_tombstone=False)
    
    def get(self, key: str) -> str | None:
        self._check_open()
        
        if not isinstance(key, str):
            raise TypeError("key must be str")
        
        loc = self._index.get(key)
        if loc is None:
            return None
        
        segment = self._segments[loc.seg_id]
        segment._file.seek(loc.offset + 15)
        
        from .record import decode_record, HEADER_SIZE
        segment._file.seek(loc.offset)
        remaining = segment._size - loc.offset
        buf = segment._file.read(remaining)
        
        key_result, value_result, _ = decode_record(buf, 0)
        return value_result
    
    def delete(self, key: str) -> bool:
        self._check_open()
        
        if not isinstance(key, str):
            raise TypeError("key must be str")
        
        if self._index.get(key) is None:
            return False
        
        record = encode_record(key, None)
        self._append_record(key, record, is_tombstone=True)
        return True
    
    def keys(self) -> list[str]:
        self._check_open()
        return self._index.live_keys()
    
    def stats(self) -> Stats:
        self._check_open()
        
        total_records = 0
        for segment in self._segments.values():
            segment._file.seek(0)
            for _ in segment.scan():
                total_records += 1
        
        live_count = len(self._index.live_keys())
        tombstone_count = self._index.tombstone_count()
        dead_count = total_records - live_count - tombstone_count
        
        bytes_on_disk = sum(seg.size for seg in self._segments.values())
        
        return Stats(
            live_keys=live_count,
            tombstones=tombstone_count,
            total_records=total_records,
            dead_records=dead_count,
            segment_count=len(self._segments),
            bytes_on_disk=bytes_on_disk
        )
    
    def close(self) -> None:
        if not self._closed:
            for segment in self._segments.values():
                segment.close()
            self._closed = True
    
    def __enter__(self):
        return self
    
    def __exit__(self, *exc):
        self.close()
    
    def _append_record(self, key: str, record: bytes, is_tombstone: bool) -> None:
        record_size = len(record)
        
        if self._active_seg.size == 0 or \
           self._active_seg.size + record_size <= self._max_segment_bytes:
            offset = self._active_seg.append(record)
            self._index.put(
                key,
                Location(self._active_seg.seg_id, offset),
                tombstone=is_tombstone
            )
        else:
            new_seg_id = self._active_seg.seg_id + 1
            new_seg_path = self.root / f"{new_seg_id:06d}.seg"
            new_segment = Segment(new_seg_path, new_seg_id)
            self._segments[new_seg_id] = new_segment
            self._active_seg = new_segment
            
            offset = new_segment.append(record)
            self._index.put(
                key,
                Location(new_seg_id, offset),
                tombstone=is_tombstone
            )
