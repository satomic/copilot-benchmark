"""Binary codec for compiled programs (magic ``MVM1``, version 1)."""

from __future__ import annotations

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import OPCODE_NUMBERS, has_argument

MAGIC: bytes = b"MVM1"
VERSION: int = 1
NO_ARG: int = 0xFFFFFFFF

_TAG_INT = 0x01
_TAG_FLOAT = 0x02
_TAG_STRING = 0x03
_TAG_BOOL = 0x04

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

_NUMBER_TO_OPCODE: dict[int, str] = {number: name for name, number in OPCODE_NUMBERS.items()}


def _encode_constant(value: object) -> bytes:
    if isinstance(value, bool):
        return bytes([_TAG_BOOL, 1 if value else 0])
    if isinstance(value, int):
        if not _INT64_MIN <= value <= _INT64_MAX:
            raise SerializationError(f"INT constant {value} does not fit in 64 bits")
        return bytes([_TAG_INT]) + struct.pack(">q", value)
    if isinstance(value, float):
        return bytes([_TAG_FLOAT]) + struct.pack(">d", value)
    if isinstance(value, str):
        payload = value.encode("utf-8")
        return bytes([_TAG_STRING]) + struct.pack(">I", len(payload)) + payload
    raise SerializationError(f"unsupported constant type {type(value).__name__}")


def _encode_instruction(instr: object) -> bytes:
    if not isinstance(instr, Instr):
        raise SerializationError("instructions must be Instr objects")
    if instr.op not in OPCODE_NUMBERS:
        raise SerializationError(f"unknown opcode {instr.op!r}")
    takes_arg = has_argument(instr.op)
    if takes_arg and instr.arg is None:
        raise SerializationError(f"opcode {instr.op} requires an argument")
    if not takes_arg and instr.arg is not None:
        raise SerializationError(f"opcode {instr.op} must not carry an argument")
    arg = NO_ARG if instr.arg is None else instr.arg
    if not 0 <= arg <= 0xFFFFFFFF or (takes_arg and arg == NO_ARG):
        raise SerializationError(f"argument out of range for {instr.op}: {instr.arg}")
    return bytes([OPCODE_NUMBERS[instr.op]]) + struct.pack(">I", arg)


def _u16_prefixed(text: str) -> bytes:
    payload = text.encode("utf-8")
    if len(payload) > 0xFFFF:
        raise SerializationError("name is too long to encode")
    return struct.pack(">H", len(payload)) + payload


def _check_count(count: int, what: str) -> None:
    if count > 0xFFFF:
        raise SerializationError(f"too many {what} to encode")


def dumps(program: Program) -> bytes:
    """Serialize *program* to its deterministic binary representation."""
    _check_count(len(program.names), "names")
    _check_count(len(program.constants), "constants")
    if len(program.instructions) > 0xFFFFFFFF:
        raise SerializationError("too many instructions to encode")
    body = bytearray()
    body.append(VERSION)
    body += struct.pack(">H", len(program.names))
    for name in program.names:
        body += _u16_prefixed(name)
    body += struct.pack(">H", len(program.constants))
    for constant in program.constants:
        body += _encode_constant(constant)
    body += struct.pack(">I", len(program.instructions))
    for instr in program.instructions:
        body += _encode_instruction(instr)
    checksum = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    return MAGIC + bytes(body) + struct.pack(">I", checksum)


class _Reader:
    """Bounds checked cursor over the decoded body."""

    def __init__(self, data: bytes) -> None:
        self.data: bytes = data
        self.pos: int = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SerializationError("truncated program data")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def at_end(self) -> bool:
        return self.pos == len(self.data)


def _decode_constant(reader: _Reader) -> object:
    tag = reader.u8()
    if tag == _TAG_INT:
        return struct.unpack(">q", reader.take(8))[0]
    if tag == _TAG_FLOAT:
        return struct.unpack(">d", reader.take(8))[0]
    if tag == _TAG_STRING:
        payload = reader.take(reader.u32())
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SerializationError("STRING constant is not valid UTF-8") from exc
    if tag == _TAG_BOOL:
        raw = reader.u8()
        if raw not in (0, 1):
            raise SerializationError(f"invalid BOOL payload {raw}")
        return raw == 1
    raise SerializationError(f"unknown constant tag {tag:#04x}")


def _decode_instruction(reader: _Reader) -> Instr:
    number = reader.u8()
    raw_arg = reader.u32()
    if number not in _NUMBER_TO_OPCODE:
        raise SerializationError(f"unknown opcode number {number}")
    op = _NUMBER_TO_OPCODE[number]
    if has_argument(op):
        if raw_arg == NO_ARG:
            raise SerializationError(f"opcode {op} is missing its argument")
        return Instr(op, raw_arg)
    if raw_arg != NO_ARG:
        raise SerializationError(f"opcode {op} must not carry an argument")
    return Instr(op, None)


def _decode_body(body: bytes) -> Program:
    reader = _Reader(body)
    name_count = reader.u16()
    names: list[str] = []
    for _ in range(name_count):
        names.append(reader.take(reader.u16()).decode("utf-8", "strict"))
    constant_count = reader.u16()
    constants = [_decode_constant(reader) for _ in range(constant_count)]
    instruction_count = reader.u32()
    instructions = [_decode_instruction(reader) for _ in range(instruction_count)]
    if not reader.at_end():
        raise SerializationError("trailing bytes after the instruction table")
    return Program(constants, names, instructions)


def loads(data: bytes) -> Program:
    """Decode *data* into a :class:`Program`, validating it thoroughly."""
    if not isinstance(data, (bytes, bytearray)):
        raise SerializationError("program data must be bytes")
    data = bytes(data)
    if len(data) < len(MAGIC) + 1 + 4:
        raise SerializationError("truncated program data")
    if data[: len(MAGIC)] != MAGIC:
        raise SerializationError("bad magic")
    if data[len(MAGIC)] != VERSION:
        raise SerializationError(f"unsupported version {data[len(MAGIC)]}")
    body = data[len(MAGIC) : -4]
    expected = struct.unpack(">I", data[-4:])[0]
    if zlib.crc32(body) & 0xFFFFFFFF != expected:
        raise SerializationError("checksum mismatch")
    try:
        return _decode_body(body[1:])
    except (struct.error, UnicodeDecodeError) as exc:  # pragma: no cover - defensive
        raise SerializationError(f"malformed program data: {exc}") from exc


__all__ = ["dumps", "loads", "MAGIC", "VERSION"]
