import struct
import zlib
from .errors import IncompleteRecordError, CorruptRecordError

MAGIC = b"KVR1"
FLAG_VALUE = 0x00
FLAG_TOMBSTONE = 0x01
HEADER_SIZE = 15


def encode_record(key: str, value: str | None) -> bytes:
    key_bytes = key.encode("utf-8")
    
    if len(key_bytes) == 0 or len(key_bytes) > 65535:
        raise ValueError(f"key byte length must be in 1..65535, got {len(key_bytes)}")
    
    if value is None:
        value_bytes = b""
        flags = FLAG_TOMBSTONE
    else:
        value_bytes = value.encode("utf-8")
        flags = FLAG_VALUE
    
    crc = zlib.crc32(key_bytes + value_bytes) & 0xffffffff
    
    header = struct.pack(
        ">4sBHII",
        MAGIC,
        flags,
        len(key_bytes),
        len(value_bytes),
        crc
    )
    
    return header + key_bytes + value_bytes


def decode_record(buf: bytes, offset: int = 0) -> tuple[str, str | None, int]:
    if offset + HEADER_SIZE > len(buf):
        raise IncompleteRecordError("incomplete header")
    
    magic, flags, key_len, value_len, crc = struct.unpack_from(
        ">4sBHII", buf, offset
    )
    
    if magic != MAGIC:
        raise CorruptRecordError("bad magic")
    
    if flags not in (FLAG_VALUE, FLAG_TOMBSTONE):
        raise CorruptRecordError(f"unknown flags {flags}")
    
    if key_len == 0:
        raise CorruptRecordError("key_len is 0")
    
    if flags == FLAG_TOMBSTONE and value_len != 0:
        raise CorruptRecordError("tombstone with value_len != 0")
    
    total_data_len = key_len + value_len
    record_end = offset + HEADER_SIZE + total_data_len
    
    if record_end > len(buf):
        raise IncompleteRecordError("incomplete key/value bytes")
    
    key_bytes = buf[offset + HEADER_SIZE : offset + HEADER_SIZE + key_len]
    value_bytes = buf[offset + HEADER_SIZE + key_len : record_end]
    
    computed_crc = zlib.crc32(key_bytes + value_bytes) & 0xffffffff
    if computed_crc != crc:
        raise CorruptRecordError("CRC mismatch")
    
    try:
        key = key_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise CorruptRecordError(f"key is not valid UTF-8: {e}")
    
    if flags == FLAG_TOMBSTONE:
        value = None
    else:
        try:
            value = value_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            raise CorruptRecordError(f"value is not valid UTF-8: {e}")
    
    return key, value, record_end - offset
