import os
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
    KVStoreError,
    Location,
    RecordError,
    Segment,
    Stats,
    compact,
    decode_record,
    encode_record,
)
from kvstore.__main__ import main

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def seg_files(root):
    return sorted(p.name for p in pathlib.Path(root).iterdir() if p.name.endswith(".seg"))


# --- record codec -----------------------------------------------------------

def test_record_round_trip():
    blob = encode_record("key", "value")
    assert decode_record(blob) == ("key", "value", len(blob))
    assert len(blob) == 15 + 3 + 5


def test_record_exact_layout():
    blob = encode_record("ab", "xyz")
    magic, flags, klen, vlen, crc = struct.unpack(">4sBHII", blob[:15])
    assert (magic, flags, klen, vlen) == (b"KVR1", 0, 2, 3)
    assert crc == zlib.crc32(b"abxyz")
    assert blob[15:] == b"abxyz"


def test_record_unicode_lengths_are_bytes():
    blob = encode_record("鍵", "値é")
    key, value, size = decode_record(blob)
    assert (key, value) == ("鍵", "値é")
    assert size == 15 + 3 + 5


def test_tombstone_vs_empty_value():
    tomb = encode_record("k", None)
    empty = encode_record("k", "")
    assert len(tomb) == len(empty) == 16
    assert tomb[4] == 1 and empty[4] == 0
    assert decode_record(tomb)[1] is None
    assert decode_record(empty)[1] == ""


def test_decode_at_offset():
    buf = encode_record("a", "1") + encode_record("b", "2")
    key, value, size = decode_record(buf, 17)
    assert (key, value, size) == ("b", "2", 17)


def test_decode_incomplete():
    blob = encode_record("key", "value")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:10])
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:-1])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b"XVR1" + b[4:],
        lambda b: b[:4] + b"\x02" + b[5:],
        lambda b: b[:-1] + bytes([b[-1] ^ 0xFF]),
    ],
)
def test_decode_corrupt(mutate):
    with pytest.raises(CorruptRecordError):
        decode_record(mutate(encode_record("key", "value")))


def test_decode_zero_key_len_and_bad_tombstone():
    zero = struct.pack(">4sBHII", b"KVR1", 0, 0, 1, zlib.crc32(b"x")) + b"x"
    with pytest.raises(CorruptRecordError):
        decode_record(zero)
    tomb = struct.pack(">4sBHII", b"KVR1", 1, 1, 1, zlib.crc32(b"kx")) + b"kx"
    with pytest.raises(CorruptRecordError):
        decode_record(tomb)


def test_decode_bad_utf8_with_valid_crc():
    body = b"\xff\xfe"
    blob = struct.pack(">4sBHII", b"KVR1", 0, 1, 1, zlib.crc32(body)) + body
    with pytest.raises(CorruptRecordError):
        decode_record(blob)


def test_error_hierarchy():
    assert issubclass(IncompleteRecordError, RecordError)
    assert issubclass(CorruptRecordError, RecordError)
    assert issubclass(RecordError, KVStoreError)
    assert issubclass(CorruptSegmentError, KVStoreError)
    err = CorruptSegmentError(pathlib.Path("x/000001.seg"), 42, "bad")
    assert "000001.seg" in str(err) and "42" in str(err)
    assert err.offset == 42 and err.reason == "bad"


def test_all_exports():
    assert sorted(kvstore.__all__) == sorted([
        "KVStore", "Stats", "Index", "Location", "Segment", "CompactionResult",
        "compact", "encode_record", "decode_record", "KVStoreError", "RecordError",
        "IncompleteRecordError", "CorruptRecordError", "CorruptSegmentError",
    ])


# --- segment ----------------------------------------------------------------

def test_segment_append_and_scan(tmp_path):
    seg = Segment(tmp_path / "000001.seg", 1)
    assert seg.append(encode_record("a", "1")) == 0
    assert seg.append(encode_record("b", None)) == 17
    assert seg.size == 33
    assert list(seg.scan()) == [("a", "1", 0), ("b", None, 17)]
    seg.close()


def test_segment_truncated_tail_is_ignored(tmp_path):
    path = tmp_path / "000001.seg"
    blob = encode_record("a", "1") + encode_record("bb", "22")
    for cut in (1, 10, 16):
        path.write_bytes(blob[: 17 + cut])
        assert list(Segment(path, 1).scan()) == [("a", "1", 0)]


def test_segment_crc_mismatch_in_last_record(tmp_path):
    path = tmp_path / "000001.seg"
    blob = bytearray(encode_record("a", "1") + encode_record("b", "2"))
    blob[-1] ^= 0x01
    path.write_bytes(bytes(blob))
    with pytest.raises(CorruptSegmentError) as info:
        list(Segment(path, 1).scan())
    assert info.value.offset == 17
    assert info.value.path == path
    assert "000001.seg" in str(info.value) and "17" in str(info.value)


# --- index ------------------------------------------------------------------

def test_index_ordering_and_counts():
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 10), tombstone=False)
    idx.put("c", Location(2, 0), tombstone=False)
    idx.put("a", Location(2, 5), tombstone=False)
    idx.put("b", Location(2, 9), tombstone=True)
    assert idx.live_keys() == ["c", "a"]
    assert idx.get("b") is None
    assert idx.get("a") == Location(2, 5)
    assert idx.tombstone_count() == 1
    assert len(idx) == 2
    idx.put("b", Location(3, 0), tombstone=False)
    assert idx.tombstone_count() == 0 and len(idx) == 3


# --- store ------------------------------------------------------------------

def test_store_basic_and_reopen(tmp_path):
    with KVStore(tmp_path / "db") as store:
        store.set("a", "1")
        store.set("b", "")
        assert store.get("a") == "1"
        assert store.get("b") == ""
        assert store.get("zz") is None
    with KVStore(tmp_path / "db") as store:
        assert store.get("a") == "1"
        assert store.get("b") == ""
        assert store.keys() == ["a", "b"]
    assert seg_files(tmp_path / "db") == ["000001.seg"]


def test_store_empty_value_is_not_deleted(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("k", "")
        assert store.keys() == ["k"]
        assert store.delete("k") is True
        assert store.get("k") is None
        assert store.keys() == []


def test_delete_noop_writes_nothing(tmp_path):
    with KVStore(tmp_path) as store:
        assert store.delete("missing") is False
        store.set("a", "1")
        assert store.delete("a") is True
        size = store.stats().bytes_on_disk
        assert store.delete("a") is False
        assert store.stats().bytes_on_disk == size


def test_keys_order_rewrite_moves_to_end(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        for k in "abcd":
            store.set(k, "v")
        store.set("b", "again")
        store.delete("c")
        assert store.keys() == ["a", "d", "b"]
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        assert store.keys() == ["a", "d", "b"]


def test_validation(tmp_path):
    with KVStore(tmp_path) as store:
        with pytest.raises(TypeError):
            store.set(b"a", "1")
        with pytest.raises(TypeError):
            store.set("a", b"1")
        with pytest.raises(TypeError):
            store.get(1)
        with pytest.raises(ValueError):
            store.set("", "1")
        with pytest.raises(ValueError):
            store.set("鍵" * 40000, "1")
        store.set("x" * 65535, "ok")
        assert store.get("x" * 65535) == "ok"
        assert store.stats().total_records == 1
    for bad in (15, "4096", 0):
        with pytest.raises(ValueError):
            KVStore(tmp_path / "other", max_segment_bytes=bad)


def test_closed_store_raises(tmp_path):
    store = KVStore(tmp_path)
    store.close()
    store.close()
    with pytest.raises(ValueError):
        store.get("a")
    with pytest.raises(ValueError):
        store.set("a", "b")


def test_rollover_boundaries(tmp_path):
    # each record "kN" -> "v" is 18 bytes
    with KVStore(tmp_path, max_segment_bytes=36) as store:
        store.set("k1", "v")
        store.set("k2", "v")  # exactly 36: fits
        assert seg_files(tmp_path) == ["000001.seg"]
        store.set("k3", "v")
        assert seg_files(tmp_path) == ["000001.seg", "000002.seg"]
        store.set("big", "x" * 100)  # segment 2 not empty -> new segment 3
        store.set("k4", "v")  # segment 3 holds oversized record -> segment 4
        assert seg_files(tmp_path)[-1] == "000004.seg"
        assert store.get("big") == "x" * 100


def test_oversized_record_in_empty_segment(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=16) as store:
        store.set("key", "a long value")
        assert seg_files(tmp_path) == ["000001.seg"]
        assert store.get("key") == "a long value"


def test_recovery_with_truncated_tail_then_write(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    path = tmp_path / "000001.seg"
    with open(path, "ab") as fh:
        fh.write(encode_record("b", "2")[:9])
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a"]
        st = store.stats()
        assert st.total_records == 1 and st.bytes_on_disk == 17 + 9
        store.set("c", "3")
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a", "c"]
        assert store.get("c") == "3"


def test_recovery_reports_corruption(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("b", "2")
    path = tmp_path / "000001.seg"
    data = bytearray(path.read_bytes())
    data[15] ^= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(CorruptSegmentError) as info:
        KVStore(tmp_path)
    assert info.value.offset == 0


def test_ignores_non_segment_files(tmp_path):
    (tmp_path / "000003.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "12.seg").write_bytes(b"junk")
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        assert store.stats().segment_count == 1
    assert seg_files(tmp_path) == ["000001.seg", "12.seg"]


def test_stats(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.set("a", "2")
        store.set("b", "1")
        store.delete("b")
        st = store.stats()
    assert isinstance(st, Stats)
    assert st == Stats(1, 1, 4, 2, 1, 17 * 3 + 16)


# --- compaction -------------------------------------------------------------

def test_compaction(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        for i in range(5):
            store.set(f"k{i}", "v")
        store.set("k1", "new")
        store.delete("k2")
        before = store.stats()
        order = store.keys()
        result = compact(store)
        assert isinstance(result, CompactionResult)
        assert result.segments_removed == before.segment_count
        assert result.records_written == 4
        assert result.records_dropped == before.total_records - 4
        after = store.stats()
        assert result.bytes_reclaimed == before.bytes_on_disk - after.bytes_on_disk
        assert store.keys() == order
        assert store.get("k1") == "new" and store.get("k2") is None
        assert after.tombstones == 0 and after.segment_count == 1
        new_name = f"{before.segment_count + 1:06d}.seg"
        assert seg_files(tmp_path) == [new_name]
        store.set("z", "1")
    with KVStore(tmp_path, max_segment_bytes=40) as store:
        assert store.keys() == order + ["z"]


def test_compaction_empty_store_keeps_segment(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
        store.delete("a")
        result = compact(store)
        assert result == CompactionResult(1, 0, 2, 33)
        assert seg_files(tmp_path) == ["000002.seg"]
        store.set("b", "2")
        assert store.get("b") == "2"


def test_crash_before_replace_keeps_old_state(tmp_path):
    with KVStore(tmp_path) as store:
        store.set("a", "1")
    (tmp_path / "000002.seg.tmp").write_bytes(encode_record("zz", "x"))
    with KVStore(tmp_path) as store:
        assert store.keys() == ["a"]


# --- CLI --------------------------------------------------------------------

def test_cli_round_trip(tmp_path, capsys):
    root = str(tmp_path / "data")
    assert main([root, "set", "a", "1"]) == 0
    assert capsys.readouterr().out == ""
    assert main([root, "get", "a"]) == 0
    assert capsys.readouterr().out == "1\n"
    assert main([root, "get", "zz"]) == 1
    assert capsys.readouterr().out == ""
    assert main([root, "list"]) == 0
    assert capsys.readouterr().out == "a\n"
    assert main([root, "stats"]) == 0
    assert capsys.readouterr().out == (
        "live_keys=1 tombstones=0 total_records=1 dead_records=0 "
        "segment_count=1 bytes_on_disk=17\n"
    )


def test_cli_delete_and_compact(tmp_path, capsys):
    root = str(tmp_path)
    main([root, "set", "a", "1"])
    main([root, "set", "b", "2"])
    assert main([root, "delete", "a"]) == 0
    assert main([root, "delete", "a"]) == 1
    capsys.readouterr()
    assert main([root, "compact"]) == 0
    assert capsys.readouterr().out == "removed=1 written=1 dropped=2 reclaimed=33\n"


def test_cli_usage_errors(tmp_path, capsys):
    root = str(tmp_path)
    for argv in ([root, "bogus"], [root, "get"], [root, "get", "a", "b"],
                 ["--max-segment-bytes", "0", root, "list"],
                 ["--max-segment-bytes", "abc", root, "list"], []):
        assert main(argv) == 2
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err != ""


def test_cli_value_errors_exit_2(tmp_path, capsys):
    assert main(["--max-segment-bytes", "10", str(tmp_path), "list"]) == 2
    assert main([str(tmp_path), "set", "x" * 70000, "v"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "error" in captured.err


def test_cli_corruption_exit_3(tmp_path, capsys):
    main([str(tmp_path), "set", "a", "1"])
    path = tmp_path / "000001.seg"
    path.write_bytes(b"BAD!" + path.read_bytes()[4:])
    assert main([str(tmp_path), "get", "a"]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "000001.seg" in captured.err


def test_cli_global_flag_rollover(tmp_path, capsys):
    root = str(tmp_path)
    main(["--max-segment-bytes", "20", root, "set", "a", "1"])
    main([root, "set", "b", "2", "--max-segment-bytes", "20"])
    main([root, "stats"])
    assert "segment_count=2" in capsys.readouterr().out


def test_python_m_kvstore_subprocess(tmp_path):
    root = str(tmp_path / "data")
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))
    run = lambda *a: subprocess.run(
        [sys.executable, "-m", "kvstore", root, *a],
        capture_output=True, text=True, env=env, cwd=PROJECT_ROOT,
    )
    assert run("set", "a", "1").returncode == 0
    got = run("get", "a")
    assert got.returncode == 0 and got.stdout.strip() == "1"
    missing = run("get", "zz")
    assert missing.returncode == 1 and missing.stdout == ""
    assert run("nope").returncode == 2
