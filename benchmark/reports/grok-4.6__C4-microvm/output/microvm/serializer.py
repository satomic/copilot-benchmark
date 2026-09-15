from __future__ import annotations

import struct
import zlib

from microvm.compiler import Instr, Program
from microvm.errors import SerializationError
from microvm.opcodes import HAS_ARG, NO_ARG_SENTINEL, OPCODE_NUMBERS

_MAGIC = b"MVM1"
_I64_MIN = -(1 << 63)
_I64_MAX = (1 << 63) - 1
_NUM_TO_OP: dict[int, str] = {number: name for name, number in OPCODE_NUMBERS.items()}


def dumps(program: Program) -> bytes:
    body = bytearray()
    body.append(1)
    _write_names(body, program.names)
    _write_constants(body, program.constants)
    _write_instructions(body, program.instructions)
    checksum = zlib.crc32(body) & 0xFFFFFFFF
    return _MAGIC + bytes(body) + checksum.to_bytes(4, "big")


def loads(data: bytes) -> Program:
    if len(data) < 9:
        raise SerializationError("truncated")
    if data[:4] != _MAGIC:
        raise SerializationError("bad magic")
    payload = data[4:-4]
    checksum = int.from_bytes(data[-4:], "big")
    if (zlib.crc32(payload) & 0xFFFFFFFF) != checksum:
        raise SerializationError("checksum mismatch")
    reader = _Reader(payload)
    program = _parse_payload(reader)
    if reader.i != len(payload):
        raise SerializationError("trailing bytes")
    return program


def _write_names(body: bytearray, names: list[str]) -> None:
    if len(names) > 0xFFFF:
        raise SerializationError("too many names")
    body.extend(struct.pack(">H", len(names)))
    for name in names:
        encoded = name.encode("utf-8")
        if len(encoded) > 0xFFFF:
            raise SerializationError("name too long")
        body.extend(struct.pack(">H", len(encoded)))
        body.extend(encoded)


def _write_constants(body: bytearray, constants: list[object]) -> None:
    if len(constants) > 0xFFFF:
        raise SerializationError("too many constants")
    body.extend(struct.pack(">H", len(constants)))
    for value in constants:
        _write_constant(body, value)


def _write_constant(body: bytearray, value: object) -> None:
    if type(value) is int:
        if value < _I64_MIN or value > _I64_MAX:
            raise SerializationError("int out of signed 64-bit range")
        body.append(0x01)
        body.extend(value.to_bytes(8, "big", signed=True))
    elif type(value) is float:
        body.append(0x02)
        body.extend(struct.pack(">d", value))
    elif type(value) is str:
        encoded = value.encode("utf-8")
        body.append(0x03)
        body.extend(struct.pack(">I", len(encoded)))
        body.extend(encoded)
    elif type(value) is bool:
        body.append(0x04)
        body.append(1 if value else 0)
    else:
        raise SerializationError("unsupported constant")


def _write_instructions(body: bytearray, instructions: list[Instr]) -> None:
    body.extend(struct.pack(">I", len(instructions)))
    for instr in instructions:
        if instr.op not in OPCODE_NUMBERS:
            raise SerializationError("unknown opcode")
        takes = instr.op in HAS_ARG
        if takes != (instr.arg is not None):
            raise SerializationError("instruction argument mismatch")
        arg = instr.arg if takes else NO_ARG_SENTINEL
        if takes and arg == NO_ARG_SENTINEL:
            raise SerializationError("reserved argument sentinel")
        body.append(OPCODE_NUMBERS[instr.op])
        body.extend(struct.pack(">I", int(arg)))


def _parse_payload(reader: _Reader) -> Program:
    version = reader.u8()
    if version != 1:
        raise SerializationError("unsupported version")
    names = _read_names(reader)
    constants = _read_constants(reader)
    instructions = _read_instructions(reader)
    return Program(constants, names, instructions)


def _read_names(reader: _Reader) -> list[str]:
    count = reader.u16()
    names: list[str] = []
    for _ in range(count):
        length = reader.u16()
        names.append(_decode_utf8(reader.raw(length)))
    return names


def _read_constants(reader: _Reader) -> list[object]:
    count = reader.u16()
    values: list[object] = []
    for _ in range(count):
        values.append(_read_constant(reader))
    return values


def _read_constant(reader: _Reader) -> object:
    tag = reader.u8()
    if tag == 0x01:
        return int.from_bytes(reader.raw(8), "big", signed=True)
    if tag == 0x02:
        return struct.unpack(">d", reader.raw(8))[0]
    if tag == 0x03:
        return _decode_utf8(reader.raw(reader.u32()))
    if tag == 0x04:
        flag = reader.u8()
        if flag not in (0, 1):
            raise SerializationError("invalid bool payload")
        return bool(flag)
    raise SerializationError("unknown constant tag")


def _read_instructions(reader: _Reader) -> list[Instr]:
    count = reader.u32()
    ins: list[Instr] = []
    for _ in range(count):
        number = reader.u8()
        arg = reader.u32()
        op = _NUM_TO_OP.get(number)
        if op is None:
            raise SerializationError("unknown opcode")
        takes = op in HAS_ARG
        if takes:
            if arg == NO_ARG_SENTINEL:
                raise SerializationError("missing instruction argument")
            ins.append(Instr(op, arg))
        else:
            if arg != NO_ARG_SENTINEL:
                raise SerializationError("unexpected instruction argument")
            ins.append(Instr(op, None))
    return ins


def _decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SerializationError("invalid utf-8") from exc


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.i = 0

    def need(self, n: int) -> None:
        if self.i + n > len(self.data):
            raise SerializationError("truncated")

    def raw(self, n: int) -> bytes:
        self.need(n)
        chunk = self.data[self.i : self.i + n]
        self.i += n
        return chunk

    def u8(self) -> int:
        return self.raw(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.raw(2), "big")

    def u32(self) -> int:
        return int.from_bytes(self.raw(4), "big")
