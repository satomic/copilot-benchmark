import struct
import zlib

from microvm.errors import SerializationError
from microvm.compiler import Program, Instr
from microvm.opcodes import OPCODES, OPCODE_NUMBERS

MAGIC = b"MVM1"
VERSION = 1


def _write_names(program: Program) -> bytearray:
    buf = bytearray()
    for name in program.names:
        encoded = name.encode("utf-8")
        if len(encoded) > 65535:
            raise SerializationError("Name too long")
        buf += struct.pack(">H", len(encoded))
        buf += encoded
    return buf


def _write_constants(program: Program) -> bytearray:
    buf = bytearray()
    for c in program.constants:
        if isinstance(c, int):
            if c < -2**63 or c >= 2**63:
                raise SerializationError("INT constant out of range for signed i64")
            buf += b"\x01" + struct.pack(">q", c)
        elif isinstance(c, float):
            buf += b"\x02" + struct.pack(">d", c)
        elif isinstance(c, str):
            encoded = c.encode("utf-8")
            buf += b"\x03" + struct.pack(">I", len(encoded)) + encoded
        elif isinstance(c, bool):
            buf += b"\x04" + struct.pack(">B", 1 if c else 0)
        else:
            raise SerializationError(f"Unsupported constant type: {type(c)}")
    return buf


def _write_instructions(program: Program) -> bytearray:
    buf = bytearray()
    for instr in program.instructions:
        opcode = OPCODE_NUMBERS.get(instr.op)
        if opcode is None:
            raise SerializationError(f"Unknown opcode: {instr.op}")
        buf += struct.pack(">B", opcode)
        if instr.arg is not None:
            buf += struct.pack(">I", instr.arg)
        else:
            buf += struct.pack(">I", 0xFFFFFFFF)
    return buf


def dumps(program: Program) -> bytes:
    body = bytearray()
    names_data = _write_names(program)
    body += struct.pack(">H", len(program.names))
    body += names_data
    const_data = _write_constants(program)
    body += struct.pack(">H", len(program.constants))
    body += const_data
    instr_data = _write_instructions(program)
    body += struct.pack(">I", len(program.instructions))
    body += instr_data

    result = bytearray()
    result += MAGIC
    payload_start = len(result)
    result += struct.pack(">B", VERSION)
    result += body
    checksum = zlib.crc32(bytes(result[payload_start:])) & 0xFFFFFFFF
    result += struct.pack(">I", checksum)
    return bytes(result)


def _read_names(payload: bytes, pos: int) -> tuple[list[str], int]:
    if pos + 2 > len(payload):
        raise SerializationError("Truncated: name count")
    count = struct.unpack(">H", payload[pos:pos + 2])[0]
    pos += 2
    names: list[str] = []
    for _ in range(count):
        if pos + 2 > len(payload):
            raise SerializationError("Truncated: name length")
        nlen = struct.unpack(">H", payload[pos:pos + 2])[0]
        pos += 2
        if pos + nlen > len(payload):
            raise SerializationError("Truncated: name data")
        names.append(payload[pos:pos + nlen].decode("utf-8"))
        pos += nlen
    return names, pos


def _read_constants(payload: bytes, pos: int) -> tuple[list[object], int]:
    if pos + 2 > len(payload):
        raise SerializationError("Truncated: constant count")
    count = struct.unpack(">H", payload[pos:pos + 2])[0]
    pos += 2
    constants: list[object] = []
    for _ in range(count):
        if pos >= len(payload):
            raise SerializationError("Truncated: constant tag")
        tag = payload[pos]
        pos += 1
        if tag == 0x01:  # INT
            if pos + 8 > len(payload):
                raise SerializationError("Truncated: INT")
            constants.append(struct.unpack(">q", payload[pos:pos + 8])[0])
            pos += 8
        elif tag == 0x02:  # FLOAT
            if pos + 8 > len(payload):
                raise SerializationError("Truncated: FLOAT")
            constants.append(struct.unpack(">d", payload[pos:pos + 8])[0])
            pos += 8
        elif tag == 0x03:  # STRING
            if pos + 4 > len(payload):
                raise SerializationError("Truncated: STRING length")
            slen = struct.unpack(">I", payload[pos:pos + 4])[0]
            pos += 4
            if pos + slen > len(payload):
                raise SerializationError("Truncated: STRING data")
            constants.append(payload[pos:pos + slen].decode("utf-8"))
            pos += slen
        elif tag == 0x04:  # BOOL
            if pos >= len(payload):
                raise SerializationError("Truncated: BOOL")
            bval = payload[pos]
            if bval not in (0, 1):
                raise SerializationError(f"Invalid BOOL value: {bval}")
            constants.append(bval == 1)
            pos += 1
        else:
            raise SerializationError(f"Unknown constant tag: {tag:#04x}")
    return constants, pos


def _read_instructions(payload: bytes, pos: int) -> tuple[list[Instr], int]:
    opcode_to_name = {v: k for k, v in OPCODE_NUMBERS.items()}
    takes_arg_set = {"CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE"}
    if pos + 4 > len(payload):
        raise SerializationError("Truncated: instruction count")
    count = struct.unpack(">I", payload[pos:pos + 4])[0]
    pos += 4
    instrs: list[Instr] = []
    for _ in range(count):
        if pos >= len(payload):
            raise SerializationError("Truncated: opcode")
        opcode = payload[pos]
        pos += 1
        op_name = opcode_to_name.get(opcode)
        if op_name is None:
            raise SerializationError(f"Unknown opcode number: {opcode}")
        if pos + 4 > len(payload):
            raise SerializationError("Truncated: arg")
        arg_raw = struct.unpack(">I", payload[pos:pos + 4])[0]
        pos += 4
        if op_name in takes_arg_set:
            if arg_raw == 0xFFFFFFFF:
                raise SerializationError(f"Opcode {op_name} requires an argument")
            instrs.append(Instr(op_name, arg_raw))
        else:
            if arg_raw != 0xFFFFFFFF:
                raise SerializationError(f"Opcode {op_name} takes no argument")
            instrs.append(Instr(op_name, None))
    return instrs, pos


def loads(data: bytes) -> Program:
    if len(data) < 8:
        raise SerializationError("Data too short")
    if data[:4] != MAGIC:
        raise SerializationError("Bad magic")
    if data[4] != VERSION:
        raise SerializationError(f"Unsupported version: {data[4]}")

    checksum_start = len(data) - 4
    stored_crc = struct.unpack(">I", data[checksum_start:])[0]
    computed_crc = zlib.crc32(data[4:checksum_start]) & 0xFFFFFFFF
    if stored_crc != computed_crc:
        raise SerializationError("Checksum mismatch")

    payload = data[4:checksum_start]
    pos = 1
    names, pos = _read_names(payload, pos)
    constants, pos = _read_constants(payload, pos)
    instrs, pos = _read_instructions(payload, pos)
    if pos != len(payload):
        raise SerializationError("Trailing bytes after instruction decoding")
    return Program(constants=constants, names=names, instructions=instrs)