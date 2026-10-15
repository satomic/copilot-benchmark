"""Command-line interface: ``python -m microvm COMMAND ...``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute

DEFAULT_STEP_LIMIT = 100_000


class _UsageError(Exception):
    """Unreadable file or other usage problem; maps to exit code 2."""


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm", description="MicroVM bytecode tools")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="compile a source file and execute it")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=DEFAULT_STEP_LIMIT)

    build = sub.add_parser("build", help="compile a source file to binary")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")

    exec_cmd = sub.add_parser("exec", help="execute a compiled binary")
    exec_cmd.add_argument("file")
    exec_cmd.add_argument("--step-limit", type=_positive_int, default=DEFAULT_STEP_LIMIT)

    disasm = sub.add_parser("disasm", help="disassemble a compiled binary")
    disasm.add_argument("file")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    handlers: dict[str, Callable[[argparse.Namespace], int]] = {
        "run": _cmd_run,
        "build": _cmd_build,
        "exec": _cmd_exec,
        "disasm": _cmd_disasm,
    }
    try:
        return handlers[args.command](args)
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


def _cmd_run(args: argparse.Namespace) -> int:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    return _emit(execute(program, step_limit=args.step_limit))


def _cmd_build(args: argparse.Namespace) -> int:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    _write_bytes(args.out, dumps(program))
    return 0


def _cmd_exec(args: argparse.Namespace) -> int:
    program = loads(_read_bytes(args.file))
    return _emit(execute(program, step_limit=args.step_limit))


def _cmd_disasm(args: argparse.Namespace) -> int:
    sys.stdout.write(disassemble(loads(_read_bytes(args.file))))
    return 0


def _emit(lines: list[str]) -> int:
    """Print output only after the whole run succeeded."""
    sys.stdout.write("".join(line + "\n" for line in lines))
    return 0


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from exc


def _read_bytes(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from exc


def _write_bytes(path: str, data: bytes) -> None:
    try:
        Path(path).write_bytes(data)
    except OSError as exc:
        raise _UsageError(f"cannot write {path}: {exc}") from exc


if __name__ == "__main__":
    sys.exit(main())
