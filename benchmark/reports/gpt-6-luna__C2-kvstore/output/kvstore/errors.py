"""Exceptions raised by the key-value store."""

from pathlib import Path


class KVStoreError(Exception):
    """Base exception for key-value store failures."""


class RecordError(KVStoreError):
    """Base exception for record codec failures."""


class IncompleteRecordError(RecordError):
    """A record is cut off before its declared end."""


class CorruptRecordError(RecordError):
    """A record violates the binary format."""


class CorruptSegmentError(KVStoreError):
    """A segment contains a corrupt record."""

    def __init__(self, path: str | Path, offset: int, reason: str) -> None:
        self.path = Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"Corrupt segment {self.path.name} at offset {offset}: {reason}")
