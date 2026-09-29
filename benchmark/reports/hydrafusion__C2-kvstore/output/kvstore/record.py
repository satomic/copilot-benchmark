import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError


MAGIC = b"KVR1"
HEADER_SIZE = 15
_HEADER = struct.Struct(">4sBHII")


def _encode_key(key: str) -> bytes:
    if not isinstance(key, str):
        raise TypeError("key must be a str")
    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= 65535:
        raise ValueError("key UTF-8 length must be between 1 and 65535 bytes")
    return key_bytes


def encode_record(key: str, value: str | None) -> bytes:
    key_bytes = _encode_key(key)
    if value is not None and not isinstance(value, str):
        raise TypeError("value must be a str or None")
    value_bytes = b"" if value is None else value.encode("utf-8")
    flags = 1 if value is None else 0
    payload = key_bytes + value_bytes
    header = _HEADER.pack(
        MAGIC, flags, len(key_bytes), len(value_bytes), zlib.crc32(payload)
    )
    return header + payload


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative int")
    if len(buf) - offset < HEADER_SIZE:
        raise IncompleteRecordError("incomplete record header")
    magic, flags, key_len, value_len, expected_crc = _HEADER.unpack_from(buf, offset)
    if magic != MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (0, 1):
        raise CorruptRecordError("unknown flags")
    if key_len == 0:
        raise CorruptRecordError("key length is zero")
    if flags == 1 and value_len != 0:
        raise CorruptRecordError("tombstone has a value")
    total_size = HEADER_SIZE + key_len + value_len
    if len(buf) - offset < total_size:
        raise IncompleteRecordError("incomplete record body")
    start = offset + HEADER_SIZE
    key_bytes = buf[start : start + key_len]
    value_bytes = buf[start + key_len : offset + total_size]
    if zlib.crc32(key_bytes + value_bytes) != expected_crc:
        raise CorruptRecordError("CRC mismatch")
    try:
        key = key_bytes.decode("utf-8")
        value = None if flags == 1 else value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid UTF-8") from exc
    return key, value, total_size
