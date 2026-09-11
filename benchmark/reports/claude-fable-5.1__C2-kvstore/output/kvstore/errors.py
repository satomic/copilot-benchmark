"""Exception hierarchy for kvstore."""

from __future__ import annotations

import pathlib


class KVStoreError(Exception):
    """Base class for all kvstore errors."""


class RecordError(KVStoreError):
    """Base class for record codec errors."""


class IncompleteRecordError(RecordError):
    """Fewer bytes are available than the record needs (truncated tail)."""


class CorruptRecordError(RecordError):
    """The record bytes are structurally wrong, fail the CRC, or are not UTF-8."""


class CorruptSegmentError(KVStoreError):
    """A segment file contains a corrupt record at a given offset."""

    def __init__(self, path: pathlib.Path, offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"corrupt record in {self.path.name} at offset {offset}: {reason}")
