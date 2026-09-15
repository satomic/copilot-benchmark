"""Binary serialization and deserialization for microvm programs."""

import struct
import zlib
from microvm.compiler import Instr, Program
from microvm.errors import SerializationError
from microvm.opcodes import OPCODE_NUMBERS, OPCODES

MAGIC: bytes = b"MVM1"
ARG_OPCODES: frozenset[str] = frozenset({"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"})
NO_ARG: int = 0xFFFFFFFF


def _encode_constant(c: object) -> bytes:
    if type(c) is bool:
        return b"\x04" + (b"\x01" if c else b"\x00")
    if type(c) is int:
        if not (-9223372036854775808 <= c <= 9223372036854775807):
            raise SerializationError(f"Integer constant {c} out of 64-bit signed range")
        return b"\x01" + struct.pack(">q", c)
    if type(c) is float:
        return b"\x02" + struct.pack(">d", c)
    if type(c) is str:
        data = c.encode("utf-8")
        if len(data) > NO_ARG:
            raise SerializationError("String constant too long")
        return b"\x03" + struct.pack(">I", len(data)) + data
    raise SerializationError(f"Unknown constant type {type(c)}")


def _encode_instruction(instr: Instr) -> bytes:
    if instr.op not in OPCODE_NUMBERS:
        raise SerializationError(f"Unknown opcode '{instr.op}'")
    op_num = OPCODE_NUMBERS[instr.op]
    if instr.op in ARG_OPCODES:
        if instr.arg is None or not (0 <= instr.arg < NO_ARG):
            raise SerializationError(f"Opcode '{instr.op}' requires valid argument")
        arg = instr.arg
    else:
        if instr.arg is not None:
            raise SerializationError(f"Opcode '{instr.op}' cannot have argument")
        arg = NO_ARG
    return struct.pack(">BI", op_num, arg)


def dumps(program: Program) -> bytes:
    parts: list[bytes] = [b"\x01"]
    if len(program.names) > 0xFFFF:
        raise SerializationError("Too many names")
    parts.append(struct.pack(">H", len(program.names)))
    for name in program.names:
        encoded = name.encode("utf-8")
        if len(encoded) > 0xFFFF:
            raise SerializationError(f"Name '{name}' too long")
        parts.append(struct.pack(">H", len(encoded)) + encoded)
    if len(program.constants) > 0xFFFF:
        raise SerializationError("Too many constants")
    parts.append(struct.pack(">H", len(program.constants)))
    for c in program.constants:
        parts.append(_encode_constant(c))
    if len(program.instructions) > NO_ARG:
        raise SerializationError("Too many instructions")
    parts.append(struct.pack(">I", len(program.instructions)))
    for instr in program.instructions:
        parts.append(_encode_instruction(instr))
    body = b"".join(parts)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return MAGIC + body + struct.pack(">I", crc)


def _decode_names(data: bytes, pos: int, end: int) -> tuple[list[str], int]:
    if pos + 2 > end:
        raise SerializationError("Truncated data in name count")
    (name_count,) = struct.unpack(">H", data[pos : pos + 2])
    pos += 2
    names: list[str] = []
    for _ in range(name_count):
        if pos + 2 > end:
            raise SerializationError("Truncated name length")
        (nlen,) = struct.unpack(">H", data[pos : pos + 2])
        pos += 2
        if pos + nlen > end:
            raise SerializationError("Truncated name bytes")
        try:
            names.append(data[pos : pos + nlen].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise SerializationError("Invalid UTF-8 in name") from exc
        pos += nlen
    return names, pos


def _decode_constants(data: bytes, pos: int, end: int) -> tuple[list[object], int]:
    if pos + 2 > end:
        raise SerializationError("Truncated data in constant count")
    (const_count,) = struct.unpack(">H", data[pos : pos + 2])
    pos += 2
    constants: list[object] = []
    for _ in range(const_count):
        if pos + 1 > end:
            raise SerializationError("Truncated constant tag")
        tag = data[pos]
        pos += 1
        if tag == 1:
            if pos + 8 > end:
                raise SerializationError("Truncated INT constant")
            constants.append(struct.unpack(">q", data[pos : pos + 8])[0])
            pos += 8
        elif tag == 2:
            if pos + 8 > end:
                raise SerializationError("Truncated FLOAT constant")
            constants.append(struct.unpack(">d", data[pos : pos + 8])[0])
            pos += 8
        elif tag == 3:
            if pos + 4 > end:
                raise SerializationError("Truncated STRING length")
            (slen,) = struct.unpack(">I", data[pos : pos + 4])
            pos += 4
            if pos + slen > end:
                raise SerializationError("Truncated STRING bytes")
            try:
                constants.append(data[pos : pos + slen].decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise SerializationError("Invalid UTF-8 in string constant") from exc
            pos += slen
        elif tag == 4:
            if pos + 1 > end:
                raise SerializationError("Truncated BOOL constant")
            bval = data[pos]
            pos += 1
            if bval not in (0, 1):
                raise SerializationError(f"Invalid BOOL constant value {bval}")
            constants.append(bool(bval))
        else:
            raise SerializationError(f"Unknown constant tag {tag}")
    return constants, pos


def _decode_instructions(data: bytes, pos: int, end: int) -> tuple[list[Instr], int]:
    if pos + 4 > end:
        raise SerializationError("Truncated instruction count")
    (instr_count,) = struct.unpack(">I", data[pos : pos + 4])
    pos += 4
    instructions: list[Instr] = []
    for _ in range(instr_count):
        if pos + 5 > end:
            raise SerializationError("Truncated instruction")
        op_num, arg_raw = struct.unpack(">BI", data[pos : pos + 5])
        pos += 5
        if not (1 <= op_num <= len(OPCODES)):
            raise SerializationError(f"Unknown opcode number {op_num}")
        op_name = OPCODES[op_num - 1]
        if op_name in ARG_OPCODES:
            if arg_raw == NO_ARG:
                raise SerializationError(f"Opcode '{op_name}' requires an argument")
            instructions.append(Instr(op=op_name, arg=arg_raw))
        else:
            if arg_raw != NO_ARG:
                raise SerializationError(f"Opcode '{op_name}' cannot have an argument")
            instructions.append(Instr(op=op_name, arg=None))
    return instructions, pos


def loads(data: bytes) -> Program:
    if len(data) < 17:
        raise SerializationError("Data too short to be valid microvm binary")
    if data[:4] != MAGIC:
        raise SerializationError("Invalid magic header")
    (expected_crc,) = struct.unpack(">I", data[-4:])
    actual_crc = zlib.crc32(data[4:-4]) & 0xFFFFFFFF
    if expected_crc != actual_crc:
        raise SerializationError("CRC32 checksum mismatch")
    if data[4] != 1:
        raise SerializationError(f"Unsupported binary version {data[4]}")
    pos = 5
    end = len(data) - 4
    names, pos = _decode_names(data, pos, end)
    constants, pos = _decode_constants(data, pos, end)
    instructions, pos = _decode_instructions(data, pos, end)
    if pos != end:
        raise SerializationError("Trailing bytes before checksum")
    return Program(constants=constants, names=names, instructions=instructions)
