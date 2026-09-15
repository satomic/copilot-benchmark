import pathlib


class KVStoreError(Exception):
    """Base exception for all kvstore errors."""


class RecordError(KVStoreError):
    """Base exception for record encoding and decoding errors."""


class IncompleteRecordError(RecordError):
    """Raised when a record has fewer bytes available than needed."""


class CorruptRecordError(RecordError):
    """Raised when a record has invalid magic, flags, CRC, or UTF-8."""


class CorruptSegmentError(KVStoreError):
    """Raised when a segment contains a corrupt record."""

    def __init__(self, path: pathlib.Path | str, offset: int, reason: str) -> None:
        self.path: pathlib.Path = pathlib.Path(path)
        self.offset: int = offset
        self.reason: str = reason
        super().__init__(
            f"Corrupt segment {self.path.name} at offset {self.offset}: {self.reason}"
        )
