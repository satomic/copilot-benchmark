"""Command line interface: python -m kvstore ROOT COMMAND [ARGS...]."""
from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"not a positive integer: {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("--max-segment-bytes", type=_positive_int, default=4096)
    parser.add_argument("root")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, nargs in (("set", 2), ("get", 1), ("delete", 1), ("list", 0),
                        ("compact", 0), ("stats", 0)):
        p = sub.add_parser(name)
        if nargs >= 1:
            p.add_argument("key")
        if nargs == 2:
            p.add_argument("value")
    return parser


def _run(store: KVStore, args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd == "set":
        store.set(args.key, args.value)
    elif cmd == "get":
        value = store.get(args.key)
        if value is None:
            return 1
        sys.stdout.write(value + "\n")
    elif cmd == "delete":
        return 0 if store.delete(args.key) else 1
    elif cmd == "list":
        for key in store.keys():
            sys.stdout.write(key + "\n")
    elif cmd == "compact":
        r = compact(store)
        sys.stdout.write(f"removed={r.segments_removed} written={r.records_written} "
                         f"dropped={r.records_dropped} reclaimed={r.bytes_reclaimed}\n")
    else:
        s = store.stats()
        sys.stdout.write(" ".join(f"{k}={v}" for k, v in s._asdict().items()) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run(store, args)
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except CorruptSegmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
