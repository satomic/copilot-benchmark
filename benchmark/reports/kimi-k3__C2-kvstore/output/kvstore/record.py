"""Binary record codec.

Layout (all integers big-endian unsigned)::

    0   4  magic      b"KVR1"
    4   1  flags      0x00 = value present, 0x01 = tombstone
    5   2  key_len    UTF-8 byte length of key, 1..65535
    7   4  value_len  UTF-8 byte length of value
    11  4  crc        CRC32 of key_bytes + value_bytes (header NOT covered)
    15  .. key_bytes, then value_bytes

Total record size is 15 + key_len + value_len.
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
HEADER_SIZE = 15
_HEADER = struct.Struct(">4sBHII")


def encode_record(key: str, value: str | None) -> bytes:
    """Encode one record. ``value=None`` produces a tombstone."""
    key_bytes = key.encode("utf-8")
    if value is None:
        flags = FLAG_TOMBSTONE
        value_bytes = b""
    else:
        flags = FLAG_VALUE
        value_bytes = value.encode("utf-8")
    crc = zlib.crc32(key_bytes + value_bytes)
    header = _HEADER.pack(MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]``.

    Returns ``(key, value, total_size)``; ``value`` is ``None`` for a
    tombstone.  Raises ``IncompleteRecordError`` when too few bytes are
    available, ``CorruptRecordError`` for anything else that is wrong.
    Checks run in the order: structure, then CRC, then UTF-8.
    """
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError(
            f"need {HEADER_SIZE} header bytes, only {max(available, 0)} available"
        )
    magic, flags, key_len, value_len, crc = _HEADER.unpack_from(buf, offset)
    _check_structure(magic, flags, key_len, value_len)
    total = HEADER_SIZE + key_len + value_len
    if available < total:
        raise IncompleteRecordError(
            f"need {total} bytes, only {available} available"
        )
    key_start = offset + HEADER_SIZE
    value_start = key_start + key_len
    key_bytes = bytes(buf[key_start:value_start])
    value_bytes = bytes(buf[value_start:offset + total])
    if zlib.crc32(key_bytes + value_bytes) != crc:
        raise CorruptRecordError("crc mismatch")
    try:
        key = key_bytes.decode("utf-8")
        value = value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError(f"invalid utf-8: {exc}") from exc
    return key, (None if flags == FLAG_TOMBSTONE else value), total


def _check_structure(magic: bytes, flags: int, key_len: int, value_len: int) -> None:
    if magic != MAGIC:
        raise CorruptRecordError(f"bad magic {magic!r}")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags {flags:#04x}")
    if key_len == 0:
        raise CorruptRecordError("key_len must be >= 1")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone must have value_len == 0")
