"""The binary codec. One reader class owns every bounds check."""

from __future__ import annotations

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import HAS_ARG, OPCODES, OPCODE_NUMBERS

__all__ = ["dumps", "loads"]

_MAGIC = b"MVM1"
_VERSION = 1
_NO_ARG = 0xFFFFFFFF
_I64_MIN, _I64_MAX = -(2 ** 63), 2 ** 63 - 1

_TAG_INT, _TAG_FLOAT, _TAG_STR, _TAG_BOOL = 0x01, 0x02, 0x03, 0x04


def _encode_constant(value: object) -> bytes:
    if isinstance(value, bool):
        return struct.pack(">BB", _TAG_BOOL, 1 if value else 0)
    if isinstance(value, int):
        if not _I64_MIN <= value <= _I64_MAX:
            raise SerializationError(f"INT constant {value} does not fit in 64 bits")
        return struct.pack(">Bq", _TAG_INT, value)
    if isinstance(value, float):
        return struct.pack(">Bd", _TAG_FLOAT, value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return struct.pack(">BI", _TAG_STR, len(raw)) + raw
    raise SerializationError(f"unsupported constant {value!r}")


def dumps(program: Program) -> bytes:
    """Serialize deterministically: magic + body + CRC32(body)."""
    body = bytearray()
    body += struct.pack(">B", _VERSION)
    body += struct.pack(">H", len(program.names))
    for name in program.names:
        raw = name.encode("utf-8")
        body += struct.pack(">H", len(raw)) + raw
    body += struct.pack(">H", len(program.constants))
    for value in program.constants:
        body += _encode_constant(value)
    body += struct.pack(">I", len(program.instructions))
    for instr in program.instructions:
        arg = _NO_ARG if instr.arg is None else instr.arg
        body += struct.pack(">BI", OPCODE_NUMBERS[instr.op], arg)
    return _MAGIC + bytes(body) + struct.pack(">I", zlib.crc32(bytes(body)))


class _Reader:
    """Cursor over the body bytes; every read is bounds-checked here."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def take(self, count: int) -> bytes:
        if self._pos + count > len(self._data):
            raise SerializationError("truncated data")
        chunk = self._data[self._pos:self._pos + count]
        self._pos += count
        return chunk

    def unpack(self, fmt: str) -> tuple:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def done(self) -> bool:
        return self._pos == len(self._data)


def _decode_constant(reader: _Reader) -> object:
    (tag,) = reader.unpack(">B")
    if tag == _TAG_INT:
        return reader.unpack(">q")[0]
    if tag == _TAG_FLOAT:
        return reader.unpack(">d")[0]
    if tag == _TAG_STR:
        (length,) = reader.unpack(">I")
        try:
            return reader.take(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError(f"invalid UTF-8 in constant: {exc}") from None
    if tag == _TAG_BOOL:
        (flag,) = reader.unpack(">B")
        if flag not in (0, 1):
            raise SerializationError(f"BOOL payload must be 0 or 1, got {flag}")
        return flag == 1
    raise SerializationError(f"unknown constant tag {tag:#04x}")


def loads(data: bytes) -> Program:
    """Parse and validate. The checksum is verified before any length is trusted."""
    if len(data) < len(_MAGIC) + 1 + 4 or data[:4] != _MAGIC:
        raise SerializationError("bad magic")
    body, checksum = data[4:-4], data[-4:]
    if struct.unpack(">I", checksum)[0] != zlib.crc32(body):
        raise SerializationError("checksum mismatch")
    reader = _Reader(body)
    (version,) = reader.unpack(">B")
    if version != _VERSION:
        raise SerializationError(f"unsupported version {version}")
    (name_count,) = reader.unpack(">H")
    names = []
    for _ in range(name_count):
        (length,) = reader.unpack(">H")
        names.append(reader.take(length).decode("utf-8"))
    (const_count,) = reader.unpack(">H")
    constants = [_decode_constant(reader) for _ in range(const_count)]
    (instr_count,) = reader.unpack(">I")
    instructions = []
    for _ in range(instr_count):
        number, raw_arg = reader.unpack(">BI")
        if not 1 <= number <= len(OPCODES):
            raise SerializationError(f"unknown opcode number {number}")
        op = OPCODES[number - 1]
        arg = None if raw_arg == _NO_ARG else raw_arg
        if (arg is None) == (op in HAS_ARG):
            raise SerializationError(f"opcode {op} has a malformed argument")
        instructions.append(Instr(op, arg))
    if not reader.done():
        raise SerializationError("trailing bytes")
    return Program(constants, names, instructions)
