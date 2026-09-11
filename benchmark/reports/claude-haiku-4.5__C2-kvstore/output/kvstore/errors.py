class KVStoreError(Exception):
    pass


class RecordError(KVStoreError):
    pass


class IncompleteRecordError(RecordError):
    pass


class CorruptRecordError(RecordError):
    pass


class CorruptSegmentError(KVStoreError):
    def __init__(self, path, offset, reason):
        self.path = path
        self.offset = offset
        self.reason = reason
        super().__init__(f"{path.name} at offset {offset}: {reason}")
