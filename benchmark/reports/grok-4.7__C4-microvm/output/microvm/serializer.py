import struct
import zlib

from microvm.compiler import Instr, Program
from microvm.errors import SerializationError
from microvm.opcodes import OPCODE_NUMBERS

_ARG_OPS = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})
_NO_ARG = 0xFFFFFFFF
_INT_MIN = -9223372036854775808
_INT_MAX = 9223372036854775807
_OP_BY_NUMBER = {number: name for name, number in OPCODE_NUMBERS.items()}


def dumps(program: Program) -> bytes:
    body = bytearray()
    body.append(1)
    _write_names(body, program.names)
    _write_constants(body, program.constants)
    _write_instructions(body, program.instructions)
    checksum = zlib.crc32(body) & 0xFFFFFFFF
    return b"MVM1" + bytes(body) + checksum.to_bytes(4, "big")


def loads(data: bytes) -> Program:
    raw = _as_bytes(data)
    if len(raw) < 4:
        raise SerializationError("truncated input")
    if raw[:4] != b"MVM1":
        raise SerializationError("bad magic")
    if len(raw) < 8:
        raise SerializationError("truncated input")
    # Checksum is the last 4 bytes and is verified before any length field is read.
    body = raw[4:-4]
    checksum = int.from_bytes(raw[-4:], "big")
    if (zlib.crc32(body) & 0xFFFFFFFF) != checksum:
        raise SerializationError("checksum mismatch")
    return _parse_body(body)


def _as_bytes(data: bytes) -> bytes:
    if type(data) is bytes:
        return data
    if type(data) is bytearray or type(data) is memoryview:
        return bytes(data)
    raise SerializationError("data must be bytes")


def _write_names(body: bytearray, names: list[str]) -> None:
    if len(names) > 65535:
        raise SerializationError("too many names")
    body += len(names).to_bytes(2, "big")
    for name in names:
        raw = name.encode("utf-8")
        if len(raw) > 65535:
            raise SerializationError("name too long")
        body += len(raw).to_bytes(2, "big")
        body += raw


def _write_constants(body: bytearray, constants: list[object]) -> None:
    if len(constants) > 65535:
        raise SerializationError("too many constants")
    body += len(constants).to_bytes(2, "big")
    for value in constants:
        _write_constant(body, value)


def _write_constant(body: bytearray, value: object) -> None:
    if type(value) is bool:
        body.append(0x04)
        body.append(1 if value else 0)
        return
    if type(value) is int:
        _write_int(body, value)
        return
    if type(value) is float:
        body.append(0x02)
        body += struct.pack(">d", value)
        return
    if type(value) is str:
        _write_string(body, value)
        return
    raise SerializationError("unsupported constant type")


def _write_int(body: bytearray, value: int) -> None:
    if value < _INT_MIN or value > _INT_MAX:
        raise SerializationError("integer out of range")
    body.append(0x01)
    body += value.to_bytes(8, "big", signed=True)


def _write_string(body: bytearray, value: str) -> None:
    raw = value.encode("utf-8")
    if len(raw) > 0xFFFFFFFF:
        raise SerializationError("string too long")
    body.append(0x03)
    body += len(raw).to_bytes(4, "big")
    body += raw


def _write_instructions(body: bytearray, instructions: list[Instr]) -> None:
    if len(instructions) > 0xFFFFFFFF:
        raise SerializationError("too many instructions")
    body += len(instructions).to_bytes(4, "big")
    for instr in instructions:
        _write_instr(body, instr)


def _write_instr(body: bytearray, instr: Instr) -> None:
    number = OPCODE_NUMBERS.get(instr.op)
    if number is None:
        raise SerializationError(f"unknown opcode: {instr.op}")
    body.append(number)
    if instr.op in _ARG_OPS:
        if type(instr.arg) is not int or not 0 <= instr.arg <= 0xFFFFFFFE:
            raise SerializationError("invalid instruction argument")
        body += instr.arg.to_bytes(4, "big")
        return
    if instr.arg is not None:
        raise SerializationError("unexpected instruction argument")
    body += b"\xff\xff\xff\xff"


def _parse_body(body: bytes) -> Program:
    reader = _Reader(body)
    version = reader.u8()
    if version != 1:
        raise SerializationError("unsupported version")
    names = _read_names(reader)
    constants = _read_constants(reader)
    instructions = _read_instructions(reader)
    if not reader.done():
        raise SerializationError("trailing bytes")
    return Program(constants, names, instructions)


def _read_names(reader: "_Reader") -> list[str]:
    count = reader.u16()
    return [_read_utf8(reader, reader.u16(), "name") for _ in range(count)]


def _read_constants(reader: "_Reader") -> list[object]:
    count = reader.u16()
    return [_read_constant(reader) for _ in range(count)]


def _read_constant(reader: "_Reader") -> object:
    tag = reader.u8()
    if tag == 0x01:
        return reader.i64()
    if tag == 0x02:
        return reader.f64()
    if tag == 0x03:
        return _read_utf8(reader, reader.u32(), "string")
    if tag == 0x04:
        return _read_bool(reader)
    raise SerializationError("unknown constant tag")


def _read_bool(reader: "_Reader") -> bool:
    flag = reader.u8()
    if flag not in (0, 1):
        raise SerializationError("invalid bool")
    return flag == 1


def _read_utf8(reader: "_Reader", length: int, label: str) -> str:
    try:
        return reader.take(length).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SerializationError(f"invalid utf-8 {label}") from exc


def _read_instructions(reader: "_Reader") -> list[Instr]:
    count = reader.u32()
    return [_read_instr(reader) for _ in range(count)]


def _read_instr(reader: "_Reader") -> Instr:
    op = _OP_BY_NUMBER.get(reader.u8())
    arg_raw = reader.u32()
    if op is None:
        raise SerializationError("unknown opcode")
    if op in _ARG_OPS:
        if arg_raw == _NO_ARG:
            raise SerializationError("missing instruction argument")
        return Instr(op, arg_raw)
    if arg_raw != _NO_ARG:
        raise SerializationError("unexpected instruction argument")
    return Instr(op, None)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def done(self) -> bool:
        return self.pos == len(self.data)

    def take(self, size: int) -> bytes:
        end = self.pos + size
        if size < 0 or end > len(self.data):
            raise SerializationError("truncated input")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), "big")

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "big")

    def i64(self) -> int:
        return int.from_bytes(self.take(8), "big", signed=True)

    def f64(self) -> float:
        return struct.unpack(">d", self.take(8))[0]
