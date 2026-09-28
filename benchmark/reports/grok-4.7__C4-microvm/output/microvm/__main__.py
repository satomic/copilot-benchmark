import argparse
import sys

from microvm.compiler import compile_source
from microvm.disassembler import disassemble
from microvm.errors import MicroVMError
from microvm.serializer import dumps, loads
from microvm.vm import execute


class _UsageError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if type(code) is int else 2
    try:
        _run_command(args)
    except _UsageError as exc:
        print(exc, file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(exc, file=sys.stderr)
        return 3
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="microvm")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_run(sub)
    _add_build(sub)
    _add_exec(sub)
    _add_disasm(sub)
    return parser


def _add_run(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    cmd = sub.add_parser("run")
    cmd.add_argument("file")
    cmd.add_argument("--optimize", action="store_true")
    cmd.add_argument("--step-limit", type=_positive_int, default=100_000)


def _add_build(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    cmd = sub.add_parser("build")
    cmd.add_argument("file")
    cmd.add_argument("out")
    cmd.add_argument("--optimize", action="store_true")


def _add_exec(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    cmd = sub.add_parser("exec")
    cmd.add_argument("file")
    cmd.add_argument("--step-limit", type=_positive_int, default=100_000)


def _add_disasm(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    cmd = sub.add_parser("disasm")
    cmd.add_argument("file")


def _positive_int(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("step-limit must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("step-limit must be a positive integer")
    return value


def _run_command(args: argparse.Namespace) -> None:
    if args.command == "run":
        _cmd_run(args)
        return
    if args.command == "build":
        _cmd_build(args)
        return
    if args.command == "exec":
        _cmd_exec(args)
        return
    if args.command == "disasm":
        _cmd_disasm(args)
        return
    raise _UsageError(f"unknown command: {args.command}")


def _cmd_run(args: argparse.Namespace) -> None:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    _write_lines(execute(program, step_limit=args.step_limit))


def _cmd_build(args: argparse.Namespace) -> None:
    program = compile_source(_read_text(args.file), optimize=args.optimize)
    _write_bytes(args.out, dumps(program))


def _cmd_exec(args: argparse.Namespace) -> None:
    _write_lines(execute(loads(_read_bytes(args.file)), step_limit=args.step_limit))


def _cmd_disasm(args: argparse.Namespace) -> None:
    sys.stdout.write(disassemble(loads(_read_bytes(args.file))))


def _write_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise _UsageError(str(exc)) from exc


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _UsageError(str(exc)) from exc


def _write_bytes(path: str, payload: bytes) -> None:
    try:
        with open(path, "wb") as handle:
            handle.write(payload)
    except OSError as exc:
        raise _UsageError(str(exc)) from exc


if __name__ == "__main__":
    sys.exit(main())
