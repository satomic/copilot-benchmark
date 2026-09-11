"""Exception hierarchy for the kvstore package."""

from __future__ import annotations

import pathlib

__all__ = [
    "KVStoreError",
    "RecordError",
    "IncompleteRecordError",
    "CorruptRecordError",
    "CorruptSegmentError",
]


class KVStoreError(Exception):
    """Base class for every error raised by this package."""


class RecordError(KVStoreError):
    """A problem decoding a single record."""


class IncompleteRecordError(RecordError):
    """Fewer bytes are available than the record needs.

    This is the signature of a write that was interrupted, so callers scanning a
    segment treat it as a clean end of file rather than as damage.
    """


class CorruptRecordError(RecordError):
    """The bytes are all present but they do not describe a valid record."""


class CorruptSegmentError(KVStoreError):
    """A segment holds a record that is damaged rather than merely truncated."""

    def __init__(self, path: pathlib.Path, offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"{self.path.name}: corrupt record at offset {offset}: {reason}")
