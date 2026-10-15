from __future__ import annotations

import struct
import zlib
from microvm.compiler import Instr, Program
from microvm.errors import SerializationError
from microvm.opcodes import ARG_OPCODES, OPCODES, OPCODE_NUMBERS

MAGIC = b"MVM1"
VERSION = 1
NO_ARG = 0xFFFFFFFF

TAG_INT = 0x01
TAG_FLOAT = 0x02
TAG_STRING = 0x03
TAG_BOOL = 0x04

NUMBER_TO_OPCODE: dict[int, str] = {v: k for k, v in OPCODE_NUMBERS.items()}


def _pack_constant(val: object) -> bytes:
    if type(val) is bool:
        return struct.pack(">BB", TAG_BOOL, 1 if val else 0)
    if type(val) is int:
        if not (-(1 << 63) <= val <= (1 << 63) - 1):
            raise SerializationError(f"Integer constant {val} out of signed 64-bit range")
        return struct.pack(">Bq", TAG_INT, val)
    if type(val) is float:
        return struct.pack(">Bd", TAG_FLOAT, val)
    if type(val) is str:
        raw = val.encode("utf-8")
        if len(raw) > 0xFFFFFFFF:
            raise SerializationError("String constant too long")
        return struct.pack(">BI", TAG_STRING, len(raw)) + raw
    raise SerializationError(f"Unsupported constant type {type(val).__name__}")


def _pack_instruction(ins: Instr) -> bytes:
    if ins.op not in OPCODE_NUMBERS:
        raise SerializationError(f"Unknown opcode {ins.op!r}")
    op_num = OPCODE_NUMBERS[ins.op]
    takes_arg = ins.op in ARG_OPCODES
    if takes_arg:
        if ins.arg is None or type(ins.arg) is not int or not (0 <= ins.arg < NO_ARG):
            raise SerializationError(f"Invalid argument {ins.arg!r} for opcode {ins.op}")
        arg_val = ins.arg
    else:
        if ins.arg is not None:
            raise SerializationError(f"Opcode {ins.op} takes no argument, got {ins.arg!r}")
        arg_val = NO_ARG
    return struct.pack(">BI", op_num, arg_val)


def dumps(program: Program) -> bytes:
    body = bytearray()
    body.extend(struct.pack(">B", VERSION))

    if len(program.names) > 0xFFFF:
        raise SerializationError("Too many variable names")
    body.extend(struct.pack(">H", len(program.names)))
    for name in program.names:
        if not isinstance(name, str):
            raise SerializationError("Variable name must be a string")
        raw = name.encode("utf-8")
        if len(raw) > 0xFFFF:
            raise SerializationError("Variable name too long")
        body.extend(struct.pack(">H", len(raw)))
        body.extend(raw)

    if len(program.constants) > 0xFFFF:
        raise SerializationError("Too many constants")
    body.extend(struct.pack(">H", len(program.constants)))
    for c in program.constants:
        body.extend(_pack_constant(c))

    if len(program.instructions) > 0xFFFFFFFF:
        raise SerializationError("Too many instructions")
    body.extend(struct.pack(">I", len(program.instructions)))
    for ins in program.instructions:
        body.extend(_pack_instruction(ins))

    crc = zlib.crc32(body) & 0xFFFFFFFF
    return MAGIC + bytes(body) + struct.pack(">I", crc)


def _read_bytes(buf: bytes, pos: int, count: int) -> tuple[bytes, int]:
    if pos + count > len(buf):
        raise SerializationError("Unexpected end of binary data")
    return buf[pos : pos + count], pos + count


def _unpack_constants(buf: bytes, pos: int, count: int) -> tuple[list[object], int]:
    constants: list[object] = []
    for _ in range(count):
        raw_tag, pos = _read_bytes(buf, pos, 1)
        tag = raw_tag[0]
        if tag == TAG_INT:
            raw_val, pos = _read_bytes(buf, pos, 8)
            constants.append(struct.unpack(">q", raw_val)[0])
        elif tag == TAG_FLOAT:
            raw_val, pos = _read_bytes(buf, pos, 8)
            constants.append(struct.unpack(">d", raw_val)[0])
        elif tag == TAG_STRING:
            raw_len, pos = _read_bytes(buf, pos, 4)
            slen = struct.unpack(">I", raw_len)[0]
            raw_str, pos = _read_bytes(buf, pos, slen)
            try:
                constants.append(raw_str.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise SerializationError("Invalid UTF-8 in string constant") from exc
        elif tag == TAG_BOOL:
            raw_b, pos = _read_bytes(buf, pos, 1)
            bval = raw_b[0]
            if bval not in (0, 1):
                raise SerializationError(f"Invalid BOOL payload {bval}")
            constants.append(bool(bval))
        else:
            raise SerializationError(f"Unknown constant tag {tag:#x}")
    return constants, pos


def _unpack_instructions(buf: bytes, pos: int, count: int) -> tuple[list[Instr], int]:
    instructions: list[Instr] = []
    for _ in range(count):
        raw_ins, pos = _read_bytes(buf, pos, 5)
        op_num, arg_val = struct.unpack(">BI", raw_ins)
        if op_num not in NUMBER_TO_OPCODE:
            raise SerializationError(f"Unknown opcode number {op_num}")
        op_name = NUMBER_TO_OPCODE[op_num]
        takes_arg = op_name in ARG_OPCODES
        if takes_arg:
            if arg_val == NO_ARG:
                raise SerializationError(f"Missing argument for opcode {op_name}")
            instructions.append(Instr(op_name, arg_val))
        else:
            if arg_val != NO_ARG:
                raise SerializationError(f"Unexpected argument for opcode {op_name}")
            instructions.append(Instr(op_name, None))
    return instructions, pos


def loads(data: bytes) -> Program:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise SerializationError("Data must be bytes-like")
    buf = bytes(data)
    # Minimum size: 4 (magic) + 1 (version) + 2 (names) + 2 (consts) + 4 (instrs) + 4 (crc) = 17
    if len(buf) < 9:
        raise SerializationError("Data too short")
    if buf[:4] != MAGIC:
        raise SerializationError("Invalid magic header")
    expected_crc = struct.unpack(">I", buf[-4:])[0]
    body = buf[4:-4]
    actual_crc = zlib.crc32(body) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise SerializationError("Checksum mismatch")

    pos = 0
    raw_ver, pos = _read_bytes(body, pos, 1)
    if raw_ver[0] != VERSION:
        raise SerializationError(f"Unsupported version {raw_ver[0]}")

    raw_ncount, pos = _read_bytes(body, pos, 2)
    ncount = struct.unpack(">H", raw_ncount)[0]
    names: list[str] = []
    for _ in range(ncount):
        raw_nlen, pos = _read_bytes(body, pos, 2)
        nlen = struct.unpack(">H", raw_nlen)[0]
        raw_name, pos = _read_bytes(body, pos, nlen)
        try:
            names.append(raw_name.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise SerializationError("Invalid UTF-8 in variable name") from exc

    raw_ccount, pos = _read_bytes(body, pos, 2)
    ccount = struct.unpack(">H", raw_ccount)[0]
    constants, pos = _unpack_constants(body, pos, ccount)

    raw_icount, pos = _read_bytes(body, pos, 4)
    icount = struct.unpack(">I", raw_icount)[0]
    instructions, pos = _unpack_instructions(body, pos, icount)

    if pos != len(body):
        raise SerializationError("Trailing bytes in payload")
    return Program(constants=constants, names=names, instructions=instructions)
