"""Exception hierarchy for :mod:`kvstore`."""

from __future__ import annotations

import pathlib


class KVStoreError(Exception):
    """Base class for every error raised by this package."""


class RecordError(KVStoreError):
    """Base class for problems with a single record."""


class IncompleteRecordError(RecordError):
    """Fewer bytes are available than the record needs (a partial write)."""


class CorruptRecordError(RecordError):
    """The record's bytes are all present but they are not valid."""


class CorruptSegmentError(KVStoreError):
    """A segment file contains a corrupt record at a known offset."""

    def __init__(self, path: pathlib.Path, offset: int, reason: str) -> None:
        self.path: pathlib.Path = pathlib.Path(path)
        self.offset: int = offset
        self.reason: str = reason
        super().__init__(
            f"corrupt record in {self.path.name} at offset {offset}: {reason}"
        )
