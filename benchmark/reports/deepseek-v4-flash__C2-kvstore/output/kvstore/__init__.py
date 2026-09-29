"""kvstore — an append-only key-value store."""

from kvstore.store import KVStore, Stats
from kvstore.index import Index, Location
from kvstore.segment import Segment
from kvstore.compact import compact, CompactionResult
from kvstore.record import encode_record, decode_record
from kvstore.errors import (
    KVStoreError,
    RecordError,
    IncompleteRecordError,
    CorruptRecordError,
    CorruptSegmentError,
)

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