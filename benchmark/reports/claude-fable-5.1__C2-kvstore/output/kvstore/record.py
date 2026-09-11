"""Binary record codec.

Layout (all integers big-endian unsigned):
    magic(4) flags(1) key_len(2) value_len(4) crc(4) key_bytes value_bytes
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
HEADER_FMT = ">4sBHII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 15


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a key/value pair; ``value=None`` produces a tombstone."""
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= 0xFFFF:
        raise ValueError("key must encode to 1..65535 UTF-8 bytes")
    if value is None:
        flags = FLAG_TOMBSTONE
        value_bytes = b""
    else:
        flags = FLAG_VALUE
        value_bytes = value.encode("utf-8")
    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    header = struct.pack(HEADER_FMT, MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]``; returns ``(key, value, total_size)``."""
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError("incomplete header")
    magic, flags, key_len, value_len, crc = struct.unpack_from(HEADER_FMT, buf, offset)
    if magic != MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags 0x{flags:02x}")
    if key_len == 0:
        raise CorruptRecordError("key_len == 0")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with non-zero value_len")
    total = HEADER_SIZE + key_len + value_len
    if available < total:
        raise IncompleteRecordError("incomplete body")
    start = offset + HEADER_SIZE
    key_bytes = buf[start : start + key_len]
    value_bytes = buf[start + key_len : offset + total]
    if zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF != crc:
        raise CorruptRecordError("crc mismatch")
    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == FLAG_TOMBSTONE else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid utf-8") from exc
    return key, value, total
