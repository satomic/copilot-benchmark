"""Binary record codec.

Layout (big-endian): magic(4) flags(1) key_len(2) value_len(4) crc(4), then key
bytes and value bytes. The CRC covers key bytes + value bytes only.
"""

from __future__ import annotations

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
MAX_KEY_BYTES = 65535
MAX_VALUE_BYTES = 0xFFFFFFFF
HEADER = struct.Struct(">4sBHII")
HEADER_SIZE = HEADER.size  # 15


def encode_key(key: object) -> bytes:
    """Return the UTF-8 bytes of ``key``, validating its type and byte length."""
    if not isinstance(key, str):
        raise TypeError(f"key must be str, not {type(key).__name__}")
    raw = key.encode("utf-8")
    if not 1 <= len(raw) <= MAX_KEY_BYTES:
        raise ValueError(f"key must encode to 1..{MAX_KEY_BYTES} bytes, got {len(raw)}")
    return raw


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a complete record. ``value=None`` produces a tombstone."""
    key_bytes = encode_key(key)
    if value is None:
        flags, value_bytes = FLAG_TOMBSTONE, b""
    else:
        if not isinstance(value, str):
            raise TypeError(f"value must be str or None, not {type(value).__name__}")
        flags, value_bytes = FLAG_VALUE, value.encode("utf-8")
        if len(value_bytes) > MAX_VALUE_BYTES:
            raise ValueError("value exceeds the 4-byte value_len field")
    crc = zlib.crc32(key_bytes + value_bytes)
    header = HEADER.pack(MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + key_bytes + value_bytes


def _check_header(magic: bytes, flags: int, key_len: int, value_len: int) -> None:
    if magic != MAGIC:
        raise CorruptRecordError(f"bad magic {magic!r}")
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags 0x{flags:02x}")
    if key_len == 0:
        raise CorruptRecordError("key_len is 0")
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError(f"tombstone with value_len {value_len}")


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode the record at ``buf[offset]``.

    Returns ``(key, value, total_size)``; ``value`` is ``None`` for a tombstone.
    Header structure is validated first, then completeness, then the CRC, then UTF-8.
    """
    available = len(buf) - offset
    if available < HEADER_SIZE:
        raise IncompleteRecordError(f"need {HEADER_SIZE} header bytes, have {max(available, 0)}")
    magic, flags, key_len, value_len, crc = HEADER.unpack_from(buf, offset)
    _check_header(magic, flags, key_len, value_len)
    total = HEADER_SIZE + key_len + value_len
    if available < total:
        raise IncompleteRecordError(f"record needs {total} bytes, have {available}")
    body = offset + HEADER_SIZE
    key_bytes = bytes(buf[body:body + key_len])
    value_bytes = bytes(buf[body + key_len:body + key_len + value_len])
    if zlib.crc32(key_bytes + value_bytes) != crc:
        raise CorruptRecordError("CRC mismatch")
    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == FLAG_TOMBSTONE else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError(f"invalid UTF-8: {exc}") from exc
    return key, value, total
