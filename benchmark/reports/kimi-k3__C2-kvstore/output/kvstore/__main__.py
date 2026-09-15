"""Command line interface: ``python -m kvstore ROOT COMMAND [ARGS...]``."""

from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


def _positive_int(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument(
        "--max-segment-bytes", type=_positive_int, default=4096, metavar="N"
    )
    parser.add_argument("root", help="store directory")
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_get = sub.add_parser("get")
    p_get.add_argument("key")
    p_del = sub.add_parser("delete")
    p_del.add_argument("key")
    sub.add_parser("list")
    sub.add_parser("compact")
    sub.add_parser("stats")
    return parser


def _run(args: argparse.Namespace, store: KVStore) -> int:
    if args.command == "set":
        store.set(args.key, args.value)
        return 0
    if args.command == "get":
        value = store.get(args.key)
        if value is None:
            return 1
        print(value)
        return 0
    if args.command == "delete":
        return 0 if store.delete(args.key) else 1
    if args.command == "list":
        for key in store.keys():
            print(key)
        return 0
    if args.command == "compact":
        r = compact(store)
        print(
            f"removed={r.segments_removed} written={r.records_written} "
            f"dropped={r.records_dropped} reclaimed={r.bytes_reclaimed}"
        )
        return 0
    s = store.stats()
    print(
        f"live_keys={s.live_keys} tombstones={s.tombstones} "
        f"total_records={s.total_records} dead_records={s.dead_records} "
        f"segment_count={s.segment_count} bytes_on_disk={s.bytes_on_disk}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run(args, store)
    except CorruptSegmentError as exc:
        print(exc, file=sys.stderr)
        return 3
    except (ValueError, TypeError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
