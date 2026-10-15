from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from .compact import compact
from .errors import CorruptSegmentError
from .store import KVStore


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(2)


def _positive_int(raw: str) -> int:
    try:
        val = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int value: {raw!r}") from exc
    if val <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return val


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="kvstore")
    parser.add_argument(
        "--max-segment-bytes",
        type=_positive_int,
        default=4096,
        help="maximum segment size in bytes",
    )
    parser.add_argument("root", help="path to store directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_p = subparsers.add_parser("set")
    set_p.add_argument("key")
    set_p.add_argument("value")

    get_p = subparsers.add_parser("get")
    get_p.add_argument("key")

    del_p = subparsers.add_parser("delete")
    del_p.add_argument("key")

    subparsers.add_parser("list")
    subparsers.add_parser("compact")
    subparsers.add_parser("stats")
    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    front: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            rest.extend(argv[i:])
            break
        if arg == "--max-segment-bytes":
            if i + 1 < len(argv):
                front.extend([arg, argv[i + 1]])
                i += 2
            else:
                front.append(arg)
                i += 1
        elif arg.startswith("--max-segment-bytes="):
            front.append(arg)
            i += 1
        else:
            rest.append(arg)
            i += 1
    return front + rest


def _run_command(store: KVStore, ns: argparse.Namespace) -> int:
    cmd = ns.command
    if cmd == "set":
        store.set(ns.key, ns.value)
        return 0
    if cmd == "get":
        val = store.get(ns.key)
        if val is None:
            return 1
        sys.stdout.write(f"{val}\n")
        return 0
    if cmd == "delete":
        return 0 if store.delete(ns.key) else 1
    if cmd == "list":
        for key in store.keys():
            sys.stdout.write(f"{key}\n")
        return 0
    if cmd == "compact":
        res = compact(store)
        sys.stdout.write(
            f"removed={res.segments_removed} written={res.records_written} "
            f"dropped={res.records_dropped} reclaimed={res.bytes_reclaimed}\n"
        )
        return 0
    st = store.stats()
    sys.stdout.write(
        f"live_keys={st.live_keys} tombstones={st.tombstones} "
        f"total_records={st.total_records} dead_records={st.dead_records} "
        f"segment_count={st.segment_count} bytes_on_disk={st.bytes_on_disk}\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    try:
        ns = parser.parse_args(_normalize_argv(raw_args))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return code

    try:
        with KVStore(ns.root, max_segment_bytes=ns.max_segment_bytes) as store:
            return _run_command(store, ns)
    except CorruptSegmentError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 3
    except (ValueError, TypeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
