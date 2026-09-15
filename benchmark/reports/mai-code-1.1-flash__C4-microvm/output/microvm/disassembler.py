from .compiler import Program
from .opcodes import ARG_OPCODE_NAMES


def _escape_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instr in enumerate(program.instructions):
        if instr.arg is None:
            lines.append(f"{index:04d} {instr.op}")
            continue
        line = f"{index:04d} {instr.op} {instr.arg}"
        if instr.op == "CONST":
            value = program.constants[instr.arg]
            if type(value) is bool:
                rendered = "true" if value else "false"
            elif type(value) is str:
                rendered = _escape_string(value)
            else:
                rendered = str(value)
            line += f"  ; {rendered}"
        lines.append(line)
    return "\n".join(lines) + "\n"
