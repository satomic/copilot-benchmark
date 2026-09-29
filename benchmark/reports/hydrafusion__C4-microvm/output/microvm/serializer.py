import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import OPCODES, OPCODE_NUMBERS


_ARGUMENT_OPS = frozenset(("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"))
_NO_ARGUMENT = 0xFFFFFFFF


def _u16(value: int, label: str) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise SerializationError(f"{label} exceeds u16 range")
    return struct.pack(">H", value)


def _u32(value: int, label: str) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise SerializationError(f"{label} exceeds u32 range")
    return struct.pack(">I", value)


def _encode_text(value: str, length_size: int) -> bytes:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SerializationError("text is not valid UTF-8") from exc
    length = _u16(len(encoded), "text") if length_size == 2 else _u32(len(encoded), "text")
    return length + encoded


def _encode_constant(value: object) -> bytes:
    if type(value) is bool:
        return b"\x04" + bytes((int(value),))
    if type(value) is int:
        if not -(1 << 63) <= value < (1 << 63):
            raise SerializationError("integer constant outside signed i64 range")
        return b"\x01" + struct.pack(">q", value)
    if type(value) is float:
        return b"\x02" + struct.pack(">d", value)
    if type(value) is str:
        return b"\x03" + _encode_text(value, 4)
    raise SerializationError("unsupported constant type")


def _encode_instruction(instruction: Instr) -> bytes:
    if instruction.op not in OPCODE_NUMBERS:
        raise SerializationError(f"unknown opcode: {instruction.op}")
    if instruction.op in _ARGUMENT_OPS:
        if type(instruction.arg) is not int or not 0 <= instruction.arg < _NO_ARGUMENT:
            raise SerializationError(f"{instruction.op} requires a u32 argument")
        argument = instruction.arg
    else:
        if instruction.arg is not None:
            raise SerializationError(f"{instruction.op} takes no argument")
        argument = _NO_ARGUMENT
    return bytes((OPCODE_NUMBERS[instruction.op],)) + struct.pack(">I", argument)


def dumps(program: Program) -> bytes:
    body = bytearray((1,))
    body.extend(_u16(len(program.names), "name count"))
    for name in program.names:
        if type(name) is not str:
            raise SerializationError("variable name must be a string")
        body.extend(_encode_text(name, 2))
    body.extend(_u16(len(program.constants), "constant count"))
    for constant in program.constants:
        body.extend(_encode_constant(constant))
    body.extend(_u32(len(program.instructions), "instruction count"))
    for instruction in program.instructions:
        if not isinstance(instruction, Instr):
            raise SerializationError("invalid instruction")
        body.extend(_encode_instruction(instruction))
    checksum = struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return b"MVM1" + bytes(body) + checksum


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SerializationError("truncated data")
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def text(self, length_size: int) -> str:
        length = self.u16() if length_size == 2 else self.u32()
        try:
            return self.take(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError("invalid UTF-8") from exc


def _decode_constant(reader: _Reader) -> object:
    tag = reader.u8()
    if tag == 1:
        return struct.unpack(">q", reader.take(8))[0]
    if tag == 2:
        return struct.unpack(">d", reader.take(8))[0]
    if tag == 3:
        return reader.text(4)
    if tag == 4:
        value = reader.u8()
        if value not in (0, 1):
            raise SerializationError("invalid BOOL payload")
        return bool(value)
    raise SerializationError(f"unknown constant tag: {tag}")


def _decode_instruction(reader: _Reader) -> Instr:
    number = reader.u8()
    if not 1 <= number <= len(OPCODES):
        raise SerializationError(f"unknown opcode number: {number}")
    op = OPCODES[number - 1]
    encoded_arg = reader.u32()
    if op in _ARGUMENT_OPS:
        if encoded_arg == _NO_ARGUMENT:
            raise SerializationError(f"{op} requires an argument")
        return Instr(op, encoded_arg)
    if encoded_arg != _NO_ARGUMENT:
        raise SerializationError(f"{op} takes no argument")
    return Instr(op, None)


def loads(data: bytes) -> Program:
    if not isinstance(data, bytes):
        raise SerializationError("data must be bytes")
    if len(data) < 9:
        raise SerializationError("truncated data")
    if data[:4] != b"MVM1":
        raise SerializationError("bad magic")
    payload = data[4:-4]
    expected = struct.unpack(">I", data[-4:])[0]
    if (zlib.crc32(payload) & 0xFFFFFFFF) != expected:
        raise SerializationError("checksum mismatch")
    reader = _Reader(payload)
    if reader.u8() != 1:
        raise SerializationError("unsupported version")
    names = [reader.text(2) for _ in range(reader.u16())]
    constants = [_decode_constant(reader) for _ in range(reader.u16())]
    instructions = [_decode_instruction(reader) for _ in range(reader.u32())]
    if reader.pos != len(payload):
        raise SerializationError("trailing bytes after program")
    return Program(constants, names, instructions)
