import struct
import zlib
from .compiler import Program, Instr
from .errors import SerializationError
from .opcodes import OPCODE_NUMBERS


def _dump_const(data: bytearray, const) -> None:
    if isinstance(const, int):
        if const < -(2**63) or const >= 2**63:
            raise SerializationError("INT constant out of range")
        data.append(0x01)
        data.extend(struct.pack(">q", const))
    elif isinstance(const, float):
        data.append(0x02)
        data.extend(struct.pack(">d", const))
    elif isinstance(const, str):
        data.append(0x03)
        const_bytes = const.encode("utf-8")
        data.extend(struct.pack(">I", len(const_bytes)))
        data.extend(const_bytes)
    elif isinstance(const, bool):
        data.append(0x04)
        data.append(1 if const else 0)


def dumps(program: Program) -> bytes:
    data = bytearray()
    data.extend(b"MVM1")
    data.append(1)
    data.extend(struct.pack(">H", len(program.names)))
    for name in program.names:
        name_bytes = name.encode("utf-8")
        data.extend(struct.pack(">H", len(name_bytes)))
        data.extend(name_bytes)
    data.extend(struct.pack(">H", len(program.constants)))
    for const in program.constants:
        _dump_const(data, const)
    data.extend(struct.pack(">I", len(program.instructions)))
    for instr in program.instructions:
        op_num = OPCODE_NUMBERS[instr.op]
        data.append(op_num)
        arg = 0xFFFFFFFF if instr.arg is None else instr.arg
        data.extend(struct.pack(">I", arg))
    checksum = zlib.crc32(data) & 0xFFFFFFFF
    data.extend(struct.pack(">I", checksum))
    return bytes(data)


def _load_const(data: bytes, pos: int, tag: int) -> tuple[object, int]:
    if tag == 0x01:
        if pos + 8 > len(data):
            raise SerializationError("Truncated file")
        val = struct.unpack(">q", data[pos:pos+8])[0]
        return val, pos + 8
    elif tag == 0x02:
        if pos + 8 > len(data):
            raise SerializationError("Truncated file")
        val = struct.unpack(">d", data[pos:pos+8])[0]
        return val, pos + 8
    elif tag == 0x03:
        if pos + 4 > len(data):
            raise SerializationError("Truncated file")
        str_len = struct.unpack(">I", data[pos:pos+4])[0]
        pos += 4
        if pos + str_len > len(data):
            raise SerializationError("Truncated file")
        val = data[pos:pos+str_len].decode("utf-8")
        return val, pos + str_len
    elif tag == 0x04:
        if pos >= len(data):
            raise SerializationError("Truncated file")
        bool_val = data[pos]
        if bool_val not in (0, 1):
            raise SerializationError("Invalid bool value")
        return bool(bool_val), pos + 1
    else:
        raise SerializationError("Unknown constant tag")


def _load_constants(data: bytes, pos: int) -> tuple[list, int]:
    if pos + 2 > len(data):
        raise SerializationError("Truncated file")
    const_count = struct.unpack(">H", data[pos:pos+2])[0]
    pos += 2
    constants = []
    for _ in range(const_count):
        if pos >= len(data):
            raise SerializationError("Truncated file")
        tag = data[pos]
        pos += 1
        const_val, pos = _load_const(data, pos, tag)
        constants.append(const_val)
    return constants, pos


def _get_opcode_name(op_num: int) -> str:
    for name, num in OPCODE_NUMBERS.items():
        if num == op_num:
            return name
    raise SerializationError("Unknown opcode")


def _load_instructions_block(data: bytes, pos: int, instr_count: int) -> tuple[list, int]:
    instructions = []
    for _ in range(instr_count):
        if pos >= len(data):
            raise SerializationError("Truncated file")
        op_num = data[pos]
        pos += 1
        if pos + 4 > len(data):
            raise SerializationError("Truncated file")
        arg = struct.unpack(">I", data[pos:pos+4])[0]
        pos += 4
        op_name = _get_opcode_name(op_num)
        instructions.append(Instr(op_name, None if arg == 0xFFFFFFFF else arg))
    return instructions, pos


def loads(data: bytes) -> Program:
    if len(data) < 5:
        raise SerializationError("Truncated file")
    if data[:4] != b"MVM1":
        raise SerializationError("Bad magic")
    if data[4] != 1:
        raise SerializationError("Unsupported version")
    pos = 5
    if pos + 2 > len(data):
        raise SerializationError("Truncated file")
    name_count = struct.unpack(">H", data[pos:pos+2])[0]
    pos += 2
    names = []
    for _ in range(name_count):
        if pos + 2 > len(data):
            raise SerializationError("Truncated file")
        name_len = struct.unpack(">H", data[pos:pos+2])[0]
        pos += 2
        if pos + name_len > len(data):
            raise SerializationError("Truncated file")
        names.append(data[pos:pos+name_len].decode("utf-8"))
        pos += name_len
    constants, pos = _load_constants(data, pos)
    if pos + 4 > len(data):
        raise SerializationError("Truncated file")
    instr_count = struct.unpack(">I", data[pos:pos+4])[0]
    pos += 4
    stored_checksum_pos = pos + instr_count * 5
    if stored_checksum_pos + 4 > len(data):
        raise SerializationError("Truncated file")
    stored_checksum = struct.unpack(">I", data[stored_checksum_pos:stored_checksum_pos+4])[0]
    calc_checksum = zlib.crc32(data[:stored_checksum_pos]) & 0xFFFFFFFF
    if calc_checksum != stored_checksum:
        raise SerializationError("Checksum mismatch")
    instructions, pos = _load_instructions_block(data, pos, instr_count)
    if pos != stored_checksum_pos:
        raise SerializationError("Instruction count mismatch")
    if len(data) != stored_checksum_pos + 4:
        raise SerializationError("Trailing bytes")
    return Program(constants, names, instructions)
