from __future__ import annotations

import argparse
import sys

from microvm.compiler import compile_source
from microvm.disassembler import disassemble
from microvm.errors import MicroVMError
from microvm.serializer import dumps, loads
from microvm.vm import execute


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        return _dispatch(args)
    except _UsageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except MicroVMError as exc:
        print(str(exc), file=sys.stderr)
        return 3


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="microvm")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("file")
    run_p.add_argument("--optimize", action="store_true")
    run_p.add_argument("--step-limit", type=int, default=100_000)
    build_p = sub.add_parser("build")
    build_p.add_argument("file")
    build_p.add_argument("out")
    build_p.add_argument("--optimize", action="store_true")
    exec_p = sub.add_parser("exec")
    exec_p.add_argument("file")
    exec_p.add_argument("--step-limit", type=int, default=100_000)
    dis_p = sub.add_parser("disasm")
    dis_p.add_argument("file")
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command == "run":
        return _cmd_run(args)
    if command == "build":
        return _cmd_build(args)
    if command == "exec":
        return _cmd_exec(args)
    if command == "disasm":
        return _cmd_disasm(args)
    raise _UsageError("unknown command")


def _positive_step_limit(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise _UsageError("step-limit must be a positive integer")
    return value


def _cmd_run(args: argparse.Namespace) -> int:
    limit = _positive_step_limit(args.step_limit)
    src = _read_text(args.file)
    program = compile_source(src, optimize=bool(args.optimize))
    _print_output(execute(program, step_limit=limit))
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    src = _read_text(args.file)
    program = compile_source(src, optimize=bool(args.optimize))
    with open(args.out, "wb") as handle:
        handle.write(dumps(program))
    return 0


def _cmd_exec(args: argparse.Namespace) -> int:
    limit = _positive_step_limit(args.step_limit)
    program = loads(_read_bytes(args.file))
    _print_output(execute(program, step_limit=limit))
    return 0


def _cmd_disasm(args: argparse.Namespace) -> int:
    sys.stdout.write(disassemble(loads(_read_bytes(args.file))))
    return 0


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _print_output(lines: list[str]) -> None:
    for line in lines:
        print(line)


if __name__ == "__main__":
    sys.exit(main())
