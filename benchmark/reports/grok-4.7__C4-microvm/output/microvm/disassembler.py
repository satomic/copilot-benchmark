from microvm.compiler import Instr, Program


def disassemble(program: Program) -> str:
    lines = [
        _format_line(index, instr, program)
        for index, instr in enumerate(program.instructions)
    ]
    return "".join(f"{line}\n" for line in lines)


def _format_line(index: int, instr: Instr, program: Program) -> str:
    if instr.arg is None:
        return f"{index:04d} {instr.op}"
    text = f"{index:04d} {instr.op} {instr.arg}"
    if instr.op != "CONST":
        return text
    return f"{text}  ; {_render_constant(program.constants[instr.arg])}"


def _render_constant(value: object) -> str:
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return '"' + _escape(value) + '"'
    return str(value)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
