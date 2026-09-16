import struct
import zlib
from .compiler import Program, Instr
from .opcodes import OPCODES, OPCODE_NUMBERS
from .errors import SerializationError


def dumps(program: Program) -> bytes:
    try:
        body = bytearray([1]); body += struct.pack(">H", len(program.names))
        for name in program.names:
            raw = name.encode(); body += struct.pack(">H", len(raw)) + raw
        body += struct.pack(">H", len(program.constants))
        for value in program.constants:
            if type(value) is int:
                if not -(1 << 63) <= value < (1 << 63): raise SerializationError("integer out of range")
                body += b"\x01" + struct.pack(">q", value)
            elif type(value) is float: body += b"\x02" + struct.pack(">d", value)
            elif type(value) is str:
                raw = value.encode(); body += b"\x03" + struct.pack(">I", len(raw)) + raw
            elif type(value) is bool: body += b"\x04" + bytes([value])
            else: raise SerializationError("unsupported constant")
        body += struct.pack(">I", len(program.instructions))
        for ins in program.instructions:
            if ins.op not in OPCODE_NUMBERS: raise SerializationError("unknown opcode")
            arg = 0xffffffff if ins.arg is None else ins.arg
            if ins.op in ("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE") and ins.arg is None: raise SerializationError("missing argument")
            if ins.op not in ("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE") and ins.arg is not None: raise SerializationError("unexpected argument")
            body += bytes([OPCODE_NUMBERS[ins.op]]) + struct.pack(">I", arg)
        return b"MVM1" + bytes(body) + struct.pack(">I", zlib.crc32(body) & 0xffffffff)
    except (struct.error, UnicodeError) as exc:
        raise SerializationError(str(exc)) from exc


def loads(data: bytes) -> Program:
    if not isinstance(data, (bytes, bytearray)) or len(data) < 9 or data[:4] != b"MVM1": raise SerializationError("bad magic or truncation")
    if len(data) < 8: raise SerializationError("truncation")
    body, checksum = data[4:-4], data[-4:]
    if zlib.crc32(body) & 0xffffffff != struct.unpack(">I", checksum)[0]: raise SerializationError("checksum mismatch")
    pos = 0
    def take(n: int) -> bytes:
        nonlocal pos
        if pos + n > len(body): raise SerializationError("truncation")
        x = body[pos:pos+n]; pos += n; return x
    def text(raw: bytes) -> str:
        try:
            return raw.decode("utf-8")
        except UnicodeError as exc:
            raise SerializationError("invalid UTF-8") from exc
    if take(1)[0] != 1: raise SerializationError("unsupported version")
    names = []
    for _ in range(struct.unpack(">H", take(2))[0]):
        names.append(text(take(struct.unpack(">H", take(2))[0])))
    constants = []
    for _ in range(struct.unpack(">H", take(2))[0]):
        tag = take(1)[0]
        if tag == 1: constants.append(struct.unpack(">q", take(8))[0])
        elif tag == 2: constants.append(struct.unpack(">d", take(8))[0])
        elif tag == 3: constants.append(text(take(struct.unpack(">I", take(4))[0])))
        elif tag == 4:
            value = take(1)[0]
            if value > 1: raise SerializationError("invalid bool")
            constants.append(bool(value))
        else: raise SerializationError("unknown constant tag")
    instructions = []
    for _ in range(struct.unpack(">I", take(4))[0]):
        num = take(1)[0]; arg = struct.unpack(">I", take(4))[0]
        if not 1 <= num <= len(OPCODES): raise SerializationError("unknown opcode")
        op = OPCODES[num-1]; takes = op in ("CONST", "LOAD", "STORE", "JUMP", "JUMP_IF_FALSE")
        if takes == (arg == 0xffffffff): raise SerializationError("invalid argument")
        instructions.append(Instr(op, None if arg == 0xffffffff else arg))
    if pos != len(body): raise SerializationError("trailing bytes")
    return Program(constants, names, instructions)
