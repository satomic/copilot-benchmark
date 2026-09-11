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
    CompactionResult,
    CorruptRecordError,
    CorruptSegmentError,
    IncompleteRecordError,
    Index,
    KVStore,
    Location,
    RecordError,
    Segment,
    Stats,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main

HEADER = 15


def seg_path(root: pathlib.Path, seg_id: int) -> pathlib.Path:
    return root / f"{seg_id:06d}.seg"


def run_cli(*argv: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "kvstore", *argv],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(__file__).resolve().parent.parent,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ------------------------------------------------------------------ record codec


def test_record_round_trip() -> None:
    blob = encode_record("key", "value")
    assert len(blob) == HEADER + 3 + 5
    assert blob[:4] == b"KVR1"
    assert decode_record(blob) == ("key", "value", len(blob))


def test_record_layout_fields() -> None:
    blob = encode_record("ab", "xyz")
    magic, flags, key_len, value_len, crc = struct.unpack(">4sBHII", blob[:HEADER])
    assert (magic, flags, key_len, value_len) == (b"KVR1", 0, 2, 3)
    assert crc == zlib.crc32(b"abxyz")


def test_record_unicode_round_trip() -> None:
    blob = encode_record("clé", "värde 日本")
    assert decode_record(blob)[:2] == ("clé", "värde 日本")


def test_tombstone_vs_empty_value() -> None:
    tomb = encode_record("k", None)
    empty = encode_record("k", "")
    assert len(tomb) == len(empty) == HEADER + 1
    assert tomb != empty
    assert tomb[4] == 0x01 and empty[4] == 0x00
    assert decode_record(tomb)[1] is None
    assert decode_record(empty)[1] == ""


def test_decode_with_offset() -> None:
    a = encode_record("a", "1")
    b = encode_record("b", "2")
    assert decode_record(a + b, len(a)) == ("b", "2", len(b))


def test_decode_incomplete_header() -> None:
    blob = encode_record("k", "v")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:10])


def test_decode_incomplete_body() -> None:
    blob = encode_record("key", "value")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:-1])


def test_decode_bad_magic() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[0:4] = b"XXXX"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_unknown_flags() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[4] = 0x02
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_zero_key_len() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[5:7] = b"\x00\x00"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_tombstone_with_value() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[4] = 0x01
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_crc_mismatch() -> None:
    blob = bytearray(encode_record("k", "v"))
    blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_invalid_utf8() -> None:
    key_bytes = b"\xff\xfe"
    crc = zlib.crc32(key_bytes)
    blob = struct.pack(">4sBHII", b"KVR1", 0, 2, 0, crc) + key_bytes
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_error_hierarchy() -> None:
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(RecordError, kvstore.KVStoreError)
    assert issubclass(CorruptSegmentError, kvstore.KVStoreError)
    err = CorruptSegmentError(pathlib.Path("/x/000007.seg"), 42, "bad")
    assert "000007.seg" in str(err) and "42" in str(err)
    assert err.offset == 42 and err.reason == "bad"


# --------------------------------------------------------------------- segment


def test_segment_append_and_scan(tmp_path: pathlib.Path) -> None:
    seg = Segment(seg_path(tmp_path, 1), 1)
    a = encode_record("a", "1")
    assert seg.append(a) == 0
    assert seg.append(encode_record("b", None)) == len(a)
    assert seg.size == len(a) + HEADER + 1
    assert list(seg.scan()) == [("a", "1", 0), ("b", None, len(a))]
    seg.close()


def test_segment_truncated_tail_ignored(tmp_path: pathlib.Path) -> None:
    p = seg_path(tmp_path, 1)
    good = encode_record("a", "1")
    p.write_bytes(good + encode_record("bb", "longvalue")[:-3])
    seg = Segment(p, 1)
    assert list(seg.scan()) == [("a", "1", 0)]
    seg.close()


def test_segment_crc_mismatch_at_end_is_corruption(tmp_path: pathlib.Path) -> None:
    p = seg_path(tmp_path, 1)
    good = encode_record("a", "1")
    bad = bytearray(encode_record("b", "2"))
    bad[-1] ^= 0x01
    p.write_bytes(good + bytes(bad))
    seg = Segment(p, 1)
    with pytest.raises(CorruptSegmentError) as info:
        list(seg.scan())
    assert info.value.offset == len(good)
    assert info.value.path == p
    assert "000001.seg" in str(info.value) and str(len(good)) in str(info.value)
    seg.close()


# ----------------------------------------------------------------------- index


def test_index_put_get_and_tombstone() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    assert idx.get("a") == Location(1, 0)
    idx.put("a", Location(1, 20), tombstone=True)
    assert idx.get("a") is None
    assert idx.tombstone_count() == 1
    assert len(idx) == 0
    idx.put("a", Location(2, 0), tombstone=False)
    assert idx.tombstone_count() == 0 and len(idx) == 1


def test_index_live_keys_order() -> None:
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 10), tombstone=False)
    idx.put("c", Location(2, 0), tombstone=False)
    assert idx.live_keys() == ["a", "b", "c"]
    idx.put("a", Location(2, 30), tombstone=False)
    assert idx.live_keys() == ["b", "c", "a"]


# ----------------------------------------------------------------------- store


def test_store_set_get_and_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        s.set("b", "2")
        assert s.get("a") == "1"
    with KVStore(tmp_path) as s:
        assert s.get("a") == "1" and s.get("b") == "2"
        assert s.get("zz") is None


def test_store_empty_value_is_not_none(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("e", "")
        assert s.get("e") == ""
    with KVStore(tmp_path) as s:
        assert s.get("e") == ""
        assert s.keys() == ["e"]


def test_store_delete_semantics(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        size_before = seg_path(tmp_path, 1).stat().st_size
        assert s.delete("a") is True
        assert seg_path(tmp_path, 1).stat().st_size > size_before
        size_after = seg_path(tmp_path, 1).stat().st_size
        assert s.delete("a") is False
        assert s.delete("missing") is False
        assert seg_path(tmp_path, 1).stat().st_size == size_after
        assert s.get("a") is None
    with KVStore(tmp_path) as s:
        assert s.get("a") is None
        assert s.stats().tombstones == 1


def test_store_overwrite_moves_key_to_end(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        s.set("b", "2")
        s.set("c", "3")
        s.set("a", "9")
        assert s.keys() == ["b", "c", "a"]
    with KVStore(tmp_path) as s:
        assert s.keys() == ["b", "c", "a"]
        assert s.get("a") == "9"


def test_store_type_validation(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        with pytest.raises(TypeError):
            s.set(b"k", "v")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            s.set("k", 1)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            s.get(1)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            s.set("", "v")
        with pytest.raises(ValueError):
            s.set("日" * 40000, "v")
        s.set("日" * 21845, "ok")  # 65535 bytes exactly
        assert s.stats().total_records == 1


def test_store_max_segment_bytes_validation(tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=15)
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes="64")  # type: ignore[arg-type]
    KVStore(tmp_path, max_segment_bytes=16).close()


def test_store_closed_raises(tmp_path: pathlib.Path) -> None:
    s = KVStore(tmp_path)
    s.close()
    s.close()
    with pytest.raises(ValueError):
        s.get("a")
    with pytest.raises(ValueError):
        s.set("a", "b")


def test_store_rollover(tmp_path: pathlib.Path) -> None:
    rec = len(encode_record("k1", "vv"))  # 19 bytes
    with KVStore(tmp_path, max_segment_bytes=rec * 2) as s:
        s.set("k1", "vv")
        s.set("k2", "vv")  # exactly fills: 38 == 38, still fits
        assert s.stats().segment_count == 1
        s.set("k3", "vv")
        assert s.stats().segment_count == 2
        assert seg_path(tmp_path, 2).exists()
        assert s.keys() == ["k1", "k2", "k3"]
    with KVStore(tmp_path, max_segment_bytes=rec * 2) as s:
        assert s.get("k3") == "vv"
        s.set("k4", "vv")
        assert s.stats().segment_count == 2


def test_store_oversized_record_in_empty_segment(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=16) as s:
        s.set("big", "x" * 1000)
        assert s.stats().segment_count == 1
        s.set("b", "y")
        assert s.stats().segment_count == 2
        assert s.get("big") == "x" * 1000


def test_store_recovers_truncated_tail(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
    p = seg_path(tmp_path, 1)
    p.write_bytes(p.read_bytes() + encode_record("b", "partial")[:-2])
    truncated_size = p.stat().st_size
    with KVStore(tmp_path) as s:
        assert s.get("a") == "1" and s.get("b") is None
        st = s.stats()
        assert st.total_records == 1
        assert st.bytes_on_disk == truncated_size
        s.set("c", "3")
        assert s.get("c") == "3"


def test_store_reports_corruption(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        s.set("b", "2")
    p = seg_path(tmp_path, 1)
    data = bytearray(p.read_bytes())
    data[-1] ^= 0xFF
    p.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError) as info:
        KVStore(tmp_path)
    assert info.value.offset == len(encode_record("a", "1"))


def test_store_ignores_non_segment_files(tmp_path: pathlib.Path) -> None:
    (tmp_path / "000003.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notes.txt").write_bytes(b"garbage")
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        st = s.stats()
        assert st.segment_count == 1
        assert st.bytes_on_disk == seg_path(tmp_path, 1).stat().st_size


def test_store_stats(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        assert s.stats() == Stats(0, 0, 0, 0, 1, 0)
        s.set("a", "1")
        s.set("a", "2")
        s.set("b", "1")
        s.delete("b")
        s.set("c", "1")
        st = s.stats()
        assert (st.live_keys, st.tombstones, st.total_records, st.dead_records) == (2, 1, 5, 2)
        assert st.segment_count == 1
        assert st.bytes_on_disk == seg_path(tmp_path, 1).stat().st_size
    with KVStore(tmp_path) as s:
        assert s.stats() == st


def test_store_creates_root(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "nested" / "data"
    with KVStore(root) as s:
        s.set("a", "1")
    assert seg_path(root, 1).exists()


# ------------------------------------------------------------------ compaction


def test_compact_basic(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=40) as s:
        s.set("a", "1")
        s.set("b", "2")
        s.set("a", "3")
        s.set("c", "4")
        s.delete("b")
        s.set("d", "5")
        before = s.stats()
        keys_before = s.keys()
        result = compact(s)
        assert isinstance(result, CompactionResult)
        assert result.segments_removed == before.segment_count
        assert result.records_written == 3
        assert result.records_dropped == before.total_records - 3
        assert result.bytes_reclaimed == before.bytes_on_disk - s.stats().bytes_on_disk
        assert result.bytes_reclaimed > 0
        assert s.keys() == keys_before == ["a", "c", "d"]
        assert s.get("a") == "3" and s.get("b") is None
        after = s.stats()
        assert after == Stats(3, 0, 3, 0, 1, after.bytes_on_disk)
        ids = sorted(int(p.name[:6]) for p in tmp_path.glob("*.seg"))
        assert ids == [before.segment_count + 1]
        assert not list(tmp_path.glob("*.tmp"))


def test_compact_writes_go_to_new_segment_and_roll_over(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path, max_segment_bytes=60) as s:
        s.set("a", "1")
        s.set("b", "2")
        compact(s)
        assert seg_path(tmp_path, 2).exists()
        s.set("c", "3")  # 51 bytes <= 60, appended to the compacted segment
        assert s.get("c") == "3"
        assert seg_path(tmp_path, 2).stat().st_size == 3 * 17
        s.set("d", "4")  # 68 bytes > 60 -> rollover
        assert s.stats().segment_count == 2
        assert seg_path(tmp_path, 3).exists()
    with KVStore(tmp_path, max_segment_bytes=60) as s:
        assert s.keys() == ["a", "b", "c", "d"]


def test_compact_empty_store(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        s.delete("a")
        result = compact(s)
        assert result.records_written == 0
        assert result.segments_removed == 1
        assert seg_path(tmp_path, 2).exists()
        assert s.stats() == Stats(0, 0, 0, 0, 1, 0)
        s.set("z", "1")
        assert s.get("z") == "1"


def test_compact_survives_reopen(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        s.set("b", "")
        s.delete("a")
        compact(s)
    with KVStore(tmp_path) as s:
        assert s.get("a") is None
        assert s.get("b") == ""
        assert s.keys() == ["b"]


def test_leftover_tmp_from_compaction_is_ignored(tmp_path: pathlib.Path) -> None:
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        s.delete("a")
        s.set("b", "2")
    # Simulate death before os.replace: tmp exists, old segment intact.
    (tmp_path / "000002.seg.tmp").write_bytes(encode_record("b", "2"))
    with KVStore(tmp_path) as s:
        assert s.get("a") is None and s.get("b") == "2"
        assert s.stats().total_records == 3


# -------------------------------------------------------------------------- CLI


def test_cli_round_trip(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    assert main([root, "set", "a", "1"]) == 0
    assert capsys.readouterr().out == ""
    assert main([root, "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([root, "get", "zz"]) == 1
    assert capsys.readouterr().out == ""
    assert main([root, "set", "b", "2"]) == 0
    assert main([root, "list"]) == 0
    assert capsys.readouterr().out == "a\nb\n"


def test_cli_delete_exit_codes(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    assert main([root, "delete", "a"]) == 0
    assert main([root, "delete", "a"]) == 1
    assert main([root, "delete", "nope"]) == 1
    assert capsys.readouterr().out == ""


def test_cli_stats_and_compact(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    assert main([root, "stats"]) == 0
    assert capsys.readouterr().out == (
        "live_keys=1 tombstones=0 total_records=1 dead_records=0 "
        "segment_count=1 bytes_on_disk=17\n"
    )
    main([root, "set", "a", "2"])
    assert main([root, "compact"]) == 0
    assert capsys.readouterr().out == "removed=1 written=1 dropped=1 reclaimed=17\n"


def test_cli_usage_errors(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    assert main([root, "bogus"]) == 2
    assert main([root, "get"]) == 2
    assert main([root, "get", "a", "extra"]) == 2
    assert main([root]) == 2
    assert main(["--max-segment-bytes", "abc", root, "list"]) == 2
    assert main(["--max-segment-bytes", "0", root, "list"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err != ""


def test_cli_store_value_error_exits_2(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    assert main([root, "set", "日" * 40000, "v"]) == 2
    assert main(["--max-segment-bytes", "8", root, "list"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and "error" in err


def test_cli_corruption_exits_3(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    p = seg_path(tmp_path, 1)
    data = bytearray(p.read_bytes())
    data[0] = 0x00
    p.write_bytes(bytes(data))
    assert main([root, "get", "a"]) == 3
    out, err = capsys.readouterr()
    assert out == "" and "000001.seg" in err and "offset 0" in err


def test_cli_subprocess_entry_point(tmp_path: pathlib.Path) -> None:
    root = str(tmp_path / "data")
    assert run_cli(root, "set", "a", "1")[0] == 0
    code, out, _ = run_cli(root, "get", "a")
    assert (code, out) == (0, "1\n")
    code, out, _ = run_cli(root, "get", "zz")
    assert (code, out) == (1, "")
    code, out, err = run_cli(root, "nope")
    assert code == 2 and out == "" and err


def test_public_all() -> None:
    expected = {
        "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult", "compact",
        "encode_record", "decode_record", "KVStoreError", "RecordError",
        "IncompleteRecordError", "CorruptRecordError", "CorruptSegmentError",
    }
    assert set(kvstore.__all__) == expected
    for name in expected:
        assert hasattr(kvstore, name)
