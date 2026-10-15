from __future__ import annotations

import pathlib


class KVStoreError(Exception):
    """Base exception for all kvstore errors."""


class RecordError(KVStoreError):
    """Base exception for record encoding/decoding errors."""


class IncompleteRecordError(RecordError):
    """Raised when a buffer ends before a complete record can be read."""


class CorruptRecordError(RecordError):
    """Raised when a record violates structural, CRC, or UTF-8 invariants."""


class CorruptSegmentError(KVStoreError):
    """Raised when scanning a segment encounters a corrupt record."""

    def __init__(self, path: pathlib.Path | str, offset: int, reason: str) -> None:
        self.path: pathlib.Path = pathlib.Path(path)
        self.offset: int = offset
        self.reason: str = reason
        super().__init__(f"{self.path.name} at offset {self.offset}: {self.reason}")
