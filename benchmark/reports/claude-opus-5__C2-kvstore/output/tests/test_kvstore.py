"""Test suite for the kvstore package."""

from __future__ import annotations

import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

from kvstore import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    Location,
    Segment,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# record codec
# --------------------------------------------------------------------------


def test_encode_header_layout() -> None:
    blob = encode_record("ab", "xyz")
    magic, flags, key_len, value_len, crc = struct.unpack_from("!4sBHII", blob, 0)
    assert magic == b"KVR1"
    assert (flags, key_len, value_len) == (0x00, 2, 3)
    assert crc == zlib.crc32(b"abxyz")
    assert len(blob) == 15 + 2 + 3


def test_round_trip_value() -> None:
    blob = encode_record("key", "value")
    assert decode_record(blob) == ("key", "value", len(blob))


def test_round_trip_unicode() -> None:
    blob = encode_record("ключ", "日本語")
    key, value, size = decode_record(blob)
    assert (key, value, size) == ("ключ", "日本語", len(blob))


def test_tombstone_encoding() -> None:
    blob = encode_record("k", None)
    assert len(blob) == 16
    assert blob[4] == 0x01
    assert decode_record(blob) == ("k", None, 16)


def test_tombstone_versus_empty_value() -> None:
    tomb = encode_record("k", None)
    empty = encode_record("k", "")
    assert len(tomb) == len(empty) == 16
    assert tomb != empty
    assert decode_record(tomb)[1] is None
    assert decode_record(empty)[1] == ""


def test_decode_with_offset() -> None:
    first = encode_record("a", "1")
    second = encode_record("bb", "22")
    buf = first + second
    assert decode_record(buf, len(first)) == ("bb", "22", len(second))


def test_decode_short_header_is_incomplete() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("a", "1")[:10])


def test_decode_short_body_is_incomplete() -> None:
    blob = encode_record("abc", "defgh")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:-1])


def test_decode_bad_magic() -> None:
    blob = bytearray(encode_record("a", "1"))
    blob[0:4] = b"XXXX"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_unknown_flags() -> None:
    blob = bytearray(encode_record("a", "1"))
    blob[4] = 0x07
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_zero_key_len() -> None:
    blob = struct.pack("!4sBHII", b"KVR1", 0, 0, 0, zlib.crc32(b""))
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_decode_tombstone_with_value_len() -> None:
    body = b"kv"
    blob = struct.pack("!4sBHII", b"KVR1", 1, 1, 1, zlib.crc32(body)) + body
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_decode_crc_mismatch() -> None:
    blob = bytearray(encode_record("a", "1"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_invalid_utf8() -> None:
    body = b"\xff\xfe"
    blob = struct.pack("!4sBHII", b"KVR1", 0, 1, 1, zlib.crc32(body)) + body
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_structural_error_beats_crc() -> None:
    blob = bytearray(encode_record("a", "1"))
    blob[0] = 0x00
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError, match="magic"):
        decode_record(bytes(blob))


def test_encode_rejects_bad_types_and_lengths() -> None:
    with pytest.raises(TypeError):
        encode_record(b"a", "1")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        encode_record("", "1")
    with pytest.raises(ValueError):
        encode_record("x" * 70000, "1")


# --------------------------------------------------------------------------
# segments
# --------------------------------------------------------------------------


def test_segment_append_and_scan(tmp_path: pathlib.Path) -> None:
    seg = Segment(tmp_path / "000001.seg", 1)
    a = seg.append(encode_record("a", "1"))
    b = seg.append(encode_record("b", None))
    assert (a, b) == (0, 17)
    assert list(seg.scan()) == [("a", "1", 0), ("b", None, 17)]
    assert seg.size == 33
    seg.close()


def test_segment_scan_stops_at_truncated_tail(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1") + encode_record("b", "22")[:-1])
    assert list(Segment(path, 1).scan()) == [("a", "1", 0)]


def test_segment_scan_stops_at_partial_header(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    path.write_bytes(encode_record("a", "1") + b"KVR")
    assert list(Segment(path, 1).scan()) == [("a", "1", 0)]


def test_segment_scan_raises_on_crc_mismatch_at_tail(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    good = encode_record("a", "1")
    bad = bytearray(encode_record("b", "22"))
    bad[-1] ^= 0xFF
    path.write_bytes(good + bytes(bad))
    with pytest.raises(CorruptSegmentError) as info:
        list(Segment(path, 1).scan())
    assert info.value.offset == len(good)
    assert info.value.path == path
    assert "000001.seg" in str(info.value)
    assert str(len(good)) in str(info.value)


def test_segment_empty_file_scans_to_nothing(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "000001.seg"
    seg = Segment(path, 1)
    assert list(seg.scan()) == []
    assert seg.size == 0
    seg.close()


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------


def test_index_put_get_and_len() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 10), tombstone=False)
    assert idx.get("a") == Location(1, 0)
    assert idx.get("zz") is None
    assert len(idx) == 2


def test_index_tombstones() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("a", Location(1, 20), tombstone=True)
    assert idx.get("a") is None
    assert idx.tombstone_count() == 1
    assert len(idx) == 0
    idx.put("a", Location(2, 0), tombstone=False)
    assert idx.tombstone_count() == 0
    assert idx.live_keys() == ["a"]


def test_index_live_keys_ordering() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 30), tombstone=False)
    idx.put("c", Location(2, 5), tombstone=False)
    assert idx.live_keys() == ["a", "b", "c"]
    idx.put("a", Location(2, 90), tombstone=False)
    assert idx.live_keys() == ["b", "c", "a"]


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------


def test_store_set_get(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.get("a") == "1"
        assert store.get("missing") is None


def test_store_empty_value_is_not_none(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "")
        assert store.get("a") == ""
        store.delete("a")
        assert store.get("a") is None


def test_store_persists_across_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("a")
    with KVStore(tmp_path) as store:
        assert store.get("a") is None
        assert store.get("b") == "2"
        assert store.keys() == ["b"]


def test_store_delete_noop_writes_nothing(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.delete("a") is True
        size = store.stats().bytes_on_disk
        assert store.delete("a") is False
        assert store.delete("never") is False
        assert store.stats().bytes_on_disk == size


def test_store_recovers_from_truncated_tail(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
    path = tmp_path / "000001.seg"
    data = path.read_bytes()
    path.write_bytes(data + encode_record("c", "333")[:-2])
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b"]
        assert store.get("c") is None
        assert store.stats().bytes_on_disk == len(data) + len(encode_record("c", "333")) - 2


def test_write_after_truncated_tail_recovery(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    path = tmp_path / "000001.seg"
    good = path.read_bytes()
    path.write_bytes(good + encode_record("c", "333")[:-2])
    with KVStore(tmp_path) as store:
        assert store.stats().bytes_on_disk == len(good) + 17
        store.set("d", "4")
        assert path.stat().st_size == len(good) + len(encode_record("d", "4"))
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "d"]
        assert store.get("d") == "4"
        assert store.get("c") is None


def test_store_reports_corruption_on_open(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    path = tmp_path / "000001.seg"
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_store_ignores_non_segment_files(tmp_path: pathlib.Path) -> None:
    (tmp_path / "000003.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notes.txt").write_bytes(b"hello")
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        stats = store.stats()
        assert stats.segment_count == 1
        assert stats.bytes_on_disk == len(encode_record("a", "1"))


def test_store_rollover(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        store.set("a", "1")  # 17 bytes
        store.set("b", "2")  # 34 bytes
        assert store.stats().segment_count == 1
        store.set("c", "3")  # would be 51 > 40 -> rollover
        assert store.stats().segment_count == 2
    assert (tmp_path / "000002.seg").exists()


def test_store_rollover_boundary_is_strict(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 1
        assert (tmp_path / "000001.seg").stat().st_size == 34


def test_store_oversized_record_fits_empty_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("k", "v" * 500)
        assert store.get("k") == "v" * 500
        store.set("k2", "w")
        assert store.stats().segment_count == 2


def test_store_keys_order_and_rewrite_moves_to_end(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        for key in ("a", "b", "c"):
            store.set(key, key)
        assert store.keys() == ["a", "b", "c"]
        store.set("a", "again")
        assert store.keys() == ["b", "c", "a"]


def test_store_stats_fields(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "3")
        store.delete("b")
        stats = store.stats()
        assert (stats.live_keys, stats.tombstones, stats.total_records) == (1, 1, 4)
        assert stats.dead_records == 2
        assert stats.segment_count == 1
        assert stats.bytes_on_disk == (tmp_path / "000001.seg").stat().st_size


def test_store_type_validation(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"a", "1")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set("a", 1)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.get(42)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.delete(None)  # type: ignore[arg-type]


def test_store_key_length_validation_counts_bytes(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("", "1")
        with pytest.raises(ValueError):
            store.set("漢" * 40000, "1")
        assert store.stats().total_records == 0


def test_store_max_segment_bytes_validation(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes="4096")  # type: ignore[arg-type]


def test_store_close_is_idempotent_and_guards(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(ValueError):
        store.set("a", "2")
    with pytest.raises(ValueError):
        store.keys()


def test_store_creates_missing_root(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "deep" / "nested"
    with KVStore(root) as store:
        store.set("a", "1")
    assert (root / "000001.seg").exists()


# --------------------------------------------------------------------------
# compaction
# --------------------------------------------------------------------------


def test_compact_basic(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        store.delete("b")
        before = store.stats()
        result = compact(store)
        assert result.records_written == 1
        assert result.records_dropped == before.total_records - 1
        assert result.segments_removed == before.segment_count
        assert result.bytes_reclaimed == before.bytes_on_disk - store.stats().bytes_on_disk
        assert store.keys() == ["a"]
        assert store.get("a") == "3"
        assert store.get("b") is None
        assert store.stats().tombstones == 0


def test_compact_preserves_keys_order(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=64) as store:
        for key in ("a", "b", "c", "d"):
            store.set(key, key * 3)
        store.set("b", "new")
        order = store.keys()
        compact(store)
        assert store.keys() == order


def test_compact_creates_new_segment_id_and_removes_old(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=20) as store:
        store.set("a", "1")
        store.set("b", "2")
        assert store.stats().segment_count == 2
        compact(store)
    assert sorted(p.name for p in tmp_path.glob("*.seg")) == ["000003.seg"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_compact_empty_store_creates_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        result = compact(store)
        assert result.records_written == 0
        assert store.keys() == []
        assert store.stats().segment_count == 1
    assert (tmp_path / "000002.seg").exists()
    assert (tmp_path / "000002.seg").stat().st_size == 0


def test_writes_after_compaction_append_and_roll(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=34) as store:
        store.set("a", "1")
        compact(store)
        store.set("b", "2")
        assert store.stats().segment_count == 1
        store.set("c", "3")
        assert store.stats().segment_count == 2
        assert store.keys() == ["a", "b", "c"]
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "b", "c"]


def test_compaction_survives_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=24) as store:
        for i in range(10):
            store.set(f"k{i}", str(i))
        for i in range(0, 10, 2):
            store.delete(f"k{i}")
        compact(store)
    with KVStore(tmp_path) as store:
        assert store.keys() == ["k1", "k3", "k5", "k7", "k9"]
        assert store.get("k3") == "3"
        assert store.stats().total_records == 5


def test_leftover_tmp_file_does_not_break_recovery(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    (tmp_path / "000002.seg.tmp").write_bytes(encode_record("a", "compacted"))
    with KVStore(tmp_path) as store:
        assert store.get("a") == "1"
        assert store.stats().segment_count == 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_round_trip(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
    root = str(tmp_path)
    assert main([root, "set", "a", "1"]) == 0
    assert capsys.readouterr().out == ""
    assert main([root, "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([root, "get", "zz"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_delete_exit_codes(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    assert main([root, "delete", "a"]) == 0
    assert main([root, "delete", "a"]) == 1
    assert main([root, "delete", "nope"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_list_and_stats(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    main([root, "set", "b", "2"])
    capsys.readouterr()
    assert main([root, "list"]) == 0
    assert capsys.readouterr().out == "a\nb\n"
    assert main([root, "stats"]) == 0
    line = capsys.readouterr().out
    assert line.endswith("\n") and line.count("\n") == 1
    fields = [part.split("=")[0] for part in line.strip().split(" ")]
    assert fields == [
        "live_keys",
        "tombstones",
        "total_records",
        "dead_records",
        "segment_count",
        "bytes_on_disk",
    ]


def test_cli_compact_output(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    main([root, "set", "a", "2"])
    capsys.readouterr()
    assert main([root, "compact"]) == 0
    out = capsys.readouterr().out
    assert out == "removed=1 written=1 dropped=1 reclaimed=17\n"


def test_cli_usage_errors(tmp_path: pathlib.Path) -> None:
    assert main([str(tmp_path), "frobnicate"]) == 2
    assert main([str(tmp_path), "set", "onlykey"]) == 2
    assert main([str(tmp_path), "get", "a", "extra"]) == 2
    assert main([str(tmp_path), "--max-segment-bytes", "0", "list"]) == 2
    assert main([str(tmp_path), "--max-segment-bytes", "abc", "list"]) == 2


def test_cli_value_error_exit_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    assert main([str(tmp_path), "set", "", "1"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_cli_corrupt_segment_exit_3(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    main([str(tmp_path), "set", "a", "1"])
    path = tmp_path / "000001.seg"
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    capsys.readouterr()
    assert main([str(tmp_path), "get", "a"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "000001.seg" in captured.err


def test_cli_max_segment_bytes_flag(tmp_path: pathlib.Path) -> None:
    root = str(tmp_path)
    assert main([root, "--max-segment-bytes", "20", "set", "a", "1"]) == 0
    assert main([root, "--max-segment-bytes", "20", "set", "b", "2"]) == 0
    assert (tmp_path / "000002.seg").exists()


def test_cli_module_entry_point(tmp_path: pathlib.Path) -> None:
    root = str(tmp_path)
    assert subprocess.run(
        [sys.executable, "-m", "kvstore", root, "set", "a", "1"], cwd=ROOT
    ).returncode == 0
    done = subprocess.run(
        [sys.executable, "-m", "kvstore", root, "get", "a"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    assert done.stdout == "1\n"
    missing = subprocess.run(
        [sys.executable, "-m", "kvstore", root, "get", "zz"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 1
    assert missing.stdout == ""
