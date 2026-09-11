"""Binary codec for a single append-only log record.

Record layout (all integers big-endian unsigned):

    offset  size  field
    0       4     magic       b"KVR1"
    4       1     flags       0x00 = value present, 0x01 = tombstone
    5       2     key_len     UTF-8 byte length of the key, 1..65535
    7       4     value_len   UTF-8 byte length of the value
    11      4     crc         CRC32 of key_bytes + value_bytes
    15      key_len    key_bytes
    15+key_len value_len  value_bytes
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

_MAGIC = b"KVR1"
_HEADER_STRUCT = struct.Struct(">4sBHIL")
_HEADER_SIZE = _HEADER_STRUCT.size  # 15
_FLAG_VALUE = 0x00
_FLAG_TOMBSTONE = 0x01


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a key/value pair (or tombstone, when value is None) into a record."""
    key_bytes = key.encode("utf-8")
    if not (1 <= len(key_bytes) <= 65535):
        raise ValueError("key byte length must be in 1..65535")
    if value is None:
        flags = _FLAG_TOMBSTONE
        value_bytes = b""
    else:
        flags = _FLAG_VALUE
        value_bytes = value.encode("utf-8")
    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    header = _HEADER_STRUCT.pack(_MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode a record starting at buf[offset].

    Returns (key, value, total_size). value is None for a tombstone.
    Raises IncompleteRecordError if not enough bytes are available, or
    CorruptRecordError if the bytes are structurally or semantically invalid.
    """
    available = len(buf) - offset
    if available < _HEADER_SIZE:
        raise IncompleteRecordError("not enough bytes for header")
    magic, flags, key_len, value_len, crc = _HEADER_STRUCT.unpack_from(buf, offset)
    if magic != _MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (_FLAG_VALUE, _FLAG_TOMBSTONE):
        raise CorruptRecordError("unknown flags")
    if key_len == 0:
        raise CorruptRecordError("key_len is zero")
    if flags == _FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with non-zero value_len")
    total_size = _HEADER_SIZE + key_len + value_len
    if available < total_size:
        raise IncompleteRecordError("not enough bytes for key/value")
    key_bytes = buf[offset + _HEADER_SIZE:offset + _HEADER_SIZE + key_len]
    value_bytes = buf[offset + _HEADER_SIZE + key_len:offset + total_size]
    actual_crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    if actual_crc != crc:
        raise CorruptRecordError("crc mismatch")
    try:
        key = key_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("key is not valid utf-8") from exc
    if flags == _FLAG_TOMBSTONE:
        return key, None, total_size
    try:
        value = value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("value is not valid utf-8") from exc
    return key, value, total_size
