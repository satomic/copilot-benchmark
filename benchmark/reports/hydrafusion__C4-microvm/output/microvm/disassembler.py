from .compiler import Program


def _constant_text(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        escaped = value.replace("\\", "\\\\").replace("\n", "\\n")
        escaped = escaped.replace("\t", "\\t").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


def disassemble(program: Program) -> str:
    lines: list[str] = []
    for index, instruction in enumerate(program.instructions):
        line = f"{index:04d} {instruction.op}"
        if instruction.arg is not None:
            line += f" {instruction.arg}"
        if instruction.op == "CONST" and instruction.arg is not None:
            line += f"  ; {_constant_text(program.constants[instruction.arg])}"
        lines.append(line)
    return "".join(line + "\n" for line in lines)
