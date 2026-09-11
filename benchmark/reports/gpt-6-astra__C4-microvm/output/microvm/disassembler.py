from .compiler import Program
from .vm import _Value, _render


def _literal(value: _Value) -> str:
    if type(value) is str:
        escaped = value.replace("\\", "\\\\").replace("\n", "\\n")
        escaped = escaped.replace("\t", "\\t").replace('"', '\\"')
        return f'"{escaped}"'
    return _render(value)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instr in enumerate(program.instructions):
        line = f"{index:04d} {instr.op}"
        if instr.arg is not None:
            line += f" {instr.arg}"
        if instr.op == "CONST" and instr.arg is not None:
            line += f"  ; {_literal(program.constants[instr.arg])}"
        lines.append(line + "\n")
    return "".join(lines)
