"""Binary record codec.

Layout (all integers big-endian unsigned)::

    0  4  magic      b"KVR1"
    4  1  flags      0x00 value present, 0x01 tombstone
    5  2  key_len    UTF-8 byte length of the key, 1..65535
    7  4  value_len  UTF-8 byte length of the value
    11 4  crc        zlib.crc32(key_bytes + value_bytes)
    15 .. key_bytes then value_bytes
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC: bytes = b"KVR1"
HEADER_FORMAT: str = "!4sBHII"
HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 15
FLAG_VALUE: int = 0x00
FLAG_TOMBSTONE: int = 0x01
MAX_KEY_BYTES: int = 65535

__all__ = [
    "MAGIC",
    "HEADER_SIZE",
    "FLAG_VALUE",
    "FLAG_TOMBSTONE",
    "MAX_KEY_BYTES",
    "encode_record",
    "decode_record",
]


def encode_record(key: str, value: str | None) -> bytes:
    """Encode one record. ``value=None`` produces a tombstone."""
    if not isinstance(key, str):
        raise TypeError("key must be str")
    if value is not None and not isinstance(value, str):
        raise TypeError("value must be str or None")
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= MAX_KEY_BYTES:
        raise ValueError(
            f"key must encode to 1..{MAX_KEY_BYTES} bytes, got {len(key_bytes)}"
        )
    value_bytes = b"" if value is None else value.encode("utf-8")
    flags = FLAG_TOMBSTONE if value is None else FLAG_VALUE
    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    header = struct.pack(
        HEADER_FORMAT, MAGIC, flags, len(key_bytes), len(value_bytes), crc
    )
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]``.

    Returns ``(key, value, total_size)`` with ``value`` set to ``None`` for a
    tombstone. Structural checks come first, then the CRC, then UTF-8 decoding.
    """
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError(
            f"need {HEADER_SIZE} header bytes, only {max(available, 0)} available"
        )
    magic, flags, key_len, value_len, crc = struct.unpack_from(
        HEADER_FORMAT, buf, offset
    )
    if magic != MAGIC:
        raise CorruptRecordError(f"bad magic {magic!r}")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags 0x{flags:02x}")
    if key_len == 0:
        raise CorruptRecordError("key_len is zero")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError(f"tombstone with value_len {value_len}")
    body_size = key_len + value_len
    total_size = HEADER_SIZE + body_size
    if available < total_size:
        raise IncompleteRecordError(
            f"need {total_size} bytes, only {available} available"
        )
    body_start = offset + HEADER_SIZE
    body = bytes(buf[body_start : body_start + body_size])
    if (zlib.crc32(body) & 0xFFFFFFFF) != crc:
        raise CorruptRecordError("crc mismatch")
    try:
        key = body[:key_len].decode("utf-8")
        value = None if flags == FLAG_TOMBSTONE else body[key_len:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError(f"invalid utf-8: {exc}") from exc
    return key, value, total_size
