"""Binary codec for compiled programs."""

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import ARG_OPCODES, OPCODE_NUMBERS, OPCODES

MAGIC = b"MVM1"
VERSION = 1
NO_ARG = 0xFFFFFFFF
_INT_MIN = -(2 ** 63)
_INT_MAX = 2 ** 63 - 1


def _encode_constant(value: object) -> bytes:
    if type(value) is bool:
        return b"\x04" + struct.pack(">B", 1 if value else 0)
    if type(value) is int:
        if not _INT_MIN <= value <= _INT_MAX:
            raise SerializationError(f"INT constant {value} outside signed 64-bit range")
        return b"\x01" + struct.pack(">q", value)
    if type(value) is float:
        return b"\x02" + struct.pack(">d", value)
    if type(value) is str:
        try:
            raw = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise SerializationError(f"string not encodable: {exc}") from None
        if len(raw) > 0xFFFFFFFF:
            raise SerializationError("string constant too long")
        return b"\x03" + struct.pack(">I", len(raw)) + raw
    raise SerializationError(f"unsupported constant type {type(value).__name__}")


def _encode_name(name: object) -> bytes:
    if type(name) is not str:
        raise SerializationError("variable names must be strings")
    try:
        raw = name.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SerializationError(f"name not encodable: {exc}") from None
    if len(raw) > 0xFFFF:
        raise SerializationError("variable name too long")
    return struct.pack(">H", len(raw)) + raw


def _encode_instr(instr: Instr) -> bytes:
    number = OPCODE_NUMBERS.get(instr.op)
    if number is None:
        raise SerializationError(f"unknown opcode {instr.op!r}")
    if instr.op in ARG_OPCODES:
        arg = instr.arg
        if type(arg) is not int or not 0 <= arg < NO_ARG:
            raise SerializationError(f"{instr.op} needs an argument in u32 range")
    else:
        if instr.arg is not None:
            raise SerializationError(f"{instr.op} takes no argument")
        arg = NO_ARG
    return struct.pack(">BI", number, arg)


def dumps(program: Program) -> bytes:
    if len(program.names) > 0xFFFF or len(program.constants) > 0xFFFF:
        raise SerializationError("too many names or constants")
    if len(program.instructions) > 0xFFFFFFFF:
        raise SerializationError("too many instructions")
    parts = [struct.pack(">BH", VERSION, len(program.names))]
    parts += [_encode_name(n) for n in program.names]
    parts.append(struct.pack(">H", len(program.constants)))
    parts += [_encode_constant(c) for c in program.constants]
    parts.append(struct.pack(">I", len(program.instructions)))
    parts += [_encode_instr(i) for i in program.instructions]
    body = b"".join(parts)
    return MAGIC + body + struct.pack(">I", zlib.crc32(body))


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise SerializationError("truncated data")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def unpack(self, fmt: str) -> tuple:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def text(self, length: int) -> str:
        try:
            return self.take(length).decode("utf-8")
        except UnicodeDecodeError:
            raise SerializationError("invalid UTF-8") from None


def _decode_constant(reader: _Reader) -> object:
    (tag,) = reader.unpack(">B")
    if tag == 0x01:
        return reader.unpack(">q")[0]
    if tag == 0x02:
        return reader.unpack(">d")[0]
    if tag == 0x03:
        return reader.text(reader.unpack(">I")[0])
    if tag == 0x04:
        (flag,) = reader.unpack(">B")
        if flag not in (0, 1):
            raise SerializationError(f"invalid BOOL payload {flag}")
        return flag == 1
    raise SerializationError(f"unknown constant tag {tag:#04x}")


def _decode_instr(reader: _Reader) -> Instr:
    number, arg = reader.unpack(">BI")
    if not 1 <= number <= len(OPCODES):
        raise SerializationError(f"unknown opcode number {number}")
    op = OPCODES[number - 1]
    if op in ARG_OPCODES:
        if arg == NO_ARG:
            raise SerializationError(f"{op} is missing its argument")
        return Instr(op, arg)
    if arg != NO_ARG:
        raise SerializationError(f"{op} must not carry an argument")
    return Instr(op, None)


def loads(data: bytes) -> Program:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise SerializationError("data must be bytes")
    data = bytes(data)
    if len(data) < len(MAGIC) or data[:len(MAGIC)] != MAGIC:
        raise SerializationError("bad magic")
    if len(data) < len(MAGIC) + 4:
        raise SerializationError("truncated data")
    body, (checksum,) = data[len(MAGIC):-4], struct.unpack(">I", data[-4:])
    if zlib.crc32(body) != checksum:
        raise SerializationError("checksum mismatch")
    reader = _Reader(body)
    if reader.unpack(">B")[0] != VERSION:
        raise SerializationError("unsupported version")
    names = [reader.text(reader.unpack(">H")[0]) for _ in range(reader.unpack(">H")[0])]
    constants = [_decode_constant(reader) for _ in range(reader.unpack(">H")[0])]
    instructions = [_decode_instr(reader) for _ in range(reader.unpack(">I")[0])]
    if reader.pos != len(body):
        raise SerializationError("trailing bytes")
    return Program(constants, names, instructions)
