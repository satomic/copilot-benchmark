"""Command-line interface: ``python -m kvstore ROOT COMMAND [ARGS...]``."""

from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore", description="Append-only key-value store.")
    parser.add_argument("root", help="store directory")
    parser.add_argument(
        "--max-segment-bytes", type=_positive_int, default=4096, help="segment rollover size"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_set = sub.add_parser("set", help="store a key/value pair")
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_get = sub.add_parser("get", help="print the value of a key")
    p_get.add_argument("key")

    p_del = sub.add_parser("delete", help="delete a live key")
    p_del.add_argument("key")

    sub.add_parser("list", help="list live keys")
    sub.add_parser("compact", help="compact the store")
    sub.add_parser("stats", help="print store statistics")
    return parser


def _run(store: KVStore, args: argparse.Namespace) -> int:
    if args.command == "set":
        store.set(args.key, args.value)
        return 0
    if args.command == "get":
        value = store.get(args.key)
        if value is None:
            return 1
        sys.stdout.write(value + "\n")
        return 0
    if args.command == "delete":
        return 0 if store.delete(args.key) else 1
    if args.command == "list":
        for key in store.keys():
            sys.stdout.write(key + "\n")
        return 0
    if args.command == "compact":
        r = compact(store)
        sys.stdout.write(
            f"removed={r.segments_removed} written={r.records_written} "
            f"dropped={r.records_dropped} reclaimed={r.bytes_reclaimed}\n"
        )
        return 0
    if args.command == "stats":
        s = store.stats()
        sys.stdout.write(
            f"live_keys={s.live_keys} tombstones={s.tombstones} "
            f"total_records={s.total_records} dead_records={s.dead_records} "
            f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}\n"
        )
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run(store, args)
    except CorruptSegmentError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 3
    except (ValueError, TypeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
