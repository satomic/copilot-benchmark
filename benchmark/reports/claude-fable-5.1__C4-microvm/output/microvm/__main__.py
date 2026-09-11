"""Command-line interface: ``python -m microvm COMMAND ...``."""

from __future__ import annotations

import argparse
import sys

from .compiler import Program, compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_ERROR = 3


class _UsageError(Exception):
    """Raised for I/O problems that count as usage errors (exit code 2)."""


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid positive integer {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"step limit must be positive, got {value}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm", description="microvm toolchain")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="compile a source file and execute it")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=100_000)

    build = sub.add_parser("build", help="compile a source file to a binary")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")

    exe = sub.add_parser("exec", help="execute a compiled binary")
    exe.add_argument("file")
    exe.add_argument("--step-limit", type=_positive_int, default=100_000)

    disasm = sub.add_parser("disasm", help="disassemble a compiled binary")
    disasm.add_argument("file")
    return parser


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from exc


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from exc


def _write_bytes(path: str, data: bytes) -> None:
    try:
        with open(path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise _UsageError(f"cannot write {path}: {exc}") from exc


def _dispatch(args: argparse.Namespace) -> str:
    """Perform the command and return the full stdout text (printed only on success)."""
    if args.command == "run":
        program = compile_source(_read_text(args.file), optimize=args.optimize)
        return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))
    if args.command == "build":
        program = compile_source(_read_text(args.file), optimize=args.optimize)
        _write_bytes(args.out, dumps(program))
        return ""
    if args.command == "exec":
        program: Program = loads(_read_bytes(args.file))
        return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))
    if args.command == "disasm":
        return disassemble(loads(_read_bytes(args.file)))
    raise _UsageError(f"unknown command {args.command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed its message
        code = exc.code
        return code if isinstance(code, int) else EXIT_USAGE
    try:
        output = _dispatch(args)
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except MicroVMError as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    sys.stdout.write(output)
    sys.stdout.flush()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
