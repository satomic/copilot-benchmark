"""Command-line interface: python -m kvstore ROOT COMMAND [ARGS...]."""

from __future__ import annotations

import argparse
import sys

from kvstore.compact import compact
from kvstore.errors import CorruptSegmentError
from kvstore.store import KVStore, Stats


class _UsageError(Exception):
    """argparse reported a usage problem on stderr."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise _UsageError(message)


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command and return its exit code."""
    try:
        args = _build_parser().parse_args(argv)
    except _UsageError:
        return 2
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        store = KVStore(args.root, max_segment_bytes=args.max_segment_bytes)
    except CorruptSegmentError as exc:
        return _fail(exc, 3)
    except (TypeError, ValueError) as exc:
        return _fail(exc, 2)
    try:
        return _dispatch(store, args)
    except CorruptSegmentError as exc:
        return _fail(exc, 3)
    except (TypeError, ValueError) as exc:
        return _fail(exc, 2)
    finally:
        store.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="kvstore")
    parser.add_argument("root")
    parser.add_argument("--max-segment-bytes", type=_positive_int, default=4096)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    get_cmd = sub.add_parser("get")
    get_cmd.add_argument("key")
    delete_cmd = sub.add_parser("delete")
    delete_cmd.add_argument("key")
    sub.add_parser("list")
    sub.add_parser("compact")
    sub.add_parser("stats")
    return parser


def _positive_int(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("not a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("not a positive integer")
    return value


def _dispatch(store: KVStore, args: argparse.Namespace) -> int:
    command = args.command
    if command == "set":
        store.set(args.key, args.value)
        return 0
    if command == "get":
        return _cmd_get(store, args.key)
    if command == "delete":
        return 0 if store.delete(args.key) else 1
    if command == "list":
        return _cmd_list(store)
    if command == "compact":
        return _cmd_compact(store)
    if command == "stats":
        return _cmd_stats(store)
    return _fail(f"unknown command: {command}", 2)


def _cmd_get(store: KVStore, key: str) -> int:
    value = store.get(key)
    if value is None:
        return 1
    _write_stdout(value + "\n")
    return 0


def _cmd_list(store: KVStore) -> int:
    for key in store.keys():
        _write_stdout(key + "\n")
    return 0


def _cmd_compact(store: KVStore) -> int:
    result = compact(store)
    _write_stdout(
        f"removed={result.segments_removed} written={result.records_written} "
        f"dropped={result.records_dropped} reclaimed={result.bytes_reclaimed}\n"
    )
    return 0


def _cmd_stats(store: KVStore) -> int:
    _write_stdout(_format_stats(store.stats()))
    return 0


def _write_stdout(text: str) -> None:
    """Write exact UTF-8 bytes so Windows text mode does not turn LF into CRLF."""
    data = text.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    buffer.write(data)
    buffer.flush()


def _format_stats(stats: Stats) -> str:
    return (
        f"live_keys={stats.live_keys} tombstones={stats.tombstones} "
        f"total_records={stats.total_records} dead_records={stats.dead_records} "
        f"segment_count={stats.segment_count} bytes_on_disk={stats.bytes_on_disk}\n"
    )


def _fail(exc: object, code: int) -> int:
    print(exc, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
