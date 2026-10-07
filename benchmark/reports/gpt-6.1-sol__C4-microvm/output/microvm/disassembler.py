from .compiler import Program
from .parser import Value
from .vm import render


def _render_constant(value: Value) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("\n", "\\n")
        escaped = escaped.replace("\t", "\\t").replace('"', '\\"')
        return '"' + escaped + '"'
    return render(value)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instruction in enumerate(program.instructions):
        line = f"{index:04d} {instruction.op}"
        if instruction.arg is not None:
            line += f" {instruction.arg}"
        if instruction.op == "CONST":
            assert instruction.arg is not None
            line += "  ; " + _render_constant(program.constants[instruction.arg])
        lines.append(line + "\n")
    return "".join(lines)
