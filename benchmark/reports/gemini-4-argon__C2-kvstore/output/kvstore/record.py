from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

HEADER_FORMAT = ">4sBHII"
HEADER_SIZE = 15
MAGIC = b"KVR1"
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
MAX_KEY_LEN = 65535
MAX_VALUE_LEN = 0xFFFFFFFF


def validate_key(key: str) -> bytes:
    if not isinstance(key, str):
        raise TypeError("key must be a str")
    try:
        key_bytes = key.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("key must be valid UTF-8") from exc
    if not (1 <= len(key_bytes) <= MAX_KEY_LEN):
        raise ValueError(f"UTF-8 key length must be in 1..{MAX_KEY_LEN}")
    return key_bytes


def encode_record(key: str, value: str | None) -> bytes:
    key_bytes = validate_key(key)
    if value is None:
        flags = FLAG_TOMBSTONE
        value_bytes = b""
    elif isinstance(value, str):
        flags = FLAG_VALUE
        try:
            value_bytes = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("value must be valid UTF-8") from exc
        if len(value_bytes) > MAX_VALUE_LEN:
            raise ValueError("value too large")
    else:
        raise TypeError("value must be a str or None")

    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC,
        flags,
        len(key_bytes),
        len(value_bytes),
        crc,
    )
    return header + key_bytes + value_bytes


def _validate_header(magic: bytes, flags: int, key_len: int, value_len: int) -> None:
    if magic != MAGIC:
        raise CorruptRecordError("invalid magic bytes")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"invalid flags: {flags:#x}")
    if key_len == 0:
        raise CorruptRecordError("key_len cannot be 0")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone record must have value_len == 0")


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError("fewer than 15 bytes available for header")

    magic, flags, key_len, value_len, expected_crc = struct.unpack_from(
        HEADER_FORMAT, buf, offset
    )
    _validate_header(magic, flags, key_len, value_len)

    total_size = HEADER_SIZE + key_len + value_len
    if available < total_size:
        raise IncompleteRecordError("fewer bytes available than key_len + value_len")

    key_start = offset + HEADER_SIZE
    val_start = key_start + key_len
    val_end = val_start + value_len
    key_bytes = bytes(buf[key_start:val_start])
    value_bytes = bytes(buf[val_start:val_end])

    actual_crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise CorruptRecordError("CRC32 mismatch")

    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == FLAG_TOMBSTONE else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid UTF-8 in key or value") from exc

    return key, value, total_size
