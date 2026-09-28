"""Binary record encoding and decoding."""

import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

_HEADER = struct.Struct(">4sB H I I")
_MAGIC = b"KVR1"


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a key/value pair, using ``None`` to encode a tombstone."""
    if not isinstance(key, str):
        raise TypeError("key must be a string")
    if value is not None and not isinstance(value, str):
        raise TypeError("value must be a string or None")
    key_bytes = key.encode("utf-8")
    value_bytes = b"" if value is None else value.encode("utf-8")
    if not 1 <= len(key_bytes) <= 65535:
        raise ValueError("UTF-8 key length must be in 1..65535 bytes")
    if len(value_bytes) > 0xFFFFFFFF:
        raise ValueError("UTF-8 value is too long")
    flags = 1 if value is None else 0
    body = key_bytes + value_bytes
    return _HEADER.pack(_MAGIC, flags, len(key_bytes), len(value_bytes), zlib.crc32(body)) + body


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode one record from ``buf`` at ``offset``."""
    if not isinstance(buf, bytes):
        raise TypeError("buf must be bytes")
    if offset < 0:
        raise ValueError("offset must not be negative")
    if len(buf) - offset < _HEADER.size:
        raise IncompleteRecordError("record header is incomplete")
    magic, flags, key_len, value_len, checksum = _HEADER.unpack_from(buf, offset)
    if magic != _MAGIC:
        raise CorruptRecordError("bad record magic")
    if flags not in (0, 1):
        raise CorruptRecordError("unknown record flags")
    if key_len == 0:
        raise CorruptRecordError("key length is zero")
    if flags == 1 and value_len != 0:
        raise CorruptRecordError("tombstone has a value")
    total = _HEADER.size + key_len + value_len
    if len(buf) - offset < total:
        raise IncompleteRecordError("record body is incomplete")
    start = offset + _HEADER.size
    key_bytes = buf[start : start + key_len]
    value_bytes = buf[start + key_len : offset + total]
    if zlib.crc32(key_bytes + value_bytes) != checksum:
        raise CorruptRecordError("record CRC mismatch")
    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == 1 else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("record contains invalid UTF-8") from exc
    return key, value, total
