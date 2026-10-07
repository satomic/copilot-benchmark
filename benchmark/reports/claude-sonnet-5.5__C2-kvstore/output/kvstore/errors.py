"""Exception hierarchy for kvstore."""
from __future__ import annotations

import os
import pathlib


class KVStoreError(Exception):
    """Base class for all kvstore errors."""


class RecordError(KVStoreError):
    """A record could not be decoded."""


class IncompleteRecordError(RecordError):
    """Not enough bytes are available for the record."""


class CorruptRecordError(RecordError):
    """The record bytes are present but wrong."""


class CorruptSegmentError(KVStoreError):
    """A segment file contains a corrupt record."""

    def __init__(self, path: str | os.PathLike, offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"corrupt segment {self.path.name} at offset {offset}: {reason}")
