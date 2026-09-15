import struct
import zlib

from kvstore.errors import CorruptRecordError, IncompleteRecordError

_HEADER_FORMAT = ">4sBHII"
_HEADER_SIZE = 15
_MAGIC = b"KVR1"
_FLAG_VALUE = 0x00
_FLAG_TOMBSTONE = 0x01


def encode_record(key: str, value: str | None) -> bytes:
    if not isinstance(key, str):
        raise TypeError(f"Key must be str, got {type(key).__name__}")
    if value is not None and not isinstance(value, str):
        raise TypeError(f"Value must be str or None, got {type(value).__name__}")

    key_bytes = key.encode("utf-8")
    key_len = len(key_bytes)
    if key_len < 1 or key_len > 65535:
        raise ValueError(f"Key byte length must be in 1..65535, got {key_len}")

    if value is None:
        flags = _FLAG_TOMBSTONE
        value_bytes = b""
        value_len = 0
    else:
        flags = _FLAG_VALUE
        value_bytes = value.encode("utf-8")
        value_len = len(value_bytes)

    payload = key_bytes + value_bytes
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = struct.pack(_HEADER_FORMAT, _MAGIC, flags, key_len, value_len, crc)
    return header + payload


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    if offset < 0:
        raise ValueError("Offset cannot be negative")
    if len(buf) - offset < _HEADER_SIZE:
        raise IncompleteRecordError("Buffer has fewer than 15 bytes for header")

    magic, flags, key_len, value_len, expected_crc = struct.unpack_from(
        _HEADER_FORMAT, buf, offset
    )

    if magic != _MAGIC:
        raise CorruptRecordError(f"Bad magic: {magic!r}")
    if flags not in (_FLAG_VALUE, _FLAG_TOMBSTONE):
        raise CorruptRecordError(f"Unknown flags: {flags:#x}")
    if key_len == 0:
        raise CorruptRecordError("key_len cannot be 0")
    if flags == _FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("Tombstone record cannot have value_len != 0")

    total_size = _HEADER_SIZE + key_len + value_len
    if len(buf) - offset < total_size:
        raise IncompleteRecordError("Buffer has fewer bytes than record requires")

    payload = buf[offset + _HEADER_SIZE : offset + total_size]
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise CorruptRecordError(
            f"CRC mismatch: expected {expected_crc:#010x}, got {actual_crc:#010x}"
        )

    try:
        key = payload[:key_len].decode("utf-8")
        if flags == _FLAG_TOMBSTONE:
            value = None
        else:
            value = payload[key_len:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptRecordError(f"Invalid UTF-8: {exc}") from exc

    return key, value, total_size
