import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import ARG_OPCODE_NAMES, OPCODE_NUMBERS


def _int64_payload(value: int) -> bytes:
    if value < -(1 << 63) or value > (1 << 63) - 1:
        raise SerializationError("INT constant out of range")
    return value.to_bytes(8, byteorder="big", signed=True)


def _encode_constant(value: object) -> tuple[int, bytes]:
    if type(value) is int:
        return 0x01, _int64_payload(value)
    if type(value) is float:
        return 0x02, struct.pack(">d", value)
    if type(value) is str:
        raw = value.encode("utf-8")
        return 0x03, len(raw).to_bytes(4, "big") + raw
    if type(value) is bool:
        return 0x04, b"\x01" if value else b"\x00"
    raise SerializationError(f"Unsupported constant type: {type(value).__name__}")


def _read_name(payload: bytes, pos: int) -> tuple[str, int]:
    if pos + 2 > len(payload):
        raise SerializationError("Truncated name length")
    length = int.from_bytes(payload[pos:pos + 2], "big")
    pos += 2
    if pos + length > len(payload):
        raise SerializationError("Truncated name value")
    return payload[pos:pos + length].decode("utf-8"), pos + length


def _read_constant(payload: bytes, pos: int) -> tuple[object, int]:
    if pos >= len(payload):
        raise SerializationError("Truncated constant tag")
    tag = payload[pos]
    pos += 1
    if tag == 0x01:
        if pos + 8 > len(payload):
            raise SerializationError("Truncated INT constant")
        return int.from_bytes(payload[pos:pos + 8], "big", signed=True), pos + 8
    if tag == 0x02:
        if pos + 8 > len(payload):
            raise SerializationError("Truncated FLOAT constant")
        return struct.unpack(">d", payload[pos:pos + 8])[0], pos + 8
    if tag == 0x03:
        if pos + 4 > len(payload):
            raise SerializationError("Truncated STRING length")
        length = int.from_bytes(payload[pos:pos + 4], "big")
        pos += 4
        if pos + length > len(payload):
            raise SerializationError("Truncated STRING data")
        return payload[pos:pos + length].decode("utf-8"), pos + length
    if tag == 0x04:
        if pos >= len(payload):
            raise SerializationError("Truncated BOOL constant")
        value = payload[pos]
        if value not in (0, 1):
            raise SerializationError("BOOL payload must be 0 or 1")
        return value == 1, pos + 1
    raise SerializationError(f"Unknown constant tag: {tag:#x}")


def _read_instruction(payload: bytes, pos: int) -> tuple[Instr, int]:
    if pos >= len(payload):
        raise SerializationError("Truncated opcode")
    opcode_num = payload[pos]
    pos += 1
    reverse = {value: key for key, value in OPCODE_NUMBERS.items()}
    if opcode_num not in reverse:
        raise SerializationError(f"Unknown opcode number: {opcode_num}")
    opcode = reverse[opcode_num]
    if pos + 4 > len(payload):
        raise SerializationError("Truncated instruction argument")
    value = int.from_bytes(payload[pos:pos + 4], "big")
    pos += 4
    if opcode in ARG_OPCODE_NAMES:
        if value == 0xFFFFFFFF:
            raise SerializationError(f"Missing argument for {opcode}")
        return Instr(opcode, value), pos
    if value != 0xFFFFFFFF:
        raise SerializationError(f"Unexpected argument for {opcode}")
    return Instr(opcode, None), pos


def _emit_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    return len(raw).to_bytes(2, "big") + raw


def dumps(program: Program) -> bytes:
    body = bytearray(b"MVM1\x01")
    body.extend(len(program.names).to_bytes(2, "big"))
    for name in program.names:
        body.extend(_emit_name(name))
    body.extend(len(program.constants).to_bytes(2, "big"))
    for value in program.constants:
        tag, payload = _encode_constant(value)
        body.append(tag)
        body.extend(payload)
    body.extend(len(program.instructions).to_bytes(4, "big"))
    for instr in program.instructions:
        body.append(OPCODE_NUMBERS[instr.op])
        if instr.op in ARG_OPCODE_NAMES:
            if instr.arg is None:
                raise SerializationError(f"Missing arg for {instr.op}")
            body.extend(int(instr.arg).to_bytes(4, "big"))
        else:
            body.extend((0xFFFFFFFF).to_bytes(4, "big"))
    checksum = zlib.crc32(body[4:]) & 0xFFFFFFFF
    return bytes(body) + checksum.to_bytes(4, "big")


def loads(data: bytes) -> Program:
    if not isinstance(data, (bytes, bytearray)):
        raise SerializationError("Input must be bytes")
    blob = bytes(data)
    if len(blob) < 17 or blob[:4] != b"MVM1":
        raise SerializationError("Bad magic")
    if blob[4] != 1:
        raise SerializationError("Unsupported version")
    payload = blob[4:-4]
    if zlib.crc32(payload) & 0xFFFFFFFF != int.from_bytes(blob[-4:], "big"):
        raise SerializationError("Checksum mismatch")
    pos = 0
    if payload[pos] != 1:
        raise SerializationError("Unsupported version")
    pos += 1
    names: list[str] = []
    count = int.from_bytes(payload[pos:pos + 2], "big")
    pos += 2
    for _ in range(count):
        name, pos = _read_name(payload, pos)
        names.append(name)
    const_count = int.from_bytes(payload[pos:pos + 2], "big")
    pos += 2
    constants: list[object] = []
    for _ in range(const_count):
        value, pos = _read_constant(payload, pos)
        constants.append(value)
    instr_count = int.from_bytes(payload[pos:pos + 4], "big")
    pos += 4
    instructions: list[Instr] = []
    for _ in range(instr_count):
        instr, pos = _read_instruction(payload, pos)
        instructions.append(instr)
    if pos != len(payload):
        raise SerializationError("Trailing bytes after checksum")
    return Program(constants, names, instructions)
