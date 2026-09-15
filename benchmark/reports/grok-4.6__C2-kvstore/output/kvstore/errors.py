"""Exception hierarchy for the append-only key-value store."""

from __future__ import annotations

from pathlib import Path


class KVStoreError(Exception):
    """Base error for kvstore failures."""


class RecordError(KVStoreError):
    """A single on-disk record could not be decoded."""


class IncompleteRecordError(RecordError):
    """Not enough bytes are available to form a complete record."""


class CorruptRecordError(RecordError):
    """The bytes are present but the record is structurally invalid."""


class CorruptSegmentError(KVStoreError):
    """A complete record in a segment file is corrupt."""

    def __init__(self, path: Path, offset: int, reason: str) -> None:
        self.path = path if isinstance(path, Path) else Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"{self.path.name} offset {offset}: {reason}")
