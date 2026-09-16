from pathlib import Path
from typing import Any


class KVStoreError(Exception):
    """Base exception for the store."""


class RecordError(KVStoreError):
    """Base exception for malformed record bytes."""


class IncompleteRecordError(RecordError):
    """A record is incomplete at the end of a buffer."""


class CorruptRecordError(RecordError):
    """A complete record is malformed."""


class CorruptSegmentError(KVStoreError):
    """A segment contains a corrupt record."""

    def __init__(self, path: Path, offset: int, reason: str) -> None:
        self.path = Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"{self.path.name} at offset {offset}: {reason}")
