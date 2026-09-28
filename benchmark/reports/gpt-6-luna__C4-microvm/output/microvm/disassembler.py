from .compiler import Program


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instr in enumerate(program.instructions):
        line = f"{index:04d} {instr.op}"
        if instr.arg is not None:
            line += f" {instr.arg}"
            if instr.op == "CONST" and 0 <= instr.arg < len(program.constants):
                line += f"  ; {_constant(program.constants[instr.arg])}"
        lines.append(line)
    return "".join(line + "\n" for line in lines)


def _constant(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'
    return str(value)
