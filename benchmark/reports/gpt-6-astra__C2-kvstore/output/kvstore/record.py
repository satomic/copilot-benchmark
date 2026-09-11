import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError


_HEADER = struct.Struct(">4sBHII")
_HEADER_SIZE = _HEADER.size


def _encode_key(key: str) -> bytes:
    if not isinstance(key, str):
        raise TypeError("key must be a str")
    encoded = key.encode("utf-8")
    if not 1 <= len(encoded) <= 65535:
        raise ValueError("key must contain 1..65535 UTF-8 bytes")
    return encoded


def encode_record(key: str, value: str | None) -> bytes:
    key_bytes = _encode_key(key)
    if value is not None and not isinstance(value, str):
        raise TypeError("value must be a str or None")
    value_bytes = b"" if value is None else value.encode("utf-8")
    if len(value_bytes) > 0xFFFFFFFF:
        raise ValueError("value exceeds the record's UTF-8 byte limit")
    payload = key_bytes + value_bytes
    header = _HEADER.pack(
        b"KVR1", int(value is None), len(key_bytes), len(value_bytes),
        zlib.crc32(payload),
    )
    return header + payload


def _decode_header(buf: bytes, offset: int = 0) -> tuple[int, int, int, int]:
    if not isinstance(offset, int) or offset < 0:
        raise CorruptRecordError("offset must be a nonnegative integer")
    if len(buf) - offset < _HEADER_SIZE:
        raise IncompleteRecordError("incomplete record header")
    magic, flags, key_len, value_len, crc = _HEADER.unpack_from(buf, offset)
    if magic != b"KVR1":
        raise CorruptRecordError("bad magic")
    if flags not in (0, 1):
        raise CorruptRecordError("unknown flags")
    if key_len == 0:
        raise CorruptRecordError("empty key")
    if flags == 1 and value_len != 0:
        raise CorruptRecordError("tombstone has a value")
    return flags, key_len, value_len, crc


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    flags, key_len, value_len, crc = _decode_header(buf, offset)
    total_size = _HEADER_SIZE + key_len + value_len
    if len(buf) - offset < total_size:
        raise IncompleteRecordError("incomplete record payload")
    payload = buf[offset + _HEADER_SIZE:offset + total_size]
    if zlib.crc32(payload) != crc:
        raise CorruptRecordError("CRC mismatch")
    try:
        key = payload[:key_len].decode("utf-8")
        value = None if flags == 1 else payload[key_len:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid UTF-8") from exc
    return key, value, total_size
