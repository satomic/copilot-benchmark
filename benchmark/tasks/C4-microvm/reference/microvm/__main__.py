"""CLI: run / build / exec / disasm."""

from __future__ import annotations

import argparse
import pathlib
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute

__all__ = ["build_parser", "main"]

_USAGE_EXIT = 2
_ERROR_EXIT = 3


class _UsageError(Exception):
    """Anything that should exit with code 2."""


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError("step limit must be positive")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm", allow_abbrev=False)
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("run", allow_abbrev=False)
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=100_000)
    build = subs.add_parser("build", allow_abbrev=False)
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")
    execp = subs.add_parser("exec", allow_abbrev=False)
    execp.add_argument("file")
    execp.add_argument("--step-limit", type=_positive_int, default=100_000)
    disasm = subs.add_parser("disasm", allow_abbrev=False)
    disasm.add_argument("file")
    return parser


def _read_text(path: str) -> str:
    try:
        return pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from None


def _read_bytes(path: str) -> bytes:
    try:
        return pathlib.Path(path).read_bytes()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from None


def _run(args: argparse.Namespace) -> str:
    """Produce the full stdout text; raising means nothing reaches stdout."""
    if args.command == "run":
        program = compile_source(_read_text(args.file), optimize=args.optimize)
        return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))
    if args.command == "build":
        program = compile_source(_read_text(args.file), optimize=args.optimize)
        try:
            pathlib.Path(args.out).write_bytes(dumps(program))
        except OSError as exc:
            raise _UsageError(f"cannot write {args.out}: {exc}") from None
        return ""
    if args.command == "exec":
        program = loads(_read_bytes(args.file))
        return "".join(line + "\n" for line in execute(program, step_limit=args.step_limit))
    return disassemble(loads(_read_bytes(args.file)))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _USAGE_EXIT if exc.code else 0
    try:
        text = _run(args)
    except _UsageError as exc:
        print(str(exc), file=sys.stderr)
        return _USAGE_EXIT
    except MicroVMError as exc:
        print(str(exc), file=sys.stderr)
        return _ERROR_EXIT
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
