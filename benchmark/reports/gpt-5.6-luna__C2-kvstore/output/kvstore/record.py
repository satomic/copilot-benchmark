import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

_HEADER = 15
_MAGIC = b"KVR1"


def _key_bytes(key: str) -> bytes:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    data = key.encode("utf-8")
    if not 1 <= len(data) <= 65535:
        raise ValueError("key UTF-8 length must be 1..65535")
    return data


def encode_record(key: str, value: str | None) -> bytes:
    key_data = _key_bytes(key)
    if value is not None and not isinstance(value, str):
        raise TypeError("value must be str or None")
    value_data = b"" if value is None else value.encode("utf-8")
    flags = 1 if value is None else 0
    header = struct.pack(">4sBHI I", _MAGIC, flags, len(key_data), len(value_data),
                         zlib.crc32(key_data + value_data) & 0xffffffff)
    return header + key_data + value_data


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    if offset < 0 or offset > len(buf):
        raise IncompleteRecordError("record header is incomplete")
    if len(buf) - offset < _HEADER:
        raise IncompleteRecordError("record header is incomplete")
    magic, flags, key_len, value_len, crc = struct.unpack_from(">4sBHI I", buf, offset)
    if magic != _MAGIC:
        raise CorruptRecordError("bad magic")
    if flags not in (0, 1):
        raise CorruptRecordError("unknown flags")
    if key_len == 0:
        raise CorruptRecordError("empty key")
    if flags == 1 and value_len != 0:
        raise CorruptRecordError("tombstone has a value")
    end = offset + _HEADER + key_len + value_len
    if len(buf) < end:
        raise IncompleteRecordError("record payload is incomplete")
    key_data = buf[offset + _HEADER:offset + _HEADER + key_len]
    value_data = buf[offset + _HEADER + key_len:end]
    if zlib.crc32(key_data + value_data) & 0xffffffff != crc:
        raise CorruptRecordError("CRC mismatch")
    try:
        key = key_data.decode("utf-8")
        value = None if flags else value_data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("invalid UTF-8") from exc
    return key, value, end - offset
