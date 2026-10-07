"""Binary record codec."""
from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
HEADER = struct.Struct(">4sBHII")
HEADER_SIZE = HEADER.size  # 15
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
MAX_KEY_LEN = 65535


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a record; ``value=None`` produces a tombstone."""
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= MAX_KEY_LEN:
        raise ValueError("key must be 1..65535 bytes when UTF-8 encoded")
    if value is None:
        flags, value_bytes = FLAG_TOMBSTONE, b""
    else:
        flags, value_bytes = FLAG_VALUE, value.encode("utf-8")
    crc = zlib.crc32(key_bytes + value_bytes)
    header = HEADER.pack(MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def parse_header(buf: bytes, offset: int) -> tuple[int, int, int, int]:
    """Validate the header structure; return (flags, key_len, value_len, crc).

    Raises IncompleteRecordError if the header itself is short, and
    CorruptRecordError for structural problems.
    """
    if len(buf) - offset < HEADER_SIZE:
        raise IncompleteRecordError("incomplete header")
    magic, flags, key_len, value_len, crc = HEADER.unpack_from(buf, offset)
    if magic != MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags 0x{flags:02x}")
    if key_len == 0:
        raise CorruptRecordError("key_len is zero")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with non-zero value_len")
    return flags, key_len, value_len, crc


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]``; return (key, value, total_size)."""
    flags, key_len, value_len, crc = parse_header(buf, offset)
    total = HEADER_SIZE + key_len + value_len
    if len(buf) - offset < total:
        raise IncompleteRecordError("incomplete body")
    start = offset + HEADER_SIZE
    key_bytes = bytes(buf[start:start + key_len])
    value_bytes = bytes(buf[start + key_len:offset + total])
    if zlib.crc32(key_bytes + value_bytes) != crc:
        raise CorruptRecordError("crc mismatch")
    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == FLAG_TOMBSTONE else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid utf-8") from exc
    return key, value, total
