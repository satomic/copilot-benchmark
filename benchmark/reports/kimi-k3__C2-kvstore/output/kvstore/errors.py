"""Exception hierarchy for kvstore."""

from __future__ import annotations

import pathlib


class KVStoreError(Exception):
    """Base class for all kvstore errors."""


class RecordError(KVStoreError):
    """A single record could not be encoded or decoded."""


class IncompleteRecordError(RecordError):
    """Fewer bytes are available than the record needs (truncated write)."""


class CorruptRecordError(RecordError):
    """A record is structurally invalid or fails its integrity check."""


class CorruptSegmentError(KVStoreError):
    """A segment file contains a corrupt record."""

    def __init__(self, path: pathlib.Path, offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(
            f"{self.path.name}: corrupt record at offset {offset}: {reason}"
        )
