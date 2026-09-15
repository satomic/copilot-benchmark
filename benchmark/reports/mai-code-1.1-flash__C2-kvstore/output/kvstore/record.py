import struct
import zlib

from .errors import CorruptRecordError, IncompleteRecordError

MAGIC = b"KVR1"


def encode_record(key: str, value: str | None) -> bytes:
    if not isinstance(key, str):
        raise TypeError("key must be str")
    if value is not None and not isinstance(value, str):
        raise TypeError("value must be str or None")

    key_bytes = key.encode("utf-8")
    if not 1 <= len(key_bytes) <= 65535:
        raise ValueError("key byte length out of range")

    if value is None:
        flags = 0x01
        value_bytes = b""
    else:
        flags = 0x00
        value_bytes = value.encode("utf-8")

    header = (
        MAGIC
        + bytes([flags])
        + struct.pack(">H", len(key_bytes))
        + struct.pack(">I", len(value_bytes))
        + struct.pack(">I", zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF)
    )
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    start = offset
    if len(buf) - start < 15:
        raise IncompleteRecordError("header is incomplete")

    header = buf[start : start + 15]
    if header[0:4] != MAGIC:
        raise CorruptRecordError("bad magic")

    flags = header[4]
    if flags not in (0x00, 0x01):
        raise CorruptRecordError("unknown flags")

    key_len = struct.unpack(">H", header[5:7])[0]
    if key_len == 0:
        raise CorruptRecordError("key_len is zero")

    value_len = struct.unpack(">I", header[7:11])[0]
    if flags == 0x01 and value_len != 0:
        raise CorruptRecordError("tombstone has non-zero value_len")

    total_size = 15 + key_len + value_len
    if len(buf) - start < total_size:
        raise IncompleteRecordError("record extends beyond buffer")

    crc = struct.unpack(">I", header[11:15])[0]
    key_start = start + 15
    key_bytes = buf[key_start : key_start + key_len]
    value_start = key_start + key_len
    value_bytes = buf[value_start : value_start + value_len]

    if (zlib.crc32(key_bytes + value_bytes) & 0xFFFFFFFF) != crc:
        raise CorruptRecordError("CRC mismatch")

    try:
        key = key_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("key is not valid UTF-8") from exc

    if flags == 0x01:
        return (key, None, total_size)

    try:
        value = value_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError("value is not valid UTF-8") from exc
    return (key, value, total_size)
