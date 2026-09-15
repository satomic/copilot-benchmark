"""Command-line interface: python -m microvm run|build|exec|disasm ..."""

import argparse
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MICROVM = 3


def _positive_int(text: str) -> int:
    value = int(text)  # ValueError -> argparse usage error (exit 2)
    if value <= 0:
        raise ValueError("step limit must be a positive integer")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="compile and execute a source file")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=100_000)
    build = sub.add_parser("build", help="compile a source file to binary")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")
    exe = sub.add_parser("exec", help="execute a binary file")
    exe.add_argument("file")
    exe.add_argument("--step-limit", type=_positive_int, default=100_000)
    dis = sub.add_parser("disasm", help="disassemble a binary file")
    dis.add_argument("file")
    return parser


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc


def _read_binary(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc


def _run(args: argparse.Namespace) -> str:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    lines = execute(program, step_limit=args.step_limit)
    return "".join(line + "\n" for line in lines)


def _build(args: argparse.Namespace) -> str:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    data = dumps(program)
    try:
        with open(args.out, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from exc
    return ""


def _exec(args: argparse.Namespace) -> str:
    lines = execute(loads(_read_binary(args.file)), step_limit=args.step_limit)
    return "".join(line + "\n" for line in lines)


def _disasm(args: argparse.Namespace) -> str:
    return disassemble(loads(_read_binary(args.file)))


_HANDLERS = {"run": _run, "build": _build, "exec": _exec, "disasm": _disasm}


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        output = _HANDLERS[args.command](args)  # buffered until full success
    except SystemExit as exc:  # argparse usage errors and unreadable files
        return int(exc.code) if exc.code is not None else EXIT_OK
    except MicroVMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MICROVM
    print(output, end="")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
