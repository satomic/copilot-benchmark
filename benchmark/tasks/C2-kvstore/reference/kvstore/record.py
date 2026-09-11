"""The on-disk record codec.

Layout, all integers big-endian unsigned::

    0   4  magic      b"KVR1"
    4   1  flags      0x00 value present, 0x01 tombstone
    5   2  key_len    1..65535, UTF-8 byte length
    7   4  value_len  UTF-8 byte length, always 0 for a tombstone
    11  4  crc        crc32 of key_bytes + value_bytes only, never the header
    15  ...           key_bytes then value_bytes
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

__all__ = [
    "MAGIC",
    "HEADER_SIZE",
    "FLAG_VALUE",
    "FLAG_TOMBSTONE",
    "MAX_KEY_BYTES",
    "encode_record",
    "decode_record",
]

MAGIC = b"KVR1"
HEADER_SIZE = 15
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
MAX_KEY_BYTES = 65535

#: magic(4s) flags(B) key_len(H) value_len(I) crc(I) == 15 bytes, big-endian.
_HEADER = struct.Struct(">4sBHII")


def encode_record(key: str, value: str | None) -> bytes:
    """Serialise one record. ``value=None`` produces a tombstone."""
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= MAX_KEY_BYTES:
        raise ValueError(f"key must encode to 1..{MAX_KEY_BYTES} bytes, got {len(key_bytes)}")
    if value is None:
        flags, value_bytes = FLAG_TOMBSTONE, b""
    else:
        flags, value_bytes = FLAG_VALUE, value.encode("utf-8")
    crc = zlib.crc32(key_bytes + value_bytes)
    header = _HEADER.pack(MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]``.

    Returns ``(key, value, total_size)`` with ``value is None`` for a tombstone.
    Raises :class:`IncompleteRecordError` when bytes are missing (an interrupted
    write) and :class:`CorruptRecordError` when the bytes present are wrong.
    """
    if offset + HEADER_SIZE > len(buf):
        raise IncompleteRecordError(
            f"need {HEADER_SIZE} header bytes at {offset}, have {max(0, len(buf) - offset)}"
        )
    magic, flags, key_len, value_len, crc = _HEADER.unpack_from(buf, offset)

    # Structural checks come before the CRC so that a garbage header is reported as
    # what it is rather than as a checksum mismatch.
    if magic != MAGIC:
        raise CorruptRecordError(f"bad magic {magic!r} at offset {offset}")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags {flags:#04x} at offset {offset}")
    if key_len == 0:
        raise CorruptRecordError(f"zero-length key at offset {offset}")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError(
            f"tombstone with value_len={value_len} at offset {offset}"
        )

    body_start = offset + HEADER_SIZE
    total = HEADER_SIZE + key_len + value_len
    if body_start + key_len + value_len > len(buf):
        raise IncompleteRecordError(
            f"need {total} bytes at {offset}, have {len(buf) - offset}"
        )

    key_bytes = buf[body_start : body_start + key_len]
    value_bytes = buf[body_start + key_len : body_start + key_len + value_len]

    # A CRC mismatch means the bytes are all here and simply wrong, so it is never
    # confused with truncation.
    if zlib.crc32(key_bytes + value_bytes) != crc:
        raise CorruptRecordError(f"crc mismatch at offset {offset}")

    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == FLAG_TOMBSTONE else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError(f"invalid utf-8 at offset {offset}: {exc}") from None
    return key, value, total
