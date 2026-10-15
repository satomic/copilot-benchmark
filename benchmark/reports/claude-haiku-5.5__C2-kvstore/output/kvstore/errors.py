"""Exception hierarchy for kvstore."""

from __future__ import annotations

import os
import pathlib


class KVStoreError(Exception):
    """Base class for all kvstore errors."""


class RecordError(KVStoreError):
    """A record could not be decoded."""


class IncompleteRecordError(RecordError):
    """The buffer ends before the record does (typically a torn write)."""


class CorruptRecordError(RecordError):
    """The record bytes are structurally or cryptographically invalid."""


class CorruptSegmentError(KVStoreError):
    """A segment file contains a corrupt record at a known offset."""

    def __init__(self, path: str | os.PathLike[str], offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"{self.path}: corrupt record at offset {offset}: {reason}")
