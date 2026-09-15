import pathlib


class KVStoreError(Exception):
    pass


class RecordError(KVStoreError):
    pass


class IncompleteRecordError(RecordError):
    pass


class CorruptRecordError(RecordError):
    pass


class CorruptSegmentError(KVStoreError):
    def __init__(
        self,
        path: pathlib.Path | str,
        offset: int,
        reason: str | None = None,
    ) -> None:
        self.path = pathlib.Path(path)
        self.offset = int(offset)
        self.reason = reason

    def __str__(self) -> str:
        if self.reason is None:
            return f"{self.path.name} at offset {self.offset}"
        return f"{self.path.name} at offset {self.offset}: {self.reason}"
