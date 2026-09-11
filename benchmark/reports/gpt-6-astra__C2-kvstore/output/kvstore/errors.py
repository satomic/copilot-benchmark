from pathlib import Path


class KVStoreError(Exception):
    pass


class RecordError(KVStoreError):
    pass


class IncompleteRecordError(RecordError):
    pass


class CorruptRecordError(RecordError):
    pass


class CorruptSegmentError(KVStoreError):
    def __init__(self, path: str | Path, offset: int, reason: str) -> None:
        self.path = Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"{self.path.name} at offset {offset}: {reason}")
