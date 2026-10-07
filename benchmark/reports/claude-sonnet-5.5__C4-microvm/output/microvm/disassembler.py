"""Human-readable listing of a program."""

from .compiler import Program


def _render_constant(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        escaped = (
            value.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\t", "\\t")
        )
        return f'"{escaped}"'
    return str(value)


def disassemble(program: Program) -> str:
    lines = []
    for index, instr in enumerate(program.instructions):
        line = f"{index:04d} {instr.op}"
        if instr.arg is not None:
            line += f" {instr.arg}"
        pool = program.constants
        if instr.op == "CONST" and instr.arg is not None and 0 <= instr.arg < len(pool):
            line += f"  ; {_render_constant(pool[instr.arg])}"
        lines.append(line + "\n")
    return "".join(lines)
