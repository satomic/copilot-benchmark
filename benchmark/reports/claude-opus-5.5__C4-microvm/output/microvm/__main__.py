"""Command-line interface: ``python -m microvm {run,build,exec,disasm} ...``."""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute


class _UsageError(Exception):
    """A problem with the invocation itself (exit code 2)."""


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {text!r}")
    return value


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc.strerror or exc}") from None


def _read_source(path: str) -> str:
    raw = _read_bytes(path)
    # Tolerate BOMs, e.g. files produced by Windows shell redirection.
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        raise _UsageError(f"cannot read {path}: not valid {encoding} text") from None


def _lines(output: list[str]) -> str:
    return "".join(line + "\n" for line in output)


def _cmd_run(args: argparse.Namespace) -> str:
    program = compile_source(_read_source(args.file), optimize=args.optimize)
    return _lines(execute(program, step_limit=args.step_limit))


def _cmd_build(args: argparse.Namespace) -> str:
    data = dumps(compile_source(_read_source(args.file), optimize=args.optimize))
    try:
        with open(args.out, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise _UsageError(f"cannot write {args.out}: {exc.strerror or exc}") from None
    return ""


def _cmd_exec(args: argparse.Namespace) -> str:
    return _lines(execute(loads(_read_bytes(args.file)), step_limit=args.step_limit))


def _cmd_disasm(args: argparse.Namespace) -> str:
    return disassemble(loads(_read_bytes(args.file)))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm", description="microvm compiler and VM")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    run = sub.add_parser("run", help="compile and execute a source file")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=_positive_int, default=100_000)
    run.set_defaults(handler=_cmd_run)
    build = sub.add_parser("build", help="compile a source file to a binary")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")
    build.set_defaults(handler=_cmd_build)
    exe = sub.add_parser("exec", help="execute a compiled binary")
    exe.add_argument("file")
    exe.add_argument("--step-limit", type=_positive_int, default=100_000)
    exe.set_defaults(handler=_cmd_exec)
    disasm = sub.add_parser("disasm", help="disassemble a compiled binary")
    disasm.add_argument("file")
    disasm.set_defaults(handler=_cmd_disasm)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI and return its exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    handler: Callable[[argparse.Namespace], str] = args.handler
    try:
        output = handler(args)
    except _UsageError as exc:
        print(f"microvm: error: {exc}", file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(f"microvm: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    # Output is only written once the whole command has succeeded.
    sys.stdout.write(output)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
