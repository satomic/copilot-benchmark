"""Exception hierarchy for the append-only key-value store."""

from __future__ import annotations

import pathlib


class KVStoreError(Exception):
    """Base error for store, record, and segment failures."""


class RecordError(KVStoreError):
    """A single record could not be decoded."""


class IncompleteRecordError(RecordError):
    """The buffer ends before the record's declared bytes are present."""


class CorruptRecordError(RecordError):
    """The record bytes are complete but illegal."""


class CorruptSegmentError(KVStoreError):
    """A segment contains a corrupt record at a known offset."""

    def __init__(self, path: pathlib.Path, offset: int, reason: str) -> None:
        self.path = pathlib.Path(path)
        self.offset = offset
        self.reason = reason
        super().__init__(f"{self.path.name}: offset {self.offset}: {self.reason}")

    def __str__(self) -> str:
        return f"{self.path.name}: offset {self.offset}: {self.reason}"
