"""Command line interface for microvm."""

import argparse
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


def _positive_int(value: str) -> int:
    try:
        iv = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid step limit: {value!r}") from exc
    if iv <= 0:
        raise argparse.ArgumentTypeError("step limit must be a positive integer")
    return iv


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run")
    run_p.add_argument("file")
    run_p.add_argument("--optimize", action="store_true")
    run_p.add_argument("--step-limit", type=_positive_int, default=100_000)

    build_p = sub.add_parser("build")
    build_p.add_argument("file")
    build_p.add_argument("out")
    build_p.add_argument("--optimize", action="store_true")

    exec_p = sub.add_parser("exec")
    exec_p.add_argument("file")
    exec_p.add_argument("--step-limit", type=_positive_int, default=100_000)

    disasm_p = sub.add_parser("disasm")
    disasm_p.add_argument("file")

    return parser


def _run_command(args: argparse.Namespace) -> list[str]:
    with open(args.file, "r", encoding="utf-8") as fh:
        src = fh.read()
    program = compile_source(src, optimize=args.optimize)
    return execute(program, step_limit=args.step_limit)


def _build_command(args: argparse.Namespace) -> list[str]:
    with open(args.file, "r", encoding="utf-8") as fh:
        src = fh.read()
    program = compile_source(src, optimize=args.optimize)
    data = dumps(program)
    with open(args.out, "wb") as fh:
        fh.write(data)
    return []


def _exec_command(args: argparse.Namespace) -> list[str]:
    with open(args.file, "rb") as fh:
        data = fh.read()
    program = loads(data)
    return execute(program, step_limit=args.step_limit)


def _disasm_command(args: argparse.Namespace) -> list[str]:
    with open(args.file, "rb") as fh:
        data = fh.read()
    program = loads(data)
    return disassemble(program).splitlines()


_HANDLERS = {
    "run": _run_command,
    "build": _build_command,
    "exec": _exec_command,
    "disasm": _disasm_command,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    handler = _HANDLERS.get(args.command)
    if handler is None:
        return 2
    try:
        lines = handler(args)
    except MicroVMError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
