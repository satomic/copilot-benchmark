"""Test suite for kvstore."""

from __future__ import annotations

import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

import kvstore
from kvstore import (
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    KVStore,
    Location,
    Segment,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _seg_file(root: pathlib.Path, seg_id: int = 1) -> pathlib.Path:
    return root / f"{seg_id:06d}.seg"


def _write_segment(root: pathlib.Path, *blobs: bytes, seg_id: int = 1) -> pathlib.Path:
    path = _seg_file(root, seg_id)
    path.write_bytes(b"".join(blobs))
    return path


# ---------------------------------------------------------------- record codec


def test_record_round_trip_value() -> None:
    blob = encode_record("alpha", "beta")
    assert decode_record(blob) == ("alpha", "beta", len(blob))


def test_record_round_trip_unicode() -> None:
    blob = encode_record("键", "héllo ✓")
    assert decode_record(blob) == ("键", "héllo ✓", len(blob))


def test_record_layout_and_size() -> None:
    blob = encode_record("ab", "xyz")
    assert len(blob) == 15 + 2 + 3
    assert blob[:4] == b"KVR1"
    assert blob[4] == 0x00
    assert struct.unpack(">H", blob[5:7])[0] == 2
    assert struct.unpack(">I", blob[7:11])[0] == 3
    assert struct.unpack(">I", blob[11:15])[0] == zlib.crc32(b"abxyz")


def test_tombstone_round_trip() -> None:
    blob = encode_record("gone", None)
    assert len(blob) == 15 + 4
    assert blob[4] == 0x01
    assert decode_record(blob) == ("gone", None, 19)


def test_tombstone_and_empty_value_differ() -> None:
    empty = encode_record("k", "")
    tomb = encode_record("k", None)
    assert len(empty) == len(tomb) == 15 + 1
    assert decode_record(empty)[1] == ""
    assert decode_record(tomb)[1] is None
    assert empty != tomb


def test_decode_at_offset() -> None:
    buf = b"junk" + encode_record("a", "1") + encode_record("b", None)
    k1, v1, n1 = decode_record(buf, 4)
    k2, v2, n2 = decode_record(buf, 4 + n1)
    assert (k1, v1) == ("a", "1")
    assert (k2, v2) == ("b", None)
    assert 4 + n1 + n2 == len(buf)


def test_incomplete_short_header() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("a", "b")[:10])


def test_incomplete_body() -> None:
    with pytest.raises(IncompleteRecordError):
        decode_record(encode_record("abc", "defgh")[:-1])


def test_bad_magic_is_corrupt() -> None:
    blob = b"XXXX" + encode_record("a", "b")[4:]
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_unknown_flags_is_corrupt() -> None:
    blob = bytearray(encode_record("a", "b"))
    blob[4] = 0x02
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_zero_key_len_is_corrupt() -> None:
    header = struct.pack(">4sBHII", b"KVR1", 0, 0, 0, zlib.crc32(b""))
    with pytest.raises(CorruptRecordError):
        decode_record(header)


def test_tombstone_with_value_len_is_corrupt() -> None:
    body = b"k" + b"v"
    header = struct.pack(">4sBHII", b"KVR1", 1, 1, 1, zlib.crc32(body))
    with pytest.raises(CorruptRecordError):
        decode_record(header + body)


def test_crc_mismatch_is_corrupt() -> None:
    blob = bytearray(encode_record("key", "value"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError, match="CRC"):
        decode_record(bytes(blob))


def test_invalid_utf8_is_corrupt_after_crc() -> None:
    key, value = b"k", b"\xff\xfe"
    header = struct.pack(">4sBHII", b"KVR1", 0, 1, 2, zlib.crc32(key + value))
    with pytest.raises(CorruptRecordError, match="UTF-8"):
        decode_record(header + key + value)


def test_encode_rejects_bytes_key_and_bad_lengths() -> None:
    with pytest.raises(TypeError):
        encode_record(b"k", "v")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        encode_record("", "v")
    with pytest.raises(ValueError):
        encode_record("x" * 65536, "v")


# ---------------------------------------------------------------- segments


def test_segment_append_and_scan(tmp_path: pathlib.Path) -> None:
    seg = Segment(_seg_file(tmp_path), 1)
    first = seg.append(encode_record("a", "1"))
    second = seg.append(encode_record("b", None))
    seg.close()
    assert first == 0
    assert second == 17
    reopened = Segment(_seg_file(tmp_path), 1)
    assert list(reopened.scan()) == [("a", "1", 0), ("b", None, 17)]
    assert reopened.size == 17 + 16
    reopened.close()


def test_truncated_header_tail_is_ignored(tmp_path: pathlib.Path) -> None:
    path = _write_segment(tmp_path, encode_record("a", "1"), encode_record("b", "2")[:7])
    seg = Segment(path, 1)
    assert [(k, v) for k, v, _ in seg.scan()] == [("a", "1")]
    seg.close()


def test_truncated_body_tail_is_ignored(tmp_path: pathlib.Path) -> None:
    path = _write_segment(tmp_path, encode_record("a", "1"), encode_record("bb", "twotwo")[:-3])
    seg = Segment(path, 1)
    assert [(k, v) for k, v, _ in seg.scan()] == [("a", "1")]
    seg.close()


def test_corrupt_last_record_is_reported(tmp_path: pathlib.Path) -> None:
    bad = bytearray(encode_record("b", "2"))
    bad[-1] ^= 0x01
    path = _write_segment(tmp_path, encode_record("a", "1"), bytes(bad))
    seg = Segment(path, 1)
    with pytest.raises(CorruptSegmentError) as info:
        list(seg.scan())
    assert info.value.offset == len(encode_record("a", "1"))
    assert info.value.path == path
    seg.close()


def test_corrupt_segment_error_message(tmp_path: pathlib.Path) -> None:
    err = CorruptSegmentError(tmp_path / "000007.seg", 1234, "CRC mismatch")
    text = str(err)
    assert "000007.seg" in text
    assert "1234" in text


def test_scan_of_empty_segment_yields_nothing(tmp_path: pathlib.Path) -> None:
    seg = Segment(_seg_file(tmp_path), 1)
    assert list(seg.scan()) == []
    assert seg.size == 0
    seg.close()


# ---------------------------------------------------------------- store basics


def test_set_get_round_trip(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.get("a") == "1"
        assert store.get("missing") is None


def test_empty_string_value_is_not_none(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("e", "")
        assert store.get("e") == ""
        assert store.keys() == ["e"]


def test_delete_semantics(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.delete("a") is True
        assert store.get("a") is None
        assert store.delete("a") is False
        assert store.delete("never") is False


def test_noop_delete_writes_nothing(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        size = store.stats().bytes_on_disk
        assert store.delete("zzz") is False
        store.delete("a")
        size_after_delete = store.stats().bytes_on_disk
        assert store.delete("a") is False
        assert store.stats().bytes_on_disk == size_after_delete
        assert size_after_delete > size


def test_persistence_across_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
        store.set("a", "3")
        store.delete("b")
    with KVStore(tmp_path) as store:
        assert store.get("a") == "3"
        assert store.get("b") is None
        assert store.keys() == ["a"]


def test_root_is_created_if_missing(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "nested" / "store"
    with KVStore(root) as store:
        store.set("a", "1")
    assert _seg_file(root).exists()


def test_empty_store_creates_first_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        assert store.stats().segment_count == 1
    assert _seg_file(tmp_path).exists()


def test_keys_ordering_and_rewrite_moves_to_end(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("c", "1")
        store.set("a", "1")
        store.set("b", "1")
        store.set("c", "2")
        assert store.keys() == ["a", "b", "c"]


def test_keys_order_survives_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        for name in ("x", "y", "z", "w"):
            store.set(name, name * 5)
        store.set("x", "new")
        expected = store.keys()
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        assert store.keys() == expected


def test_set_rejects_bytes_key_without_writing(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"k", "v")  # type: ignore[arg-type]
        assert store.stats().total_records == 0
        assert store.stats().bytes_on_disk == 0


def test_set_rejects_non_str_value(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set("k", 5)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            store.set("k", None)  # type: ignore[arg-type]
        assert store.keys() == []


def test_long_cjk_key_rejected_by_byte_length(tmp_path: pathlib.Path) -> None:
    key = "键" * 40000  # 120000 UTF-8 bytes
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set(key, "v")
        assert store.stats().total_records == 0


def test_empty_key_rejected(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        with pytest.raises(ValueError):
            store.set("", "v")
        with pytest.raises(ValueError):
            store.delete("")


@pytest.mark.parametrize("bad", [0, 15, -1, 4096.0, "4096", True])
def test_invalid_max_segment_bytes(tmp_path: pathlib.Path, bad: object) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=bad)  # type: ignore[arg-type]


def test_closed_store_raises_and_close_is_idempotent(tmp_path: pathlib.Path) -> None:
    store = KVStore(tmp_path)
    store.set("a", "1")
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(ValueError):
        store.set("b", "2")


# ---------------------------------------------------------------- rollover


def test_rollover_creates_new_segments(tmp_path: pathlib.Path) -> None:
    blob_len = len(encode_record("k0", "x" * 10))  # 15 + 2 + 10 = 27
    with KVStore(tmp_path, max_segment_bytes=60) as store:
        for i in range(5):
            store.set(f"k{i}", "x" * 10)
        stats = store.stats()
    assert blob_len == 27
    assert stats.segment_count == 3
    assert sorted(p.name for p in tmp_path.glob("*.seg")) == [
        "000001.seg", "000002.seg", "000003.seg",
    ]


def test_exact_fit_does_not_roll_over(tmp_path: pathlib.Path) -> None:
    rec = len(encode_record("a", "b"))  # 18
    with KVStore(tmp_path, max_segment_bytes=rec * 2) as store:
        store.set("a", "b")
        store.set("c", "d")
        assert store.stats().segment_count == 1
        store.set("e", "f")
        assert store.stats().segment_count == 2


def test_oversized_record_is_stored_in_empty_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("big", "y" * 200)
        assert store.get("big") == "y" * 200
        assert store.stats().segment_count == 1


def test_reads_across_segments_after_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        for i in range(10):
            store.set(f"k{i}", f"v{i}")
    with KVStore(tmp_path, max_segment_bytes=32) as store:
        assert [store.get(f"k{i}") for i in range(10)] == [f"v{i}" for i in range(10)]


# ---------------------------------------------------------------- recovery


def test_non_matching_files_are_ignored(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    (tmp_path / "000003.seg.tmp").write_bytes(b"garbage that must not be read")
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "1234567.seg").write_bytes(b"x")
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a"]
        assert store.stats().segment_count == 1


def test_truncated_tail_is_recovered_and_appendable(tmp_path: pathlib.Path) -> None:
    path = _write_segment(tmp_path, encode_record("a", "1"), encode_record("b", "2")[:9])
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a"]
        assert store.stats().bytes_on_disk == path.stat().st_size
        store.set("c", "3")
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "c"]
        assert store.get("c") == "3"


def test_corrupt_segment_is_reported_on_open(tmp_path: pathlib.Path) -> None:
    bad = bytearray(encode_record("a", "1"))
    bad[-1] ^= 0xFF
    _write_segment(tmp_path, bytes(bad))
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_later_segments_win_on_recovery(tmp_path: pathlib.Path) -> None:
    _write_segment(tmp_path, encode_record("a", "old"), seg_id=1)
    _write_segment(tmp_path, encode_record("a", "new"), seg_id=2)
    with KVStore(tmp_path) as store:
        assert store.get("a") == "new"


def test_stats_fields(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "1")
        store.delete("b")
        stats = store.stats()
    assert stats.live_keys == 1
    assert stats.tombstones == 1
    assert stats.total_records == 4
    assert stats.dead_records == 2
    assert stats.segment_count == 1
    assert stats.bytes_on_disk == _seg_file(tmp_path).stat().st_size


def test_stats_is_a_named_fields_record() -> None:
    fields = [f for f in kvstore.Stats.__dataclass_fields__]
    assert fields == [
        "live_keys", "tombstones", "total_records",
        "dead_records", "segment_count", "bytes_on_disk",
    ]


# ---------------------------------------------------------------- compaction


def test_compaction_result_and_contents(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=64) as store:
        for i in range(6):
            store.set(f"k{i}", f"v{i}")
        store.set("k0", "v0-new")
        store.set("k1", "v1-new")
        store.delete("k2")
        store.delete("k3")
        before = store.stats()
        expected_keys = store.keys()
        result = compact(store)
        after = store.stats()
        assert store.keys() == expected_keys
        assert expected_keys == ["k4", "k5", "k0", "k1"]
        assert [store.get(k) for k in expected_keys] == ["v4", "v5", "v0-new", "v1-new"]
    assert result.segments_removed == before.segment_count
    assert result.records_written == len(expected_keys) == 4
    assert result.records_dropped == before.total_records - 4
    assert result.bytes_reclaimed == before.bytes_on_disk - after.bytes_on_disk
    assert after.segment_count == 1
    assert after.total_records == 4
    assert after.tombstones == 0
    assert after.dead_records == 0


def test_compaction_preserves_key_order_and_values(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        for name in ("d", "a", "c", "b"):
            store.set(name, name.upper())
        store.set("a", "AA")
        store.delete("c")
        order = store.keys()
        compact(store)
        assert store.keys() == order == ["d", "b", "a"]
        assert store.get("a") == "AA"
        assert store.get("c") is None


def test_compaction_no_tmp_left_and_new_segment_id(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        store.set("a", "1")
        store.set("b", "2")
        compact(store)
        names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["000002.seg"]


def test_compaction_empty_result_creates_active_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        result = compact(store)
        assert result.records_written == 0
        assert store.keys() == []
        store.set("b", "2")
    with KVStore(tmp_path) as store:
        assert store.keys() == ["b"]


def test_writes_after_compaction_and_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=50) as store:
        store.set("a", "1")
        store.set("b", "2")
        compact(store)
        for i in range(5):
            store.set(f"n{i}", "x" * 20)
        expected = store.keys()
    with KVStore(tmp_path, max_segment_bytes=50) as store:
        assert store.keys() == expected
        assert store.get("b") == "2"


def test_compaction_leaves_only_new_segment_on_disk(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=30) as store:
        for i in range(8):
            store.set(f"k{i}", "v")
        compact(store)
    assert [p.name for p in tmp_path.glob("*.seg")] == ["000009.seg"]


# ---------------------------------------------------------------- CLI


def _cli(root: pathlib.Path, *args: str) -> int:
    return main([str(root), *args])


def test_cli_round_trip(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "data"
    assert _cli(root, "set", "a", "1") == 0
    assert capsys.readouterr().out == ""
    assert _cli(root, "get", "a") == 0
    assert capsys.readouterr().out == "1\n"
    assert _cli(root, "get", "zz") == 1
    assert capsys.readouterr().out == ""
    assert _cli(root, "list") == 0
    assert capsys.readouterr().out == "a\n"
    assert _cli(root, "stats") == 0
    line = capsys.readouterr().out
    assert line.count("\n") == 1
    fields = [f.split("=")[0] for f in line.split()]
    assert fields == [
        "live_keys", "tombstones", "total_records",
        "dead_records", "segment_count", "bytes_on_disk",
    ]


def test_cli_get_empty_value(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "d"
    assert _cli(root, "set", "e", "") == 0
    assert _cli(root, "get", "e") == 0
    assert capsys.readouterr().out == "\n"


def test_cli_delete_exit_codes(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "d"
    _cli(root, "set", "a", "1")
    assert _cli(root, "delete", "a") == 0
    assert _cli(root, "delete", "a") == 1
    assert _cli(root, "delete", "never") == 1
    assert capsys.readouterr().out == ""


def test_cli_compact_output(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "d"
    _cli(root, "set", "a", "1")
    _cli(root, "set", "a", "2")
    capsys.readouterr()
    assert _cli(root, "compact") == 0
    out = capsys.readouterr().out
    assert out.startswith("removed=1 written=1 dropped=1 reclaimed=")
    assert out.endswith("\n")


def test_cli_unknown_command_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli(tmp_path, "frobnicate") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_cli_missing_argument_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli(tmp_path, "set", "onlykey") == 2
    assert capsys.readouterr().out == ""


def test_cli_extra_argument_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli(tmp_path, "list", "extra") == 2


def test_cli_bad_max_segment_bytes_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "--max-segment-bytes", "abc", "list"]) == 2
    assert main([str(tmp_path), "--max-segment-bytes", "3", "list"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_overlong_key_exits_2_without_stdout(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _cli(tmp_path, "set", "键" * 40000, "v") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "key" in captured.err


def test_cli_corruption_exits_3(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = bytearray(encode_record("a", "1"))
    bad[-1] ^= 0xFF
    _write_segment(tmp_path, bytes(bad))
    assert _cli(tmp_path, "list") == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "000001.seg" in captured.err


def test_cli_max_segment_bytes_flag(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path), "--max-segment-bytes", "20", "set", "a", "1"]) == 0
    assert main([str(tmp_path), "--max-segment-bytes", "20", "set", "b", "2"]) == 0
    capsys.readouterr()
    assert _cli(tmp_path, "stats") == 0
    assert "segment_count=2" in capsys.readouterr().out


def test_module_entry_point_subprocess(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "data"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "kvstore", str(root), *args],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
        )

    assert run("set", "a", "1").returncode == 0
    result = run("get", "a")
    assert result.returncode == 0 and result.stdout == "1\n"
    assert run("get", "zz").returncode == 1
    assert run("bogus").returncode == 2


def test_public_api_exports() -> None:
    expected = {
        "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult", "compact",
        "encode_record", "decode_record",
        "KVStoreError", "RecordError", "IncompleteRecordError", "CorruptRecordError",
        "CorruptSegmentError",
    }
    assert set(kvstore.__all__) == expected
    assert Location(1, 0) == Location(seg_id=1, offset=0)
