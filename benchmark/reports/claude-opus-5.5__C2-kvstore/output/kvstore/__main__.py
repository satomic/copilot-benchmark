"""Command-line interface: ``python -m kvstore ROOT COMMAND [ARGS...]``."""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _positive_int(text: str) -> int:
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if number <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {text!r}")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kvstore")
    parser.add_argument("--max-segment-bytes", type=_positive_int, default=4096)
    parser.add_argument("root")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    specs = {"set": ["key", "value"], "get": ["key"], "delete": ["key"],
             "list": [], "compact": [], "stats": []}
    for name, params in specs.items():
        cmd = sub.add_parser(name)
        # Also accept the global flag after the command; SUPPRESS keeps the default.
        cmd.add_argument("--max-segment-bytes", type=_positive_int, default=argparse.SUPPRESS)
        for param in params:
            cmd.add_argument(param)
    return parser


def _cmd_set(store: KVStore, args: argparse.Namespace) -> tuple[int, str]:
    store.set(args.key, args.value)
    return 0, ""


def _cmd_get(store: KVStore, args: argparse.Namespace) -> tuple[int, str]:
    value = store.get(args.key)
    return (1, "") if value is None else (0, value + "\n")


def _cmd_delete(store: KVStore, args: argparse.Namespace) -> tuple[int, str]:
    return (0, "") if store.delete(args.key) else (1, "")


def _cmd_list(store: KVStore, args: argparse.Namespace) -> tuple[int, str]:
    return 0, "".join(key + "\n" for key in store.keys())


def _cmd_compact(store: KVStore, args: argparse.Namespace) -> tuple[int, str]:
    r = compact(store)
    return 0, (
        f"removed={r.segments_removed} written={r.records_written} "
        f"dropped={r.records_dropped} reclaimed={r.bytes_reclaimed}\n"
    )


def _cmd_stats(store: KVStore, args: argparse.Namespace) -> tuple[int, str]:
    s = store.stats()
    return 0, (
        f"live_keys={s.live_keys} tombstones={s.tombstones} "
        f"total_records={s.total_records} dead_records={s.dead_records} "
        f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}\n"
    )


_HANDLERS: dict[str, Callable[[KVStore, argparse.Namespace], tuple[int, str]]] = {
    "set": _cmd_set,
    "get": _cmd_get,
    "delete": _cmd_delete,
    "list": _cmd_list,
    "compact": _cmd_compact,
    "stats": _cmd_stats,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            code, output = _HANDLERS[args.command](store, args)
    except CorruptSegmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Output is buffered until success so failures never write to stdout.
    sys.stdout.write(output)
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
