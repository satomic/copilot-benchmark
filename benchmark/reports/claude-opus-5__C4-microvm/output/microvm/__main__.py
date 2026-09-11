"""Command line interface: ``python -m microvm COMMAND ...``."""

from __future__ import annotations

import argparse
import sys

from .compiler import compile_source
from .disassembler import disassemble
from .errors import MicroVMError
from .serializer import dumps, loads
from .vm import execute

DEFAULT_STEP_LIMIT: int = 100_000


class _UsageError(Exception):
    """Raised for problems that must map to exit code 2."""


def _read_text(path: str) -> str:
    """Read a source file, honouring a UTF-8/UTF-16 byte order mark if present."""
    raw = _read_bytes(path)
    try:
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return raw.decode("utf-16")
        return raw.decode("utf-8-sig")
    except (UnicodeDecodeError, UnicodeError) as exc:
        raise _UsageError(f"cannot decode {path}: {exc}") from exc


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from exc


def _step_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _UsageError("--step-limit must be a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with one subcommand per operation."""
    parser = argparse.ArgumentParser(prog="microvm", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="compile and execute a source file")
    run.add_argument("file")
    run.add_argument("--optimize", action="store_true")
    run.add_argument("--step-limit", type=int, default=DEFAULT_STEP_LIMIT)

    build = subparsers.add_parser("build", help="compile a source file to bytecode")
    build.add_argument("file")
    build.add_argument("out")
    build.add_argument("--optimize", action="store_true")

    execute_cmd = subparsers.add_parser("exec", help="execute a bytecode file")
    execute_cmd.add_argument("file")
    execute_cmd.add_argument("--step-limit", type=int, default=DEFAULT_STEP_LIMIT)

    disasm = subparsers.add_parser("disasm", help="disassemble a bytecode file")
    disasm.add_argument("file")
    return parser


def _cmd_run(args: argparse.Namespace) -> list[str]:
    source = _read_text(args.file)
    limit = _step_limit(args.step_limit)
    program = compile_source(source, optimize=args.optimize)
    return execute(program, step_limit=limit)


def _cmd_build(args: argparse.Namespace) -> list[str]:
    source = _read_text(args.file)
    data = dumps(compile_source(source, optimize=args.optimize))
    try:
        with open(args.out, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        raise _UsageError(f"cannot write {args.out}: {exc}") from exc
    return []


def _cmd_exec(args: argparse.Namespace) -> list[str]:
    data = _read_bytes(args.file)
    limit = _step_limit(args.step_limit)
    return execute(loads(data), step_limit=limit)


def _cmd_disasm(args: argparse.Namespace) -> list[str]:
    listing = disassemble(loads(_read_bytes(args.file)))
    return listing.splitlines()


_COMMANDS = {
    "run": _cmd_run,
    "build": _cmd_build,
    "exec": _cmd_exec,
    "disasm": _cmd_disasm,
}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 2
    handler = _COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse rejects this first
        print(f"unknown command {args.command!r}", file=sys.stderr)
        return 2
    try:
        lines = handler(args)
    except _UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    # Output is buffered until success so failures write nothing to stdout.
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
