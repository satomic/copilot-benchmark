"""Human-readable rendering of compiled Programs."""

from .compiler import Program


def _render_constant(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace('"', '\\"')
        )
        return f'"{escaped}"'
    return str(value)


def disassemble(program: Program) -> str:
    """Return one line per instruction in the canonical assembly format."""
    lines: list[str] = []
    for index, ins in enumerate(program.instructions):
        line = f"{index:04d} {ins.op}"
        if ins.arg is not None:
            line += f" {ins.arg}"
        if ins.op == "CONST":
            line += f"  ; {_render_constant(program.constants[ins.arg])}"
        lines.append(line + "\n")
    return "".join(lines)
