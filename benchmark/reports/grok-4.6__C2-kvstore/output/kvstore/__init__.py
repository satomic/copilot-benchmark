"""Public surface of the append-only key-value store."""

from kvstore.compact import CompactionResult, compact
from kvstore.errors import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    KVStoreError,
    RecordError,
)
from kvstore.index import Index, Location
from kvstore.record import decode_record, encode_record
from kvstore.segment import Segment
from kvstore.store import KVStore, Stats

__all__ = [
    "KVStore",
    "Stats",
    "Index",
    "Location",
    "Segment",
    "CompactionResult",
    "compact",
    "encode_record",
    "decode_record",
    "KVStoreError",
    "RecordError",
    "IncompleteRecordError",
    "CorruptRecordError",
    "CorruptSegmentError",
]
