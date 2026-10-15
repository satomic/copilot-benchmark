"""Command-line interface: ``python -m kvstore ROOT COMMAND [ARGS...]``."""

from __future__ import annotations

import argparse
import sys

from .compact import compact
from .errors import CorruptSegmentError, KVStoreError
from .store import KVStore, Stats

EXIT_OK = 0
EXIT_MISSING = 1
EXIT_USAGE = 2
EXIT_CORRUPT = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvstore", description="Append-only key-value store.")
    parser.add_argument("root", help="store directory")
    parser.add_argument(
        "--max-segment-bytes", type=int, default=4096, metavar="N",
        help="segment rollover threshold in bytes (default 4096)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set", help="store KEY VALUE")
    p_set.add_argument("key")
    p_set.add_argument("value")
    for name in ("get", "delete"):
        sub.add_parser(name, help=f"{name} a key").add_argument("key")
    sub.add_parser("list", help="list live keys")
    sub.add_parser("compact", help="rewrite the store into one segment")
    sub.add_parser("stats", help="report store statistics")
    return parser


def _format_stats(stats: Stats) -> str:
    return (
        f"live_keys={stats.live_keys} tombstones={stats.tombstones} "
        f"total_records={stats.total_records} dead_records={stats.dead_records} "
        f"segment_count={stats.segment_count} bytes_on_disk={stats.bytes_on_disk}"
    )


def _run(store: KVStore, args: argparse.Namespace) -> int:
    cmd = args.command
    if cmd == "set":
        store.set(args.key, args.value)
    elif cmd == "get":
        value = store.get(args.key)
        if value is None:
            return EXIT_MISSING
        sys.stdout.write(value + "\n")
    elif cmd == "delete":
        return EXIT_OK if store.delete(args.key) else EXIT_MISSING
    elif cmd == "list":
        for key in store.keys():
            sys.stdout.write(key + "\n")
    elif cmd == "compact":
        r = compact(store)
        sys.stdout.write(
            f"removed={r.segments_removed} written={r.records_written} "
            f"dropped={r.records_dropped} reclaimed={r.bytes_reclaimed}\n"
        )
    elif cmd == "stats":
        sys.stdout.write(_format_stats(store.stats()) + "\n")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_OK
    try:
        with KVStore(args.root, max_segment_bytes=args.max_segment_bytes) as store:
            return _run(store, args)
    except (CorruptSegmentError, KVStoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CORRUPT
    except (ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
