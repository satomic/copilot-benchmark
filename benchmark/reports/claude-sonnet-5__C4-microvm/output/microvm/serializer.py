"""Binary serializer/deserializer for compiled Programs."""

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import OPCODE_NUMBERS, OPCODES, OPCODES_WITH_ARG

MAGIC = b"MVM1"
VERSION = 1

_OPCODE_BY_NUMBER: dict[int, str] = {v: k for k, v in OPCODE_NUMBERS.items()}

_TAG_INT = 0x01
_TAG_FLOAT = 0x02
_TAG_STRING = 0x03
_TAG_BOOL = 0x04

_NO_ARG = 0xFFFFFFFF
_I64_MIN = -(2 ** 63)
_I64_MAX = 2 ** 63 - 1


def _encode_const(value: object) -> bytes:
    if type(value) is bool:
        return bytes([_TAG_BOOL, 1 if value else 0])
    if isinstance(value, int):
        if not (_I64_MIN <= value <= _I64_MAX):
            raise SerializationError("integer constant out of signed 64-bit range")
        return bytes([_TAG_INT]) + struct.pack(">q", value)
    if isinstance(value, float):
        return bytes([_TAG_FLOAT]) + struct.pack(">d", value)
    encoded = value.encode("utf-8")
    return bytes([_TAG_STRING]) + struct.pack(">I", len(encoded)) + encoded


def _encode_instr(instr: Instr) -> bytes:
    opcode_num = OPCODE_NUMBERS[instr.op]
    if instr.op in OPCODES_WITH_ARG:
        arg = instr.arg
    else:
        arg = _NO_ARG
    return bytes([opcode_num]) + struct.pack(">I", arg)


def dumps(program: Program) -> bytes:
    parts = [bytes([VERSION])]
    parts.append(struct.pack(">H", len(program.names)))
    for name in program.names:
        encoded = name.encode("utf-8")
        parts.append(struct.pack(">H", len(encoded)) + encoded)
    parts.append(struct.pack(">H", len(program.constants)))
    for const in program.constants:
        parts.append(_encode_const(const))
    parts.append(struct.pack(">I", len(program.instructions)))
    for instr in program.instructions:
        parts.append(_encode_instr(instr))
    body = b"".join(parts)
    checksum = zlib.crc32(body)
    return MAGIC + body + struct.pack(">I", checksum)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise SerializationError("truncated data")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.read(4))[0]

    def i64(self) -> int:
        return struct.unpack(">q", self.read(8))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self.read(8))[0]


def _read_names(r: _Reader) -> list[str]:
    count = r.u16()
    names = []
    for _ in range(count):
        length = r.u16()
        names.append(r.read(length).decode("utf-8"))
    return names


def _read_one_const(r: _Reader) -> object:
    tag = r.u8()
    if tag == _TAG_INT:
        return r.i64()
    if tag == _TAG_FLOAT:
        return r.f64()
    if tag == _TAG_STRING:
        length = r.u32()
        return r.read(length).decode("utf-8")
    if tag == _TAG_BOOL:
        value = r.u8()
        if value not in (0, 1):
            raise SerializationError("invalid bool payload")
        return value == 1
    raise SerializationError(f"unknown constant tag {tag}")


def _read_constants(r: _Reader) -> list:
    count = r.u16()
    return [_read_one_const(r) for _ in range(count)]


def _read_one_instr(r: _Reader) -> Instr:
    opcode_num = r.u8()
    if opcode_num not in _OPCODE_BY_NUMBER:
        raise SerializationError(f"unknown opcode number {opcode_num}")
    op = _OPCODE_BY_NUMBER[opcode_num]
    raw_arg = r.u32()
    has_arg = op in OPCODES_WITH_ARG
    if has_arg and raw_arg == _NO_ARG:
        raise SerializationError(f"opcode {op} requires an argument")
    if not has_arg and raw_arg != _NO_ARG:
        raise SerializationError(f"opcode {op} takes no argument")
    return Instr(op, raw_arg if has_arg else None)


def _read_instructions(r: _Reader) -> list:
    count = r.u32()
    return [_read_one_instr(r) for _ in range(count)]


def loads(data: bytes) -> Program:
    if len(data) < len(MAGIC) + 1 + 4:
        raise SerializationError("truncated data")
    if data[:len(MAGIC)] != MAGIC:
        raise SerializationError("bad magic")
    body = data[len(MAGIC):-4]
    checksum = struct.unpack(">I", data[-4:])[0]
    if zlib.crc32(body) != checksum:
        raise SerializationError("checksum mismatch")
    r = _Reader(body)
    version = r.u8()
    if version != VERSION:
        raise SerializationError(f"unsupported version {version}")
    names = _read_names(r)
    constants = _read_constants(r)
    instructions = _read_instructions(r)
    if r.pos != len(body):
        raise SerializationError("trailing bytes after checksum")
    return Program(constants, names, instructions)
