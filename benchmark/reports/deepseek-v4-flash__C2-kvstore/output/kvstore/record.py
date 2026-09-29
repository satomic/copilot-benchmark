import struct
import zlib

from kvstore.errors import CorruptRecordError, IncompleteRecordError

_MAGIC = b"KVR1"
_FLAG_VALUE = 0x00
_FLAG_TOMBSTONE = 0x01

_HEADER_FMT = struct.Struct("!4s B H I I")  # 4 + 1 + 2 + 4 + 4 = 15
_HEADER_SIZE = _HEADER_FMT.size  # 15


def encode_record(key: str, value: str | None) -> bytes:
    """Encode a key-value pair into a binary record.

    If *value* is None a tombstone record is produced.
    """
    key_bytes = key.encode("utf-8")
    if value is None:
        flags = _FLAG_TOMBSTONE
        value_bytes = b""
    else:
        flags = _FLAG_VALUE
        value_bytes = value.encode("utf-8")
    payload = key_bytes + value_bytes
    crc = zlib.crc32(payload)
    header = _HEADER_FMT.pack(_MAGIC, flags, len(key_bytes), len(value_bytes), crc)
    return header + payload


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    """Decode a record starting at *offset* in *buf*.

    Returns ``(key, value, total_size)`` where *value* is ``None`` for tombstones.
    """
    remaining = len(buf) - offset
    if remaining < _HEADER_SIZE:
        raise IncompleteRecordError(
            f"need {_HEADER_SIZE} bytes for header, have {remaining}"
        )

    magic, flags, key_len, value_len, crc = _HEADER_FMT.unpack_from(buf, offset)

    if magic != _MAGIC:
        raise CorruptRecordError(f"bad magic: {magic!r}")

    if flags not in (_FLAG_VALUE, _FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags: {flags}")

    if key_len == 0:
        raise CorruptRecordError("key_len is 0")

    total = _HEADER_SIZE + key_len + value_len
    if remaining < total:
        raise IncompleteRecordError(
            f"need {total} bytes, have {remaining}"
        )

    if flags == _FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError(
            f"tombstone has non-zero value_len: {value_len}"
        )

    key_start = offset + _HEADER_SIZE
    key_end = key_start + key_len
    value_start = key_end
    value_end = value_start + value_len

    payload = buf[key_start:value_end]
    computed = zlib.crc32(payload)
    if computed != crc:
        raise CorruptRecordError(f"CRC mismatch: expected {crc}, computed {computed}")

    try:
        key_str = buf[key_start:key_end].decode("utf-8")
    except UnicodeDecodeError as e:
        raise CorruptRecordError(f"key is not valid UTF-8: {e}") from e

    if flags == _FLAG_TOMBSTONE:
        return key_str, None, total

    try:
        value_str = buf[value_start:value_end].decode("utf-8")
    except UnicodeDecodeError as e:
        raise CorruptRecordError(f"value is not valid UTF-8: {e}") from e

    return key_str, value_str, total