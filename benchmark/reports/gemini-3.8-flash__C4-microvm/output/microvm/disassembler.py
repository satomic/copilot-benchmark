"""Disassembler for microvm programs."""

from microvm.compiler import Program


def _format_constant(c: object) -> str:
    if type(c) is bool:
        return "true" if c else "false"
    if type(c) is int or type(c) is float:
        return str(c)
    if type(c) is str:
        chars: list[str] = []
        for ch in c:
            if ch == "\\":
                chars.append("\\\\")
            elif ch == '"':
                chars.append('\\"')
            elif ch == "\n":
                chars.append("\\n")
            elif ch == "\t":
                chars.append("\\t")
            else:
                chars.append(ch)
        return '"' + "".join(chars) + '"'
    return str(c)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instr in enumerate(program.instructions):
        if instr.op == "CONST":
            rendered = _format_constant(program.constants[instr.arg])  # type: ignore[index]
            lines.append(f"{index:04d} CONST {instr.arg}  ; {rendered}\n")
        elif instr.arg is not None:
            lines.append(f"{index:04d} {instr.op} {instr.arg}\n")
        else:
            lines.append(f"{index:04d} {instr.op}\n")
    return "".join(lines)
