import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import OPCODES, OPCODE_NUMBERS


_MAGIC = b"MVM1"
_ARG_OPS = {"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"}
_NO_ARG = 0xFFFFFFFF


def dumps(program: Program) -> bytes:
    try:
        body = bytearray([1])
        _put_u16(body, len(program.names))
        for name in program.names:
            if not isinstance(name, str):
                raise SerializationError("variable names must be strings")
            encoded = name.encode("utf-8")
            _put_u16(body, len(encoded))
            body.extend(encoded)
        _put_u16(body, len(program.constants))
        for value in program.constants:
            _put_constant(body, value)
        _put_u32(body, len(program.instructions))
        for instr in program.instructions:
            if not isinstance(instr, Instr) or instr.op not in OPCODE_NUMBERS:
                raise SerializationError("invalid instruction")
            body.append(OPCODE_NUMBERS[instr.op])
            arg = instr.arg
            if instr.op in _ARG_OPS:
                if type(arg) is not int or not 0 <= arg < _NO_ARG:
                    raise SerializationError(f"invalid argument for {instr.op}")
                _put_u32(body, arg)
            else:
                if arg is not None:
                    raise SerializationError(f"{instr.op} must not have an argument")
                _put_u32(body, _NO_ARG)
        checksum = zlib.crc32(body) & 0xFFFFFFFF
        return _MAGIC + bytes(body) + struct.pack(">I", checksum)
    except (OverflowError, struct.error, UnicodeEncodeError, TypeError) as exc:
        raise SerializationError(str(exc)) from exc


def loads(data: bytes) -> Program:
    if not isinstance(data, bytes) or len(data) < 9:
        raise SerializationError("truncated binary program")
    if data[:4] != _MAGIC:
        raise SerializationError("bad magic")
    expected = struct.unpack(">I", data[-4:])[0]
    if zlib.crc32(data[4:-4]) & 0xFFFFFFFF != expected:
        raise SerializationError("checksum mismatch")
    reader = _Reader(data, 4, len(data) - 4)
    version = reader.u8()
    if version != 1:
        raise SerializationError(f"unsupported version {version}")
    names = [_read_name(reader) for _ in range(reader.u16())]
    constants = [_read_constant(reader) for _ in range(reader.u16())]
    instructions = [_read_instruction(reader) for _ in range(reader.u32())]
    if reader.pos != reader.end:
        raise SerializationError("trailing bytes after program")
    return Program(constants, names, instructions)


def _put_constant(body: bytearray, value: object) -> None:
    if type(value) is int:
        if not -(1 << 63) <= value < (1 << 63):
            raise SerializationError("INT constant outside signed 64-bit range")
        body.append(1)
        body.extend(struct.pack(">q", value))
    elif type(value) is float:
        body.append(2)
        body.extend(struct.pack(">d", value))
    elif type(value) is str:
        encoded = value.encode("utf-8")
        body.append(3)
        _put_u32(body, len(encoded))
        body.extend(encoded)
    elif type(value) is bool:
        body.extend((4, int(value)))
    else:
        raise SerializationError(f"unsupported constant type: {type(value).__name__}")


def _read_name(reader: "_Reader") -> str:
    try:
        return reader.read(reader.u16()).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SerializationError("invalid UTF-8 name") from exc


def _read_constant(reader: "_Reader") -> object:
    tag = reader.u8()
    if tag == 1:
        return struct.unpack(">q", reader.read(8))[0]
    if tag == 2:
        return struct.unpack(">d", reader.read(8))[0]
    if tag == 3:
        try:
            return reader.read(reader.u32()).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError("invalid UTF-8 string constant") from exc
    if tag == 4:
        value = reader.u8()
        if value not in (0, 1):
            raise SerializationError("invalid BOOL payload")
        return bool(value)
    raise SerializationError(f"unknown constant tag {tag}")


def _read_instruction(reader: "_Reader") -> Instr:
    number = reader.u8()
    if not 1 <= number <= len(OPCODES):
        raise SerializationError(f"unknown opcode number {number}")
    op = OPCODES[number - 1]
    arg = reader.u32()
    if op in _ARG_OPS:
        if arg == _NO_ARG:
            raise SerializationError(f"{op} requires an argument")
        return Instr(op, arg)
    if arg != _NO_ARG:
        raise SerializationError(f"{op} must not have an argument")
    return Instr(op, None)


def _put_u16(out: bytearray, value: int) -> None:
    if not 0 <= value <= 0xFFFF:
        raise SerializationError("field exceeds u16 limit")
    out.extend(struct.pack(">H", value))


def _put_u32(out: bytearray, value: int) -> None:
    if not 0 <= value <= 0xFFFFFFFF:
        raise SerializationError("field exceeds u32 limit")
    out.extend(struct.pack(">I", value))


class _Reader:
    def __init__(self, data: bytes, pos: int, end: int):
        self.data, self.pos, self.end = data, pos, end

    def read(self, length: int) -> bytes:
        if length < 0 or length > self.end - self.pos:
            raise SerializationError("truncated binary program")
        result = self.data[self.pos:self.pos + length]
        self.pos += length
        return result

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.read(4))[0]
