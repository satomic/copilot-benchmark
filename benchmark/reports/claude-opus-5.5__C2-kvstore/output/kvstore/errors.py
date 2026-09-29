"""Exception hierarchy for kvstore."""

from __future__ import annotations

import os
import pathlib


class KVStoreError(Exception):
    """Base class for every kvstore error."""


class RecordError(KVStoreError):
    """A single record could not be decoded."""


class IncompleteRecordError(RecordError):
    """Fewer bytes are available than the record needs."""


class CorruptRecordError(RecordError):
    """The record bytes are present but invalid."""


class CorruptSegmentError(KVStoreError):
    """A segment file contains a corrupt record."""

    def __init__(self, path: str | os.PathLike, offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(
            f"corrupt record in {self.path.name} at offset {offset}: {reason}"
        )
