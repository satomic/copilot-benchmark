"""Checksummed binary encoding of compiled programs."""

from __future__ import annotations

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import OPCODES, OPCODE_NUMBERS, OPCODES_WITH_ARG

MAGIC = b"MVM1"
VERSION = 1
NO_ARG = 0xFFFFFFFF
_INT_MIN = -(1 << 63)
_INT_MAX = (1 << 63) - 1
_TAG_INT, _TAG_FLOAT, _TAG_STRING, _TAG_BOOL = 1, 2, 3, 4


def _u16(value: int, what: str) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise SerializationError(f"{what} {value} does not fit in u16")
    return struct.pack(">H", value)


def _u32(value: int, what: str) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise SerializationError(f"{what} {value} does not fit in u32")
    return struct.pack(">I", value)


def _encode_constant(value: object) -> bytes:
    if isinstance(value, bool):
        return bytes([_TAG_BOOL, 1 if value else 0])
    if isinstance(value, int):
        if not _INT_MIN <= value <= _INT_MAX:
            raise SerializationError(f"INT constant {value} is outside the signed 64-bit range")
        return bytes([_TAG_INT]) + struct.pack(">q", value)
    if isinstance(value, float):
        return bytes([_TAG_FLOAT]) + struct.pack(">d", value)
    if isinstance(value, str):
        payload = value.encode("utf-8")
        return bytes([_TAG_STRING]) + _u32(len(payload), "string length") + payload
    raise SerializationError(f"unsupported constant type {type(value).__name__}")


def _encode_instr(instr: Instr) -> bytes:
    number = OPCODE_NUMBERS.get(instr.op)
    if number is None:
        raise SerializationError(f"unknown opcode {instr.op!r}")
    takes_arg = instr.op in OPCODES_WITH_ARG
    if takes_arg:
        if not isinstance(instr.arg, int) or isinstance(instr.arg, bool):
            raise SerializationError(f"opcode {instr.op} requires an int argument")
        if not 0 <= instr.arg < NO_ARG:
            raise SerializationError(f"argument {instr.arg} of {instr.op} is out of range")
        arg = instr.arg
    else:
        if instr.arg is not None:
            raise SerializationError(f"opcode {instr.op} takes no argument")
        arg = NO_ARG
    return bytes([number]) + struct.pack(">I", arg)


def dumps(program: Program) -> bytes:
    body = bytearray()
    body.append(VERSION)
    body += _u16(len(program.names), "name count")
    for name in program.names:
        if not isinstance(name, str):
            raise SerializationError("variable names must be strings")
        raw = name.encode("utf-8")
        body += _u16(len(raw), "name length") + raw
    body += _u16(len(program.constants), "constant count")
    for value in program.constants:
        body += _encode_constant(value)
    body += _u32(len(program.instructions), "instruction count")
    for instr in program.instructions:
        body += _encode_instr(instr)
    checksum = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    return MAGIC + bytes(body) + struct.pack(">I", checksum)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int, what: str) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SerializationError(f"truncated data while reading {what}")
        chunk = self.data[self.pos:self.pos + count]
        self.pos += count
        return chunk

    def unpack(self, fmt: str, what: str) -> int:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt), what))[0]

    def utf8(self, length: int, what: str) -> str:
        try:
            return self.take(length, what).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError(f"invalid UTF-8 in {what}") from exc

    def constant(self) -> object:
        tag = self.unpack(">B", "constant tag")
        if tag == _TAG_INT:
            return self.unpack(">q", "INT constant")
        if tag == _TAG_FLOAT:
            return struct.unpack(">d", self.take(8, "FLOAT constant"))[0]
        if tag == _TAG_STRING:
            return self.utf8(self.unpack(">I", "string length"), "STRING constant")
        if tag == _TAG_BOOL:
            raw = self.unpack(">B", "BOOL constant")
            if raw not in (0, 1):
                raise SerializationError(f"invalid BOOL payload {raw}")
            return raw == 1
        raise SerializationError(f"unknown constant tag {tag}")

    def instr(self) -> Instr:
        number = self.unpack(">B", "opcode")
        arg = self.unpack(">I", "instruction argument")
        if not 1 <= number <= len(OPCODES):
            raise SerializationError(f"unknown opcode number {number}")
        op = OPCODES[number - 1]
        if op in OPCODES_WITH_ARG:
            if arg == NO_ARG:
                raise SerializationError(f"opcode {op} is missing its argument")
            return Instr(op, arg)
        if arg != NO_ARG:
            raise SerializationError(f"opcode {op} takes no argument but has {arg}")
        return Instr(op, None)


def loads(data: bytes) -> Program:
    if not isinstance(data, (bytes, bytearray)):
        raise SerializationError("expected bytes")
    data = bytes(data)
    if len(data) < len(MAGIC) + 4:
        raise SerializationError("data too short")
    if data[:4] != MAGIC:
        raise SerializationError("bad magic")
    body, (expected,) = data[4:-4], struct.unpack(">I", data[-4:])
    # The checksum guards every length field: validate it before decoding anything.
    if zlib.crc32(body) & 0xFFFFFFFF != expected:
        raise SerializationError("checksum mismatch")
    reader = _Reader(body)
    version = reader.unpack(">B", "version")
    if version != VERSION:
        raise SerializationError(f"unsupported version {version}")
    names = [
        reader.utf8(reader.unpack(">H", "name length"), "name")
        for _ in range(reader.unpack(">H", "name count"))
    ]
    constants = [reader.constant() for _ in range(reader.unpack(">H", "constant count"))]
    instructions = [reader.instr() for _ in range(reader.unpack(">I", "instruction count"))]
    if reader.pos != len(body):
        raise SerializationError("trailing bytes after program body")
    return Program(constants, names, instructions)
