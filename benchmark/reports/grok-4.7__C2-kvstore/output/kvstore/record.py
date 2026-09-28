"""Binary codec for KVR1 records."""

from __future__ import annotations

import struct
import zlib

from kvstore.errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
HEADER_SIZE = 15
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
_HEADER = struct.Struct(">4sBHII")


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a value record, or a tombstone when value is None."""
    if not isinstance(key, str):
        raise TypeError("key must be str")
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= 65535:
        raise ValueError("key UTF-8 length must be in 1..65535")
    flags, value_bytes = _value_bytes(value)
    crc = zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF
    header = _HEADER.pack(MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode one record starting at offset.

    Length is checked before header validity so a short buffer is always
    incomplete, even when the partial bytes would not form a legal header.
    Structural problems are then reported before the CRC, and the CRC before
    UTF-8 decoding.
    """
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError("incomplete record header")
    magic, flags, key_len, value_len, crc = _HEADER.unpack_from(buf, offset)
    total = HEADER_SIZE + key_len + value_len
    if available < total:
        raise IncompleteRecordError("incomplete record body")
    _check_structure(magic, flags, key_len, value_len)
    start = offset + HEADER_SIZE
    payload = buf[start:start + key_len + value_len]
    _check_crc(payload, crc)
    return _decode_text(payload, key_len, flags, total)


def _value_bytes(value: str | None) -> tuple[int, bytes]:
    if value is None:
        return FLAG_TOMBSTONE, b""
    if not isinstance(value, str):
        raise TypeError("value must be str or None")
    return FLAG_VALUE, value.encode("utf-8")


def _check_structure(magic: bytes, flags: int, key_len: int, value_len: int) -> None:
    if magic != MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError("unknown flags")
    if key_len == 0:
        raise CorruptRecordError("key length is zero")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with non-zero value_len")


def _check_crc(payload: bytes, expected: int) -> None:
    actual = zlib.crc32(payload) & 0xFFFFFFFF
    if actual != expected:
        raise CorruptRecordError("crc mismatch")


def _decode_text(payload: bytes, key_len: int, flags: int, total: int) -> tuple[str, str | None, int]:
    try:
        key = payload[:key_len].decode("utf-8")
        if flags == FLAG_TOMBSTONE:
            return key, None, total
        value = payload[key_len:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid utf-8") from exc
    return key, value, total
