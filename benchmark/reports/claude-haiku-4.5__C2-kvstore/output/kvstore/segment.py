import pathlib
from collections.abc import Iterator
from .record import decode_record
from .errors import IncompleteRecordError, CorruptSegmentError


class Segment:
    def __init__(self, path: pathlib.Path, seg_id: int) -> None:
        self.path = path
        self._seg_id = seg_id
        self._file = None
        self._size = 0
        
        if path.exists():
            self._size = path.stat().st_size
            self._file = open(path, "r+b")
        else:
            self._file = open(path, "w+b")
    
    @property
    def seg_id(self) -> int:
        return self._seg_id
    
    @property
    def size(self) -> int:
        return self._size
    
    def append(self, blob: bytes) -> int:
        offset = self._size
        self._file.seek(offset)
        self._file.write(blob)
        self._file.flush()
        self._size += len(blob)
        return offset
    
    def scan(self) -> Iterator[tuple[str, str | None, int]]:
        self._file.seek(0)
        offset = 0
        
        while True:
            current_pos = self._file.tell()
            remaining = self._size - current_pos
            
            if remaining < 15:
                break
            
            buf = self._file.read(remaining)
            
            try:
                key, value, record_size = decode_record(buf, 0)
            except IncompleteRecordError:
                break
            except Exception as e:
                raise CorruptSegmentError(
                    self.path,
                    offset,
                    f"decode error: {e}"
                )
            
            yield key, value, offset
            offset += record_size
            self._file.seek(offset)
    
    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
