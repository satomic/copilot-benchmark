from __future__ import annotations

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import OPCODES, OPCODE_NUMBERS, _ARG_OPS
from .vm import _Value


_MAGIC = b"MVM1"
_NO_ARG = 0xFFFFFFFF


def _unsigned(value: int, bits: int) -> bytes:
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise SerializationError(f"Value does not fit u{bits}: {value!r}")
    return value.to_bytes(bits // 8, "big")


def _text(value: str, bits: int) -> bytes:
    if type(value) is not str:
        raise SerializationError("Expected a string")
    try:
        data = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SerializationError("String is not valid UTF-8") from error
    return _unsigned(len(data), bits) + data


def _constant(value: _Value) -> bytes:
    if type(value) is bool:
        return b"\x04" + bytes((int(value),))
    if type(value) is int:
        if not -(1 << 63) <= value < 1 << 63:
            raise SerializationError("INT constant outside signed 64-bit range")
        return b"\x01" + struct.pack(">q", value)
    if type(value) is float:
        return b"\x02" + struct.pack(">d", value)
    if type(value) is str:
        return b"\x03" + _text(value, 32)
    raise SerializationError(f"Unsupported constant type: {type(value).__name__}")


def _instruction(instr: Instr) -> bytes:
    if not isinstance(instr, Instr) or instr.op not in OPCODE_NUMBERS:
        raise SerializationError("Unknown instruction opcode")
    if instr.op in _ARG_OPS:
        if type(instr.arg) is not int or not 0 <= instr.arg < _NO_ARG:
            raise SerializationError(f"Invalid argument for {instr.op}")
        arg = instr.arg
    else:
        if instr.arg is not None:
            raise SerializationError(f"{instr.op} takes no argument")
        arg = _NO_ARG
    return bytes((OPCODE_NUMBERS[instr.op],)) + _unsigned(arg, 32)


def dumps(program: Program) -> bytes:
    body = bytearray(b"\x01")
    body.extend(_unsigned(len(program.names), 16))
    for name in program.names:
        body.extend(_text(name, 16))
    body.extend(_unsigned(len(program.constants), 16))
    for value in program.constants:
        body.extend(_constant(value))
    body.extend(_unsigned(len(program.instructions), 32))
    for instr in program.instructions:
        body.extend(_instruction(instr))
    return _MAGIC + body + _unsigned(zlib.crc32(body), 32)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def _read(self, size: int) -> bytes:
        if size > len(self.data) - self.pos:
            raise SerializationError("Truncated bytecode")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def _uint(self, bits: int) -> int:
        return int.from_bytes(self._read(bits // 8), "big")

    def _text(self, bits: int) -> str:
        data = self._read(self._uint(bits))
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SerializationError("Invalid UTF-8 in bytecode") from error

    def _constant(self) -> _Value:
        tag = self._uint(8)
        if tag == 1:
            return struct.unpack(">q", self._read(8))[0]
        if tag == 2:
            return struct.unpack(">d", self._read(8))[0]
        if tag == 3:
            return self._text(32)
        if tag == 4:
            value = self._uint(8)
            if value not in (0, 1):
                raise SerializationError("Invalid BOOL payload")
            return bool(value)
        raise SerializationError(f"Unknown constant tag {tag}")

    def _instruction(self) -> Instr:
        number = self._uint(8)
        arg = self._uint(32)
        if not 1 <= number <= len(OPCODES):
            raise SerializationError(f"Unknown opcode number {number}")
        op = OPCODES[number - 1]
        if op in _ARG_OPS:
            if arg == _NO_ARG:
                raise SerializationError(f"Missing argument for {op}")
            return Instr(op, arg)
        if arg != _NO_ARG:
            raise SerializationError(f"Unexpected argument for {op}")
        return Instr(op, None)

    def _program(self) -> Program:
        if self._uint(8) != 1:
            raise SerializationError("Unsupported bytecode version")
        names = [self._text(16) for _ in range(self._uint(16))]
        constants = [self._constant() for _ in range(self._uint(16))]
        count = self._uint(32)
        if count > (len(self.data) - self.pos) // 5:
            raise SerializationError("Truncated instruction list")
        instructions = [self._instruction() for _ in range(count)]
        if self.pos != len(self.data):
            raise SerializationError("Trailing bytes in bytecode")
        return Program(constants, names, instructions)


def loads(data: bytes) -> Program:
    if not isinstance(data, bytes):
        raise SerializationError("Bytecode must be bytes")
    if len(data) < 9:
        raise SerializationError("Truncated bytecode")
    if data[:4] != _MAGIC:
        raise SerializationError("Bad bytecode magic")
    body = data[4:-4]
    checksum = int.from_bytes(data[-4:], "big")
    if zlib.crc32(body) != checksum:
        raise SerializationError("Bytecode checksum mismatch")
    return _Reader(body)._program()
