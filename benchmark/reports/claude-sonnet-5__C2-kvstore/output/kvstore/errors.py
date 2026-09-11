"""Exception hierarchy for the kvstore package."""

from __future__ import annotations

import pathlib


class KVStoreError(Exception):
    """Base class for all kvstore errors."""


class RecordError(KVStoreError):
    """Base class for record codec errors."""


class IncompleteRecordError(RecordError):
    """Raised when fewer bytes are available than a record needs."""


class CorruptRecordError(RecordError):
    """Raised when a record's bytes are structurally or semantically invalid."""


class CorruptSegmentError(KVStoreError):
    """Raised by Segment.scan when a segment contains a corrupt record.

    Attributes:
        path: the segment file path.
        offset: the byte offset of the bad record within the file.
        reason: a short human-readable explanation.
    """

    def __init__(self, path: pathlib.Path, offset: int, reason: str) -> None:
        self.path = path
        self.offset = offset
        self.reason = reason
        super().__init__(f"corrupt record in {path.name} at offset {offset}: {reason}")

    def __str__(self) -> str:
        return f"corrupt record in {self.path.name} at offset {self.offset}: {self.reason}"
