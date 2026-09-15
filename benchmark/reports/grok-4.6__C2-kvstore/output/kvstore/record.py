"""Binary record codec: 15-byte header plus UTF-8 key and value."""

from __future__ import annotations

import struct
import zlib

from kvstore.errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
HEADER_SIZE = 15
HEADER_STRUCT = struct.Struct(">4sBHII")


def encode_record(key: str, value: str | None) -> bytes:
    key_bytes = key.encode("utf-8")
    if value is None:
        flags = FLAG_TOMBSTONE
        value_bytes = b""
    else:
        flags = FLAG_VALUE
        value_bytes = value.encode("utf-8")
    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    header = HEADER_STRUCT.pack(MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError("truncated header")
    magic, flags, key_len, value_len, crc = HEADER_STRUCT.unpack_from(buf, offset)
    total = HEADER_SIZE + key_len + value_len
    if available < total:
        raise IncompleteRecordError("truncated payload")
    _check_structure(magic, flags, key_len, value_len)
    start = offset + HEADER_SIZE
    key_bytes = buf[start : start + key_len]
    value_bytes = buf[start + key_len : start + key_len + value_len]
    actual = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    if actual != crc:
        raise CorruptRecordError("crc mismatch")
    key, value_str = _decode_utf8(key_bytes, value_bytes)
    return key, (None if flags == FLAG_TOMBSTONE else value_str), total


def _check_structure(magic: bytes, flags: int, key_len: int, value_len: int) -> None:
    if magic != MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError("unknown flags")
    if key_len == 0:
        raise CorruptRecordError("empty key")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with value")


def _decode_utf8(key_bytes: bytes, value_bytes: bytes) -> tuple[str, str]:
    try:
        return key_bytes.decode("utf-8"), value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid utf-8") from exc
