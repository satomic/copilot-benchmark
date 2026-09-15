"""Binary codec for Programs: magic + version + payload + CRC32 checksum."""

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import ARG_OPS, OPCODE_NUMBERS, OPCODES

MAGIC = b"MVM1"
VERSION = 1
_NO_ARG = 0xFFFFFFFF

_TAG_INT = 0x01
_TAG_FLOAT = 0x02
_TAG_STRING = 0x03
_TAG_BOOL = 0x04


def _dump_constant(value: object) -> bytes:
    if isinstance(value, bool):
        return bytes([_TAG_BOOL, 1 if value else 0])
    if isinstance(value, int):
        if not (-(2 ** 63) <= value < 2 ** 63):
            raise SerializationError("INT constant out of signed 64-bit range")
        return bytes([_TAG_INT]) + struct.pack(">q", value)
    if isinstance(value, float):
        return bytes([_TAG_FLOAT]) + struct.pack(">d", value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return bytes([_TAG_STRING]) + struct.pack(">I", len(raw)) + raw
    raise SerializationError(f"unsupported constant type {type(value).__name__}")


def dumps(program: Program) -> bytes:
    """Serialize ``program`` deterministically to the MVM1 binary format."""
    body = bytearray([VERSION])
    body += struct.pack(">H", len(program.names))
    for name in program.names:
        raw = name.encode("utf-8")
        body += struct.pack(">H", len(raw)) + raw
    body += struct.pack(">H", len(program.constants))
    for value in program.constants:
        body += _dump_constant(value)
    body += struct.pack(">I", len(program.instructions))
    for ins in program.instructions:
        if ins.op in ARG_OPS:
            if ins.arg is None:
                raise SerializationError(f"{ins.op} requires an argument")
            arg = ins.arg
        else:
            if ins.arg is not None:
                raise SerializationError(f"{ins.op} takes no argument")
            arg = _NO_ARG
        body += bytes([OPCODE_NUMBERS[ins.op]]) + struct.pack(">I", arg)
    checksum = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    return MAGIC + bytes(body) + struct.pack(">I", checksum)


class _Reader:
    """Bounds-checked big-endian cursor over the checksummed body."""

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


def _load_constant(reader: _Reader) -> object:
    tag = reader.u8()
    if tag == _TAG_INT:
        return struct.unpack(">q", reader.read(8))[0]
    if tag == _TAG_FLOAT:
        return struct.unpack(">d", reader.read(8))[0]
    if tag == _TAG_STRING:
        return reader.read(reader.u32()).decode("utf-8")
    if tag == _TAG_BOOL:
        value = reader.u8()
        if value not in (0, 1):
            raise SerializationError(f"invalid BOOL payload {value}")
        return value == 1
    raise SerializationError(f"unknown constant tag 0x{tag:02X}")


def _load_instruction(reader: _Reader) -> Instr:
    number = reader.u8()
    if not (1 <= number <= len(OPCODES)):
        raise SerializationError(f"unknown opcode number {number}")
    op = OPCODES[number - 1]
    arg = reader.u32()
    if op in ARG_OPS:
        if arg == _NO_ARG:
            raise SerializationError(f"{op} is missing its argument")
        return Instr(op, arg)
    if arg != _NO_ARG:
        raise SerializationError(f"{op} must not carry an argument")
    return Instr(op, None)


def loads(data: bytes) -> Program:
    """Decode the MVM1 binary format, validating the checksum first."""
    if len(data) < 8 or not data.startswith(MAGIC):
        raise SerializationError("bad magic")
    body, raw_crc = data[4:-4], struct.unpack(">I", data[-4:])[0]
    if zlib.crc32(body) & 0xFFFFFFFF != raw_crc:
        raise SerializationError("checksum mismatch")
    reader = _Reader(body)
    if reader.u8() != VERSION:
        raise SerializationError("unsupported version")
    names = [reader.read(reader.u16()).decode("utf-8") for _ in range(reader.u16())]
    constants = [_load_constant(reader) for _ in range(reader.u16())]
    instructions = [_load_instruction(reader) for _ in range(reader.u32())]
    if reader.pos != len(body):
        raise SerializationError("trailing bytes after final section")
    return Program(constants, names, instructions)
