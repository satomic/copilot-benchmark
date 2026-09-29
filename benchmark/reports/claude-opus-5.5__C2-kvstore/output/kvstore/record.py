"""Binary record codec.

Layout (big-endian): magic(4) flags(1) key_len(2) value_len(4) crc(4) key value.
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
HEADER = struct.Struct(">4sBHII")
HEADER_SIZE = HEADER.size
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
MAX_KEY_BYTES = 0xFFFF
MAX_VALUE_BYTES = 0xFFFFFFFF


def encode_key(key: str) -> bytes:
    """Validate ``key`` and return its UTF-8 bytes."""
    if not isinstance(key, str):
        raise TypeError(f"key must be str, not {type(key).__name__}")
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= MAX_KEY_BYTES:
        raise ValueError(
            f"key must encode to 1..{MAX_KEY_BYTES} UTF-8 bytes, got {len(key_bytes)}"
        )
    return key_bytes


def encode_value(value: str) -> bytes:
    """Validate ``value`` and return its UTF-8 bytes."""
    if not isinstance(value, str):
        raise TypeError(f"value must be str, not {type(value).__name__}")
    value_bytes = value.encode("utf-8")
    if len(value_bytes) > MAX_VALUE_BYTES:
        raise ValueError("value is too large")
    return value_bytes


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a record; ``value=None`` encodes a tombstone."""
    key_bytes = encode_key(key)
    if value is None:
        flags, value_bytes = FLAG_TOMBSTONE, b""
    else:
        flags, value_bytes = FLAG_VALUE, encode_value(value)
    body = key_bytes + value_bytes
    header = HEADER.pack(MAGIC, flags, len(key_bytes), len(value_bytes), zlib.crc32(body))
    return header + body


def record_size(buf: bytes, offset: int = 0) -> int:
    """Return the total size of the record at ``offset`` after structural checks."""
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if len(buf) - offset < HEADER_SIZE:
        raise IncompleteRecordError("incomplete header")
    magic, flags, key_len, value_len, _ = HEADER.unpack_from(buf, offset)
    if magic != MAGIC:
        raise CorruptRecordError(f"bad magic {bytes(magic)!r}")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags 0x{flags:02x}")
    if key_len == 0:
        raise CorruptRecordError("key_len is 0")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with non-zero value_len")
    return HEADER_SIZE + key_len + value_len


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]`` into ``(key, value, total_size)``."""
    total = record_size(buf, offset)
    if len(buf) - offset < total:
        raise IncompleteRecordError("incomplete body")
    _, flags, key_len, _, crc = HEADER.unpack_from(buf, offset)
    body = bytes(buf[offset + HEADER_SIZE : offset + total])
    if zlib.crc32(body) != crc:
        raise CorruptRecordError("CRC mismatch")
    try:
        key = body[:key_len].decode("utf-8")
        value = body[key_len:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError(f"invalid UTF-8: {exc}") from None
    return key, (None if flags == FLAG_TOMBSTONE else value), total
