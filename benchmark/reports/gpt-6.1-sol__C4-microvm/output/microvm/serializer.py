import struct
import zlib

from .compiler import Instr, Program
from .errors import SerializationError
from .opcodes import ARG_OPCODES, OPCODES, OPCODE_NUMBERS
from .parser import Value


_SENTINEL = 0xFFFFFFFF


def _pack(fmt: str, value: int | float) -> bytes:
    try:
        return struct.pack(">" + fmt, value)
    except (struct.error, OverflowError) as error:
        raise SerializationError(f"Value outside {fmt} encoding range") from error


def _text(value: str, fmt: str) -> bytes:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SerializationError("Invalid UTF-8 text") from error
    return _pack(fmt, len(encoded)) + encoded


def _constant(value: Value) -> bytes:
    if type(value) is bool:
        return b"\x04" + bytes((int(value),))
    if type(value) is int:
        return b"\x01" + _pack("q", value)
    if type(value) is float:
        return b"\x02" + _pack("d", value)
    if type(value) is str:
        assert isinstance(value, str)
        return b"\x03" + _text(value, "I")
    raise SerializationError(f"Unsupported constant type: {type(value).__name__}")


def _validate(program: Program) -> None:
    instructions = program.instructions
    if not instructions or instructions[-1].op != "HALT":
        raise SerializationError("Program must end with HALT")
    for index, instruction in enumerate(instructions):
        if instruction.op not in OPCODE_NUMBERS:
            raise SerializationError(f"Unknown opcode: {instruction.op}")
        if instruction.op == "HALT" and index != len(instructions) - 1:
            raise SerializationError("HALT may only appear at the end")
        arg = instruction.arg
        if instruction.op not in ARG_OPCODES:
            if arg is not None:
                raise SerializationError(f"{instruction.op} takes no argument")
            continue
        if type(arg) is not int or not 0 <= arg < _SENTINEL:
            raise SerializationError(f"Invalid argument for {instruction.op}")
        bounds = {
            "CONST": len(program.constants), "LOAD": len(program.names),
            "STORE": len(program.names), "JUMP": len(instructions),
            "JUMP_IF_FALSE": len(instructions),
        }
        if arg >= bounds[instruction.op]:
            raise SerializationError(f"{instruction.op} index out of bounds")


def dumps(program: Program) -> bytes:
    _validate(program)
    body = bytearray(b"\x01")
    body.extend(_pack("H", len(program.names)))
    for name in program.names:
        if not isinstance(name, str):
            raise SerializationError("Variable names must be strings")
        body.extend(_text(name, "H"))
    body.extend(_pack("H", len(program.constants)))
    for constant in program.constants:
        body.extend(_constant(constant))
    body.extend(_pack("I", len(program.instructions)))
    for instruction in program.instructions:
        body.append(OPCODE_NUMBERS[instruction.op])
        arg = _SENTINEL if instruction.arg is None else instruction.arg
        body.extend(_pack("I", arg))
    return b"MVM1" + bytes(body) + _pack("I", zlib.crc32(body))


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.index = 0

    def take(self, size: int) -> bytes:
        if size > len(self.data) - self.index:
            raise SerializationError("Truncated binary program")
        result = self.data[self.index:self.index + size]
        self.index += size
        return result

    def integer(self, fmt: str) -> int:
        return struct.unpack(">" + fmt, self.take(struct.calcsize(">" + fmt)))[0]

    def text(self, fmt: str) -> str:
        data = self.take(self.integer(fmt))
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SerializationError("Invalid UTF-8 text") from error

    def constant(self) -> Value:
        tag = self.integer("B")
        if tag == 1:
            return self.integer("q")
        if tag == 2:
            return struct.unpack(">d", self.take(8))[0]
        if tag == 3:
            return self.text("I")
        if tag == 4:
            value = self.integer("B")
            if value not in (0, 1):
                raise SerializationError("Invalid BOOL payload")
            return bool(value)
        raise SerializationError(f"Unknown constant tag: {tag}")

    def instructions(self) -> list[Instr]:
        count = self.integer("I")
        if count > (len(self.data) - self.index) // 5:
            raise SerializationError("Truncated instruction list")
        result: list[Instr] = []
        for _ in range(count):
            number = self.integer("B")
            if not 1 <= number <= len(OPCODES):
                raise SerializationError(f"Unknown opcode number: {number}")
            op = OPCODES[number - 1]
            arg = self.integer("I")
            if op in ARG_OPCODES:
                if arg == _SENTINEL:
                    raise SerializationError(f"{op} requires an argument")
                result.append(Instr(op, arg))
            else:
                if arg != _SENTINEL:
                    raise SerializationError(f"{op} takes no argument")
                result.append(Instr(op, None))
        return result


def loads(data: bytes) -> Program:
    if not isinstance(data, bytes):
        raise SerializationError("Expected bytes")
    if len(data) < 9:
        raise SerializationError("Truncated binary program")
    if data[:4] != b"MVM1":
        raise SerializationError("Bad magic")
    body = data[4:-4]
    checksum = struct.unpack(">I", data[-4:])[0]
    # No counts or lengths are interpreted until integrity has been checked.
    if zlib.crc32(body) != checksum:
        raise SerializationError("Checksum mismatch")
    reader = _Reader(body)
    if reader.integer("B") != 1:
        raise SerializationError("Unsupported version")
    names = [reader.text("H") for _ in range(reader.integer("H"))]
    constants = [reader.constant() for _ in range(reader.integer("H"))]
    instructions = reader.instructions()
    if reader.index != len(body):
        raise SerializationError("Trailing bytes after program")
    program = Program(constants, names, instructions)
    _validate(program)
    return program
