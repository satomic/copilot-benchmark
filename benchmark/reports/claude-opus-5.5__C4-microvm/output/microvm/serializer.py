"""Checksummed binary encoding of compiled programs."""

from __future__ import annotations

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import ARG_OPCODES, OPCODE_NUMBERS, OPCODES

MAGIC = b"MVM1"
VERSION = 1
NO_ARG = 0xFFFFFFFF
_TAG_INT, _TAG_FLOAT, _TAG_STRING, _TAG_BOOL = 0x01, 0x02, 0x03, 0x04
_I64_MIN, _I64_MAX = -(2 ** 63), 2 ** 63 - 1
_U16_MAX, _U32_MAX = 0xFFFF, 0xFFFFFFFF


def _utf8(text: object, what: str) -> bytes:
    if type(text) is not str:
        raise SerializationError(f"{what} must be a str, got {type(text).__name__}")
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SerializationError(f"{what} is not encodable as UTF-8: {exc}") from None


def _count(n: int, limit: int, what: str) -> None:
    if n > limit:
        raise SerializationError(f"too many {what}: {n} (maximum {limit})")


def _encode_constant(value: object) -> bytes:
    kind = type(value)
    if kind is bool:
        return bytes([_TAG_BOOL, 1 if value else 0])
    if kind is int:
        if not _I64_MIN <= value <= _I64_MAX:
            raise SerializationError(f"INT constant {value} does not fit in 64 bits")
        return bytes([_TAG_INT]) + struct.pack(">q", value)
    if kind is float:
        return bytes([_TAG_FLOAT]) + struct.pack(">d", value)
    if kind is str:
        raw = _utf8(value, "STRING constant")
        _count(len(raw), _U32_MAX, "bytes in a STRING constant")
        return bytes([_TAG_STRING]) + struct.pack(">I", len(raw)) + raw
    raise SerializationError(f"unsupported constant type {kind.__name__}")


def _encode_instr(instr: object) -> bytes:
    op = getattr(instr, "op", None)
    arg = getattr(instr, "arg", None)
    if op not in OPCODE_NUMBERS:
        raise SerializationError(f"unknown opcode {op!r}")
    if op in ARG_OPCODES:
        if type(arg) is not int or not 0 <= arg < NO_ARG:
            raise SerializationError(f"opcode {op} needs an argument in 0..{NO_ARG - 1}, got {arg!r}")
    elif arg is not None:
        raise SerializationError(f"opcode {op} takes no argument, got {arg!r}")
    return struct.pack(">BI", OPCODE_NUMBERS[op], NO_ARG if arg is None else arg)


def dumps(program: Program) -> bytes:
    """Serialize ``program`` deterministically to bytes."""
    body = bytearray([VERSION])
    names = list(program.names)
    _count(len(names), _U16_MAX, "names")
    body += struct.pack(">H", len(names))
    for name in names:
        raw = _utf8(name, "variable name")
        _count(len(raw), _U16_MAX, "bytes in a variable name")
        body += struct.pack(">H", len(raw)) + raw
    constants = list(program.constants)
    _count(len(constants), _U16_MAX, "constants")
    body += struct.pack(">H", len(constants))
    for value in constants:
        body += _encode_constant(value)
    instructions = list(program.instructions)
    _count(len(instructions), _U32_MAX, "instructions")
    body += struct.pack(">I", len(instructions))
    for instr in instructions:
        body += _encode_instr(instr)
    return MAGIC + bytes(body) + struct.pack(">I", zlib.crc32(body) & _U32_MAX)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, size: int) -> bytes:
        if size > len(self.data) - self.pos:
            raise SerializationError("truncated data")
        chunk = self.data[self.pos:self.pos + size]
        self.pos += size
        return chunk

    def unpack(self, fmt: str) -> object:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def text(self, size: int, what: str) -> str:
        try:
            return self.take(size).decode("utf-8")
        except UnicodeDecodeError:
            raise SerializationError(f"{what} is not valid UTF-8") from None


def _decode_constant(reader: _Reader) -> object:
    tag = reader.unpack(">B")
    if tag == _TAG_INT:
        return reader.unpack(">q")
    if tag == _TAG_FLOAT:
        return reader.unpack(">d")
    if tag == _TAG_STRING:
        return reader.text(reader.unpack(">I"), "STRING constant")
    if tag == _TAG_BOOL:
        flag = reader.unpack(">B")
        if flag not in (0, 1):
            raise SerializationError(f"invalid BOOL payload {flag}")
        return flag == 1
    raise SerializationError(f"unknown constant tag 0x{tag:02x}")


def _decode_instr(reader: _Reader) -> Instr:
    number, arg = struct.unpack(">BI", reader.take(5))
    if not 1 <= number <= len(OPCODES):
        raise SerializationError(f"unknown opcode number {number}")
    op = OPCODES[number - 1]
    if op in ARG_OPCODES:
        if arg == NO_ARG:
            raise SerializationError(f"opcode {op} is missing its argument")
        return Instr(op, arg)
    if arg != NO_ARG:
        raise SerializationError(f"opcode {op} must not have an argument")
    return Instr(op, None)


def _verified_body(data: object) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise SerializationError("data must be bytes")
    data = bytes(data)
    if len(data) < len(MAGIC) or data[:len(MAGIC)] != MAGIC:
        raise SerializationError("bad magic")
    if len(data) < len(MAGIC) + 1 + 4:
        raise SerializationError("truncated data")
    body = data[len(MAGIC):-4]
    (stored,) = struct.unpack(">I", data[-4:])
    if zlib.crc32(body) & _U32_MAX != stored:
        raise SerializationError("checksum mismatch (corrupted, truncated or trailing data)")
    return body


def loads(data: bytes) -> Program:
    """Decode bytes produced by ``dumps``; every malformation is a ``SerializationError``."""
    # The checksum is verified before any length field is read.
    reader = _Reader(_verified_body(data))
    version = reader.unpack(">B")
    if version != VERSION:
        raise SerializationError(f"unsupported version {version}")
    names = [reader.text(reader.unpack(">H"), "variable name")
             for _ in range(reader.unpack(">H"))]
    constants = [_decode_constant(reader) for _ in range(reader.unpack(">H"))]
    count = reader.unpack(">I")
    if count * 5 > len(reader.data) - reader.pos:
        raise SerializationError("truncated data")
    instructions = [_decode_instr(reader) for _ in range(count)]
    if reader.pos != len(reader.data):
        raise SerializationError("trailing bytes after instructions")
    return Program(constants=constants, names=names, instructions=instructions)
