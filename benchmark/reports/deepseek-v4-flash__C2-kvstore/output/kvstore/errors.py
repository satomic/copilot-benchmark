import pathlib


class KVStoreError(Exception):
    """Base exception for all kvstore errors."""


class RecordError(KVStoreError):
    """Base exception for record encoding/decoding errors."""


class IncompleteRecordError(RecordError):
    """Raised when fewer bytes are available than needed."""


class CorruptRecordError(RecordError):
    """Raised when a record is structurally invalid."""


class CorruptSegmentError(KVStoreError):
    """Raised when a segment contains a corrupt record."""

    def __init__(
        self,
        path: pathlib.Path,
        offset: int,
        reason: str,
    ) -> None:
        super().__init__(f"{path.name}:{offset} ({reason})")
        self.path = path
        self.offset = offset
        self.reason = reason