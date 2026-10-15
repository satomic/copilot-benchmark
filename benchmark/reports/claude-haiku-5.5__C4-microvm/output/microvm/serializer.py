"""Binary codec for compiled Programs (magic, version, checksummed body)."""

from __future__ import annotations

import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import ARGUMENT_OPCODES, OPCODE_NUMBERS, OPCODES

MAGIC: bytes = b"MVM1"
VERSION: int = 1
NO_ARG: int = 0xFFFFFFFF
_TAG_INT, _TAG_FLOAT, _TAG_STRING, _TAG_BOOL = 0x01, 0x02, 0x03, 0x04


def dumps(program: Program) -> bytes:
    """Serialize ``program`` deterministically to the MVM1 binary format."""
    body = bytearray([VERSION])
    body += _pack(">H", len(program.names))
    for name in program.names:
        raw = _encode_text(name)
        body += _pack(">H", len(raw)) + raw
    body += _pack(">H", len(program.constants))
    for value in program.constants:
        body += _encode_constant(value)
    body += _pack(">I", len(program.instructions))
    for instr in program.instructions:
        body += bytes([_opcode_number(instr.op)]) + _pack(">I", _encode_arg(instr))
    checksum = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    return MAGIC + bytes(body) + _pack(">I", checksum)


def loads(data: bytes) -> Program:
    """Parse MVM1 bytes into a Program, raising SerializationError on any defect."""
    body = _checked_body(bytes(data))
    reader = _Reader(body)
    version = reader.unpack(">B")
    if version != VERSION:
        raise SerializationError(f"unsupported format version {version}")
    names = [_read_name(reader) for _ in range(reader.unpack(">H"))]
    constants = [_read_constant(reader) for _ in range(reader.unpack(">H"))]
    instructions = [_read_instruction(reader) for _ in range(reader.unpack(">I"))]
    if reader.pos != len(body):
        raise SerializationError("trailing bytes after program body")
    return Program(constants=constants, names=names, instructions=instructions)


def _checked_body(data: bytes) -> bytes:
    """Verify magic and checksum; only then is the body safe to parse."""
    if len(data) < len(MAGIC) or data[:len(MAGIC)] != MAGIC:
        raise SerializationError("bad magic")
    if len(data) < len(MAGIC) + 1 + 4:
        raise SerializationError("truncated data")
    body = data[len(MAGIC):-4]
    (stored,) = struct.unpack(">I", data[-4:])
    if zlib.crc32(body) & 0xFFFFFFFF != stored:
        raise SerializationError("checksum mismatch")
    return body


class _Reader:
    """Bounds-checked sequential reader over the verified body."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SerializationError("truncated data")
        chunk = self.data[self.pos:self.pos + count]
        self.pos += count
        return chunk

    def unpack(self, fmt: str) -> int:
        (value,) = struct.unpack(fmt, self.take(struct.calcsize(fmt)))
        return int(value)

    def unpack_float(self) -> float:
        (value,) = struct.unpack(">d", self.take(8))
        return float(value)


def _read_name(reader: _Reader) -> str:
    raw = reader.take(reader.unpack(">H"))
    return _decode_text(raw)


def _read_constant(reader: _Reader) -> object:
    tag = reader.unpack(">B")
    if tag == _TAG_INT:
        return reader.unpack(">q")
    if tag == _TAG_FLOAT:
        return reader.unpack_float()
    if tag == _TAG_STRING:
        return _decode_text(reader.take(reader.unpack(">I")))
    if tag == _TAG_BOOL:
        flag = reader.unpack(">B")
        if flag not in (0, 1):
            raise SerializationError(f"invalid BOOL payload {flag}")
        return flag == 1
    raise SerializationError(f"unknown constant tag 0x{tag:02x}")


def _read_instruction(reader: _Reader) -> Instr:
    number = reader.unpack(">B")
    if not 1 <= number <= len(OPCODES):
        raise SerializationError(f"unknown opcode number {number}")
    op = OPCODES[number - 1]
    arg = reader.unpack(">I")
    if op in ARGUMENT_OPCODES:
        if arg == NO_ARG:
            raise SerializationError(f"{op} requires an argument")
        return Instr(op, arg)
    if arg != NO_ARG:
        raise SerializationError(f"{op} must not carry an argument")
    return Instr(op, None)


def _encode_constant(value: object) -> bytes:
    if type(value) is bool:
        return bytes([_TAG_BOOL, 1 if value else 0])
    if type(value) is int:
        return bytes([_TAG_INT]) + _pack(">q", value)
    if type(value) is float:
        return bytes([_TAG_FLOAT]) + struct.pack(">d", value)
    if type(value) is str:
        raw = _encode_text(value)
        return bytes([_TAG_STRING]) + _pack(">I", len(raw)) + raw
    raise SerializationError(f"unsupported constant {value!r}")


def _encode_arg(instr: Instr) -> int:
    if instr.op in ARGUMENT_OPCODES:
        if instr.arg is None or instr.arg == NO_ARG:
            raise SerializationError(f"{instr.op} needs an argument below 0xFFFFFFFF")
        return instr.arg
    if instr.arg is not None:
        raise SerializationError(f"{instr.op} takes no argument")
    return NO_ARG


def _opcode_number(op: str) -> int:
    if op not in OPCODE_NUMBERS:
        raise SerializationError(f"unknown opcode {op!r}")
    return OPCODE_NUMBERS[op]


def _pack(fmt: str, value: int) -> bytes:
    try:
        return struct.pack(fmt, value)
    except struct.error as exc:
        raise SerializationError(f"value {value!r} does not fit in {fmt}") from exc


def _encode_text(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SerializationError("text is not valid UTF-8") from exc


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SerializationError("invalid UTF-8 text") from exc
