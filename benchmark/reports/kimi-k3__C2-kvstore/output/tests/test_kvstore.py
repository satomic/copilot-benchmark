"""Test suite for the kvstore package."""

from __future__ import annotations

import dataclasses
import os
import pathlib
import subprocess
import sys
import zlib

import pytest

import kvstore
from kvstore import (
    CompactionResult,
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    KVStoreError,
    Location,
    RecordError,
    Segment,
    Stats,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main as cli_main

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# record codec
# ---------------------------------------------------------------------------


def test_record_roundtrip() -> None:
    blob = encode_record("hello", "world")
    key, value, size = decode_record(blob)
    assert (key, value, size) == ("hello", "world", len(blob))


def test_record_header_layout() -> None:
    blob = encode_record("ab", "cde")
    assert blob[:4] == b"KVR1"
    assert blob[4] == 0x00
    assert int.from_bytes(blob[5:7], "big") == 2
    assert int.from_bytes(blob[7:11], "big") == 3
    assert int.from_bytes(blob[11:15], "big") == zlib.crc32(b"abcde")
    assert blob[15:] == b"abcde"
    assert len(blob) == 15 + 2 + 3


def test_record_decode_with_offset() -> None:
    blob = b"XXXX" + encode_record("k", "v")
    assert decode_record(blob, 4) == ("k", "v", 17)


def test_record_tombstone_roundtrip() -> None:
    blob = encode_record("k", None)
    assert blob[4] == 0x01
    assert len(blob) == 16
    assert decode_record(blob) == ("k", None, 16)


def test_record_empty_value_distinct_from_tombstone() -> None:
    empty = encode_record("k", "")
    tomb = encode_record("k", None)
    assert len(empty) == len(tomb) == 16
    assert empty != tomb
    assert decode_record(empty)[1] == ""
    assert decode_record(tomb)[1] is None


def test_record_unicode_roundtrip() -> None:
    key, value, _ = decode_record(encode_record("héllo", "值"))
    assert (key, value) == ("héllo", "值")


def test_decode_incomplete_header() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("k", "v")[:10])


def test_decode_incomplete_payload() -> None:
    blob = encode_record("key", "value")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:-2])


def test_decode_bad_magic() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[0] = ord("X")
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_bad_flags() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[4] = 0x7F
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_zero_key_len() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[5:7] = (0).to_bytes(2, "big")
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_tombstone_with_value_len() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[4] = 0x01  # tombstone but value_len == 1
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_crc_mismatch() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_invalid_utf8() -> None:
    key_bytes = b"\xff"
    crc = zlib.crc32(key_bytes)
    blob = (
        b"KVR1"
        + bytes([0x00])
        + (1).to_bytes(2, "big")
        + (0).to_bytes(4, "big")
        + crc.to_bytes(4, "big")
        + key_bytes
    )
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


# ---------------------------------------------------------------------------
# segment
# ---------------------------------------------------------------------------


def _segment(tmp_path: pathlib.Path, seg_id: int = 1) -> Segment:
    return Segment(tmp_path / f"{seg_id:06d}.seg", seg_id)


def test_segment_append_offsets_and_size(tmp_path: pathlib.Path) -> None:
    seg = _segment(tmp_path)
    b1 = encode_record("a", "1")
    b2 = encode_record("bb", "22")
    assert seg.append(b1) == 0
    assert seg.append(b2) == len(b1)
    assert seg.size == len(b1) + len(b2)
    seg.close()


def test_segment_scan_order(tmp_path: pathlib.Path) -> None:
    seg = _segment(tmp_path)
    seg.append(encode_record("a", "1"))
    seg.append(encode_record("b", None))
    seg.close()
    assert list(seg.scan()) == [("a", "1", 0), ("b", None, 17)]


def test_segment_scan_after_reopen(tmp_path: pathlib.Path) -> None:
    seg = _segment(tmp_path)
    seg.append(encode_record("a", "1"))
    seg.close()
    seg2 = _segment(tmp_path)
    assert list(seg2.scan()) == [("a", "1", 0)]
    seg2.close()


def test_segment_truncated_header_tail_stops_cleanly(tmp_path: pathlib.Path) -> None:
    seg = _segment(tmp_path)
    seg.append(encode_record("a", "1"))
    seg.append(encode_record("bb", "22")[:9])  # partial header
    seg.close()
    assert list(seg.scan()) == [("a", "1", 0)]


def test_segment_truncated_payload_tail_stops_cleanly(tmp_path: pathlib.Path) -> None:
    seg = _segment(tmp_path)
    seg.append(encode_record("a", "1"))
    seg.append(encode_record("key", "longvalue")[:-3])  # header ok, payload short
    seg.close()
    assert [key for key, _, _ in seg.scan()] == ["a"]


def test_segment_corruption_raises_with_path_and_offset(
    tmp_path: pathlib.Path,
) -> None:
    seg = _segment(tmp_path)
    seg.append(encode_record("a", "1"))
    bad = bytearray(encode_record("b", "2"))
    bad[0] = 0  # bad magic
    seg.append(bytes(bad))
    seg.close()
    with pytest.raises(CorruptSegmentError) as excinfo:
        list(seg.scan())
    err = excinfo.value
    assert err.offset == 17
    assert err.path == tmp_path / "000001.seg"
    assert "000001.seg" in str(err)
    assert "17" in str(err)


def test_segment_crc_mismatch_at_end_is_corruption_not_truncation(
    tmp_path: pathlib.Path,
) -> None:
    seg = _segment(tmp_path)
    bad = bytearray(encode_record("a", "1"))
    bad[-1] ^= 1  # all bytes present, crc wrong
    seg.append(bytes(bad))
    seg.close()
    with pytest.raises(CorruptSegmentError):
        list(seg.scan())


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------


def test_index_put_get() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    assert idx.get("a") == Location(1, 0)
    assert idx.get("zz") is None


def test_index_tombstone_hides_key() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("a", Location(1, 17), tombstone=True)
    assert idx.get("a") is None
    assert idx.tombstone_count() == 1
    assert len(idx) == 0
    assert idx.live_keys() == []


def test_index_rewrite_moves_key_to_end() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 10), tombstone=False)
    assert idx.live_keys() == ["a", "b"]
    idx.put("a", Location(1, 20), tombstone=False)
    assert idx.live_keys() == ["b", "a"]


def test_index_order_across_segments() -> None:
    idx = Index()
    idx.put("x", Location(2, 0), tombstone=False)
    idx.put("y", Location(1, 50), tombstone=False)
    assert idx.live_keys() == ["y", "x"]


def test_index_revive_after_tombstone() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=True)
    idx.put("a", Location(1, 5), tombstone=False)
    assert idx.get("a") == Location(1, 5)
    assert idx.tombstone_count() == 0
    assert len(idx) == 1


def test_location_is_frozen_dataclass() -> None:
    loc = Location(3, 42)
    assert (loc.seg_id, loc.offset) == (3, 42)
    with pytest.raises(dataclasses.FrozenInstanceError):
        loc.seg_id = 9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


def test_store_set_get(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        store.set("a", "1")
        assert store.get("a") == "1"


def test_store_persists_across_reopen(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.delete("a")
    with KVStore(root) as store:
        assert store.get("a") is None
        assert store.get("b") == "2"
        assert store.keys() == ["b"]


def test_store_get_missing_returns_none(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        assert store.get("nope") is None


def test_store_empty_string_value(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("e", "")
        assert store.get("e") == ""
    with KVStore(root) as store:
        value = store.get("e")
        assert value == ""
        assert value is not None


def test_store_delete_returns_true_only_when_live(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        store.set("a", "1")
        assert store.delete("a") is True
        assert store.delete("a") is False
        assert store.delete("never") is False


def test_store_noop_delete_writes_nothing(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
    size_before = (root / "000001.seg").stat().st_size
    with KVStore(root) as store:
        assert store.delete("ghost") is False
    assert (root / "000001.seg").stat().st_size == size_before


def test_store_keys_order(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("c", "3")
        assert store.keys() == ["a", "b", "c"]
        store.set("a", "9")  # re-writing moves the key to the end
        assert store.keys() == ["b", "c", "a"]
        store.delete("b")
        assert store.keys() == ["c", "a"]


def test_store_rollover(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root, max_segment_bytes=40) as store:
        for i in range(6):  # each record is 27 bytes -> one per segment
            store.set(f"k{i}", "v" * 10)
    assert len(list(root.glob("*.seg"))) == 6
    with KVStore(root, max_segment_bytes=40) as store:
        for i in range(6):
            assert store.get(f"k{i}") == "v" * 10


def test_store_record_larger_than_max_still_stored(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root, max_segment_bytes=16) as store:
        store.set("big", "x" * 100)  # 118-byte record in an empty segment
        store.set("small", "y")
        assert store.get("big") == "x" * 100
        assert store.get("small") == "y"
    with KVStore(root, max_segment_bytes=16) as store:
        assert store.get("big") == "x" * 100


def test_store_exact_fit_no_rollover(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d", max_segment_bytes=34) as store:
        store.set("a", "1")  # 17 bytes
        store.set("b", "2")  # exactly 34 -> still fits
        assert store.stats().segment_count == 1
        store.set("c", "3")  # 51 > 34 -> rollover
        assert store.stats().segment_count == 2


def test_store_segment_file_naming(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root, max_segment_bytes=17) as store:
        store.set("a", "1")
        store.set("b", "2")
    assert (root / "000001.seg").exists()
    assert (root / "000002.seg").exists()


def test_store_type_validation(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        with pytest.raises(TypeError):
            store.set(b"bytes", "v")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set(123, "v")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set("k", b"v")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set("k", None)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.get(b"k")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.delete(5)  # type: ignore[arg-type]


def test_store_key_length_validation(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        with pytest.raises(ValueError):
            store.set("", "v")
        with pytest.raises(ValueError):
            store.set("x" * 65536, "v")
        with pytest.raises(ValueError):
            store.set("值" * 40000, "v")  # 120000 UTF-8 bytes
        store.set("x" * 65535, "v")  # exactly at the byte limit
        assert store.get("x" * 65535) == "v"


def test_store_max_segment_bytes_validation(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path / "a", max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path / "b", max_segment_bytes="40")  # type: ignore[arg-type]
    KVStore(tmp_path / "c", max_segment_bytes=16).close()


def test_store_closed_raises_and_close_idempotent(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path / "d")
    store.close()
    store.close()  # idempotent
    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(ValueError):
        store.set("a", "1")
    with pytest.raises(ValueError):
        store.delete("a")
    with pytest.raises(ValueError):
        store.keys()
    with pytest.raises(ValueError):
        store.stats()


def test_store_ignores_foreign_files(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    root.mkdir()
    (root / "notes.txt").write_bytes(b"junk")
    (root / "000005.seg.tmp").write_bytes(b"junk")
    (root / "12.seg").write_bytes(b"junk")
    with KVStore(root) as store:
        store.set("a", "1")
        assert store.get("a") == "1"
        assert store.stats().segment_count == 1


def test_store_recovers_from_truncated_tail(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
        store.set("b", "2")
    with open(root / "000001.seg", "ab") as fh:
        fh.write(encode_record("c", "3")[:8])  # crashed mid-write
    with KVStore(root) as store:
        assert store.get("a") == "1"
        assert store.get("b") == "2"
        assert store.get("c") is None


def test_store_write_after_crash_tail_stays_visible(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
    with open(root / "000001.seg", "ab") as fh:
        fh.write(b"KVR1\x00\x00")  # partial header
    with KVStore(root) as store:
        store.set("b", "2")
    with KVStore(root) as store:
        assert store.get("a") == "1"
        assert store.get("b") == "2"


def test_store_stats(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path / "d") as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        store.delete("b")
        s = store.stats()
    assert isinstance(s, Stats)
    assert s.live_keys == 1
    assert s.tombstones == 1
    assert s.total_records == 4
    assert s.dead_records == 2
    assert s.segment_count == 1
    assert s.bytes_on_disk == 17 * 3 + 16


def test_store_corrupt_segment_surfaces_on_open(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
    path = root / "000001.seg"
    data = bytearray(path.read_bytes())
    data[0] = 0  # bad magic
    path.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError):
        KVStore(root)


# ---------------------------------------------------------------------------
# compaction
# ---------------------------------------------------------------------------


def test_compact_basic(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root, max_segment_bytes=40) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")  # rolls into a second segment, first "a" is dead
        before_keys = store.keys()
        result = compact(store)
        assert isinstance(result, CompactionResult)
        assert result.segments_removed == 2
        assert result.records_written == 2
        assert result.records_dropped == 1
        assert result.bytes_reclaimed == 17
        assert store.keys() == before_keys
        assert store.get("a") == "3"
        assert store.get("b") == "2"
    with KVStore(root) as store:
        assert store.get("a") == "3"
        assert store.get("b") == "2"
        assert store.stats().segment_count == 1


def test_compact_drops_tombstones(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
        store.delete("a")
        store.set("b", "2")
        result = compact(store)
        assert result.records_written == 1
        assert result.records_dropped == 2
        assert store.keys() == ["b"]
        assert store.stats().tombstones == 0
        assert store.stats().total_records == 1
    with KVStore(root) as store:
        assert store.get("a") is None
        assert store.keys() == ["b"]


def test_compact_preserves_key_order(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        assert store.keys() == ["b", "a"]
        compact(store)
        assert store.keys() == ["b", "a"]


def test_compact_empty_store_creates_segment(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        result = compact(store)
        assert result.records_written == 0
        assert result.segments_removed == 1
        assert (root / "000002.seg").exists()
        assert store.keys() == []


def test_compact_then_writes_use_new_segment(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root, max_segment_bytes=40) as store:
        store.set("a", "1")
        compact(store)
        store.set("b", "2")
        assert store.stats().segment_count == 1
        store.set("c", "3")  # 34 + 17 > 40 -> rollover
        assert store.stats().segment_count == 2
    with KVStore(root) as store:
        assert store.get("c") == "3"
        assert store.keys() == ["a", "b", "c"]


def test_compact_leftover_tmp_file_ignored(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
    (root / "000009.seg.tmp").write_bytes(b"junk from a dead compaction")
    with KVStore(root) as store:
        assert store.get("a") == "1"
        result = compact(store)
        assert result.records_written == 1
        assert store.get("a") == "1"


# ---------------------------------------------------------------------------
# errors / public surface
# ---------------------------------------------------------------------------


def test_error_hierarchy() -> None:
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(RecordError, KVStoreError)
    assert issubclass(CorruptSegmentError, KVStoreError)
    assert issubclass(KVStoreError, Exception)


def test_corrupt_segment_error_attributes(tmp_path: pathlib.Path) -> None:
    err = CorruptSegmentError(tmp_path / "000007.seg", 123, "bad magic")
    assert err.path == tmp_path / "000007.seg"
    assert err.offset == 123
    assert err.reason == "bad magic"
    assert "000007.seg" in str(err)
    assert "123" in str(err)


def test_all_exports() -> None:
    expected = {
        "KVStore",
        "Stats",
        "Index",
        "Location",
        "Segment",
        "CompactionResult",
        "compact",
        "encode_record",
        "decode_record",
        "KVStoreError",
        "RecordError",
        "IncompleteRecordError",
        "CorruptRecordError",
        "CorruptSegmentError",
    }
    assert set(kvstore.__all__) == expected


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_set_get_roundtrip(tmp_path: pathlib.Path, capsys) -> None:
    root = str(tmp_path / "d")
    assert cli_main([root, "set", "a", "1"]) == 0
    assert cli_main([root, "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"


def test_cli_get_absent_exit_1(tmp_path: pathlib.Path, capsys) -> None:
    assert cli_main([str(tmp_path / "d"), "get", "zz"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_delete_exit_codes(tmp_path: pathlib.Path, capsys) -> None:
    root = str(tmp_path / "d")
    assert cli_main([root, "set", "a", "1"]) == 0
    assert cli_main([root, "delete", "a"]) == 0
    assert cli_main([root, "delete", "a"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_list(tmp_path: pathlib.Path, capsys) -> None:
    root = str(tmp_path / "d")
    cli_main([root, "set", "a", "1"])
    cli_main([root, "set", "b", "2"])
    capsys.readouterr()
    assert cli_main([root, "list"]) == 0
    assert capsys.readouterr().out == "a\nb\n"


def test_cli_stats_format(tmp_path: pathlib.Path, capsys) -> None:
    root = str(tmp_path / "d")
    cli_main([root, "set", "a", "1"])
    capsys.readouterr()
    assert cli_main([root, "stats"]) == 0
    assert capsys.readouterr().out == (
        "live_keys=1 tombstones=0 total_records=1 dead_records=0 "
        "segment_count=1 bytes_on_disk=17\n"
    )


def test_cli_compact_output(tmp_path: pathlib.Path, capsys) -> None:
    root = str(tmp_path / "d")
    cli_main([root, "set", "a", "1"])
    cli_main([root, "set", "a", "2"])
    capsys.readouterr()
    assert cli_main([root, "compact"]) == 0
    assert capsys.readouterr().out == "removed=1 written=1 dropped=1 reclaimed=17\n"


def test_cli_max_segment_bytes_flag(tmp_path: pathlib.Path) -> None:
    root = str(tmp_path / "d")
    assert cli_main(["--max-segment-bytes", "20", root, "set", "a", "1"]) == 0
    assert cli_main(["--max-segment-bytes", "20", root, "set", "b", "2"]) == 0
    assert len(list((tmp_path / "d").glob("*.seg"))) == 2


def test_cli_unknown_command_exit_2(tmp_path: pathlib.Path, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main([str(tmp_path / "d"), "bogus"])
    assert excinfo.value.code == 2
    assert capsys.readouterr().out == ""


def test_cli_missing_args_exit_2(tmp_path: pathlib.Path, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main([str(tmp_path / "d"), "set", "onlykey"])
    assert excinfo.value.code == 2


def test_cli_bad_max_segment_bytes_exit_2(tmp_path: pathlib.Path, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--max-segment-bytes", "abc", str(tmp_path / "d"), "list"])
    assert excinfo.value.code == 2


def test_cli_store_value_error_exit_2(tmp_path: pathlib.Path, capsys) -> None:
    assert cli_main([str(tmp_path / "d"), "set", "x" * 70000, "v"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_cli_corrupt_segment_exit_3(tmp_path: pathlib.Path, capsys) -> None:
    root = tmp_path / "d"
    with KVStore(root) as store:
        store.set("a", "1")
    path = root / "000001.seg"
    data = bytearray(path.read_bytes())
    data[4] = 0x55  # unknown flags
    path.write_bytes(bytes(data))
    assert cli_main([str(root), "list"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "000001.seg" in captured.err


def test_cli_module_subprocess(tmp_path: pathlib.Path) -> None:
    root = str(tmp_path / "d")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "kvstore", root, *args],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )

    assert run("set", "a", "1").returncode == 0
    result = run("get", "a")
    assert result.returncode == 0
    assert result.stdout == "1\n"
    assert run("get", "zz").returncode == 1
    assert run("list").stdout == "a\n"
    stats = run("stats")
    assert stats.returncode == 0
    assert len(stats.stdout.strip().split()) == 6
