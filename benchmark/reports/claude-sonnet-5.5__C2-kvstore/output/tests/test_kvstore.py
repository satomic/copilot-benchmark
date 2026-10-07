import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

import kvstore
from kvstore import (
    CorruptRecordError, CorruptSegmentError, IncompleteRecordError, Index, KVStore,
    Location, Segment, compact, decode_record, encode_record,
)
from kvstore.__main__ import main

ROOT = pathlib.Path(__file__).resolve().parent.parent


def seg_path(root, n=1):
    return pathlib.Path(root) / f"{n:06d}.seg"


# ---- record codec ----
def test_roundtrip():
    blob = encode_record("k", "v")
    assert decode_record(blob) == ("k", "v", len(blob))


def test_header_layout():
    blob = encode_record("ab", "xyz")
    assert blob[:4] == b"KVR1" and blob[4] == 0
    assert struct.unpack(">HII", blob[5:15]) == (2, 3, zlib.crc32(b"abxyz"))
    assert len(blob) == 20


def test_tombstone_vs_empty_value():
    t, e = encode_record("k", None), encode_record("k", "")
    assert len(t) == len(e) == 16
    assert t != e
    assert decode_record(t)[1] is None
    assert decode_record(e)[1] == ""


def test_unicode_roundtrip_and_offset():
    blob = b"junk" + encode_record("键", "值😀")
    assert decode_record(blob, 4)[:2] == ("键", "值😀")


def test_decode_incomplete():
    blob = encode_record("key", "value")
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:10])
    with pytest.raises(IncompleteRecordError):
        decode_record(blob[:-1])


def test_decode_bad_magic_flags_keylen():
    blob = bytearray(encode_record("k", "v"))
    bad = bytearray(blob); bad[0] = 0x58
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(bad))
    bad = bytearray(blob); bad[4] = 2
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(bad))
    bad = bytearray(blob); bad[5:7] = b"\x00\x00"
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(bad))


def test_decode_tombstone_with_value():
    blob = bytearray(encode_record("k", "v")); blob[4] = 1
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))


def test_decode_crc_and_utf8():
    blob = bytearray(encode_record("k", "v")); blob[-1] ^= 0xFF
    with pytest.raises(CorruptRecordError):
        decode_record(bytes(blob))
    kb, vb = b"k", b"\xff"
    raw = struct.pack(">4sBHII", b"KVR1", 0, 1, 1, zlib.crc32(kb + vb)) + kb + vb
    with pytest.raises(CorruptRecordError):
        decode_record(raw)


def test_errors_hierarchy():
    assert issubclass(IncompleteRecordError, kvstore.RecordError)
    assert issubclass(CorruptRecordError, kvstore.RecordError)
    assert issubclass(kvstore.RecordError, kvstore.KVStoreError)
    assert issubclass(CorruptSegmentError, kvstore.KVStoreError)
    assert not issubclass(CorruptSegmentError, kvstore.RecordError)


def test_all_exports():
    assert len(kvstore.__all__) == 14
    for name in kvstore.__all__:
        assert hasattr(kvstore, name)


# ---- segment ----
def test_segment_append_scan(tmp_path):
    seg = Segment(tmp_path / "000001.seg", 1)
    a = seg.append(encode_record("a", "1"))
    b = seg.append(encode_record("b", None))
    assert a == 0 and b == seg.size - len(encode_record("b", None))
    assert list(seg.scan()) == [("a", "1", a), ("b", None, b)]
    seg.close()


def test_segment_truncated_tail(tmp_path):
    p = tmp_path / "000001.seg"
    good = encode_record("a", "1")
    p.write_bytes(good + encode_record("b", "22")[:-1])
    seg = Segment(p, 1)
    assert list(seg.scan()) == [("a", "1", 0)]
    p.write_bytes(good + b"KVR1\x00")
    assert [r[0] for r in seg.scan()] == ["a"]
    seg.close()


def test_segment_crc_mismatch_last_record(tmp_path):
    p = tmp_path / "000001.seg"
    bad = bytearray(encode_record("b", "22")); bad[-1] ^= 1
    good = encode_record("a", "1")
    p.write_bytes(good + bytes(bad))
    seg = Segment(p, 1)
    with pytest.raises(CorruptSegmentError) as ei:
        list(seg.scan())
    assert ei.value.offset == len(good)
    assert ei.value.path == p
    assert "000001.seg" in str(ei.value) and str(len(good)) in str(ei.value)
    seg.close()


def test_segment_bad_magic_short_body_is_corrupt(tmp_path):
    p = tmp_path / "000001.seg"
    bad = bytearray(encode_record("a", "1234")); bad[0] = 0
    p.write_bytes(bytes(bad)[:-2])
    seg = Segment(p, 1)
    with pytest.raises(CorruptSegmentError):
        list(seg.scan())
    seg.close()


# ---- index ----
def test_index_basic_and_order():
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("b", Location(1, 20), tombstone=False)
    idx.put("a", Location(2, 0), tombstone=False)
    assert idx.live_keys() == ["b", "a"]
    assert idx.get("a") == Location(2, 0)
    assert len(idx) == 2


def test_index_tombstones():
    idx = Index()
    idx.put("a", Location(1, 0), tombstone=False)
    idx.put("a", Location(1, 20), tombstone=True)
    assert idx.get("a") is None and len(idx) == 0
    assert idx.tombstone_count() == 1 and idx.live_keys() == []
    idx.put("a", Location(1, 40), tombstone=False)
    assert idx.tombstone_count() == 0 and len(idx) == 1


# ---- store ----
def test_set_get_persist(tmp_path):
    with KVStore(tmp_path / "s") as s:
        s.set("a", "1")
        s.set("b", "")
        assert s.get("a") == "1" and s.get("b") == "" and s.get("c") is None
    with KVStore(tmp_path / "s") as s:
        assert s.get("a") == "1" and s.get("b") == ""


def test_delete_semantics(tmp_path):
    with KVStore(tmp_path) as s:
        assert s.delete("x") is False
        assert s.stats().total_records == 0
        s.set("x", "1")
        assert s.delete("x") is True
        size = s.stats().bytes_on_disk
        assert s.delete("x") is False
        assert s.stats().bytes_on_disk == size
        assert s.get("x") is None
    with KVStore(tmp_path) as s:
        assert s.get("x") is None and s.keys() == []


def test_empty_value_not_tombstone_after_reopen(tmp_path):
    with KVStore(tmp_path) as s:
        s.set("k", "")
    with KVStore(tmp_path) as s:
        assert s.get("k") == "" and s.stats().tombstones == 0


def test_keys_order_rewrite_moves_to_end(tmp_path):
    with KVStore(tmp_path) as s:
        for k in "abc":
            s.set(k, "1")
        s.set("a", "2")
        assert s.keys() == ["b", "c", "a"]
    with KVStore(tmp_path) as s:
        assert s.keys() == ["b", "c", "a"]


def test_validation(tmp_path):
    with KVStore(tmp_path) as s:
        with pytest.raises(TypeError):
            s.set(b"k", "v")
        with pytest.raises(TypeError):
            s.set("k", b"v")
        with pytest.raises(TypeError):
            s.set("k", None)
        with pytest.raises(ValueError):
            s.set("", "v")
        with pytest.raises(ValueError):
            s.set("字" * 40000, "v")
        s.set("a" * 65535, "v")
        with pytest.raises(ValueError):
            s.set("a" * 65536, "v")
        with pytest.raises(TypeError):
            s.get(b"k")
        with pytest.raises(TypeError):
            s.delete(1)
        assert s.stats().total_records == 1


@pytest.mark.parametrize("bad", [15, 0, -1, "16", 16.0])
def test_bad_max_segment_bytes(tmp_path, bad):
    with pytest.raises(ValueError):
        KVStore(tmp_path, max_segment_bytes=bad)


def test_closed_store(tmp_path):
    s = KVStore(tmp_path)
    s.close()
    s.close()
    for call in (lambda: s.set("a", "b"), lambda: s.get("a"), s.keys, s.stats):
        with pytest.raises(ValueError):
            call()


def test_rollover_boundaries(tmp_path):
    n = len(encode_record("a", "1"))  # 17
    with KVStore(tmp_path, max_segment_bytes=2 * n) as s:
        s.set("a", "1"); s.set("b", "1")
        assert s.stats().segment_count == 1
        s.set("c", "1")
        assert s.stats().segment_count == 2
    assert seg_path(tmp_path, 2).exists()


def test_oversized_record_in_empty_segment(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=16) as s:
        s.set("a", "x" * 100)
        assert s.stats().segment_count == 1
        s.set("b", "y")
        assert s.stats().segment_count == 2
        assert s.get("a") == "x" * 100


def test_ignores_other_files(tmp_path):
    (tmp_path / "000003.seg.tmp").write_bytes(b"garbage")
    (tmp_path / "notes.txt").write_bytes(b"garbage")
    (tmp_path / "1.seg").write_bytes(b"garbage")
    with KVStore(tmp_path) as s:
        s.set("a", "1")
        assert s.stats().segment_count == 1


def test_recovery_truncated_tail(tmp_path):
    with KVStore(tmp_path) as s:
        s.set("a", "1"); s.set("b", "2")
    p = seg_path(tmp_path)
    p.write_bytes(p.read_bytes() + encode_record("c", "3")[:-2])
    with KVStore(tmp_path) as s:
        assert s.keys() == ["a", "b"]
        st = s.stats()
        assert st.total_records == 2 and st.bytes_on_disk == p.stat().st_size


def test_recovery_corruption_raises(tmp_path):
    with KVStore(tmp_path) as s:
        s.set("a", "1")
    p = seg_path(tmp_path)
    raw = bytearray(p.read_bytes()); raw[-1] ^= 0xFF
    p.write_bytes(bytes(raw))
    with pytest.raises(CorruptSegmentError):
        KVStore(tmp_path)


def test_stats_counts(tmp_path):
    with KVStore(tmp_path) as s:
        s.set("a", "1"); s.set("a", "2"); s.set("b", "1"); s.delete("b"); s.set("c", "1")
        st = s.stats()
        assert (st.live_keys, st.tombstones, st.total_records, st.dead_records) == (2, 1, 5, 2)
        assert st.segment_count == 1 and st.bytes_on_disk == seg_path(tmp_path).stat().st_size


# ---- compaction ----
def test_compact_basic(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=40) as s:
        for k in "abcd":
            s.set(k, "1")
        s.set("a", "2"); s.delete("b")
        before = s.stats()
        order = s.keys()
        r = compact(s)
        after = s.stats()
        assert r.segments_removed == before.segment_count
        assert r.records_written == 3
        assert r.records_dropped == before.total_records - 3
        assert r.bytes_reclaimed == before.bytes_on_disk - after.bytes_on_disk
        assert s.keys() == order == ["c", "d", "a"]
        assert s.get("a") == "2" and s.get("b") is None
        assert (after.segment_count, after.tombstones, after.dead_records) == (1, 0, 0)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["000007.seg"] or \
        len(list(tmp_path.glob("*.seg"))) == 1


def test_compact_new_id_and_reopen(tmp_path):
    with KVStore(tmp_path, max_segment_bytes=20) as s:
        s.set("a", "1"); s.set("b", "2")
        compact(s)
        assert [p.name for p in tmp_path.glob("*.seg")] == ["000003.seg"]
        s.set("c", "3")
    with KVStore(tmp_path, max_segment_bytes=20) as s:
        assert s.keys() == ["a", "b", "c"]


def test_compact_empty_store(tmp_path):
    with KVStore(tmp_path) as s:
        s.set("a", "1"); s.delete("a")
        r = compact(s)
        assert r.records_written == 0 and r.records_dropped == 2
        assert s.stats().segment_count == 1
        s.set("b", "1")
    assert seg_path(tmp_path, 2).exists()


def test_compact_leftover_tmp_ignored(tmp_path):
    with KVStore(tmp_path) as s:
        s.set("a", "1")
    (tmp_path / "000002.seg.tmp").write_bytes(b"partial")
    with KVStore(tmp_path) as s:
        assert s.keys() == ["a"]
        compact(s)
        assert s.get("a") == "1"


# ---- CLI ----
def run_cli(capsys, root, *args):
    code = main([str(root), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_roundtrip(tmp_path, capsys):
    root = tmp_path / "d"
    assert run_cli(capsys, root, "set", "a", "1") == (0, "", "")
    assert run_cli(capsys, root, "get", "a") == (0, "1\n", "")
    assert run_cli(capsys, root, "get", "zz") == (1, "", "")
    assert run_cli(capsys, root, "list") == (0, "a\n", "")
    code, out, _ = run_cli(capsys, root, "stats")
    assert out == ("live_keys=1 tombstones=0 total_records=1 dead_records=0 "
                   "segment_count=1 bytes_on_disk=17\n")


def test_cli_delete_and_compact(tmp_path, capsys):
    root = tmp_path
    run_cli(capsys, root, "set", "a", "1")
    assert run_cli(capsys, root, "delete", "a")[0] == 0
    assert run_cli(capsys, root, "delete", "a") == (1, "", "")
    code, out, _ = run_cli(capsys, root, "compact")
    assert code == 0 and out.startswith("removed=1 written=0 dropped=2 reclaimed=")


def test_cli_usage_errors(tmp_path, capsys):
    assert run_cli(capsys, tmp_path, "bogus")[0] == 2
    assert run_cli(capsys, tmp_path, "set", "a")[0] == 2
    assert run_cli(capsys, tmp_path, "get", "a", "b")[0] == 2
    assert main([str(tmp_path), "--max-segment-bytes", "0", "list"]) == 2
    assert main(["--max-segment-bytes", "abc", str(tmp_path), "list"]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err


def test_cli_value_error_exit_2(tmp_path, capsys):
    code, out, err = run_cli(capsys, tmp_path, "set", "k" * 70000, "v")
    assert (code, out) == (2, "") and err
    assert main(["--max-segment-bytes", "8", str(tmp_path), "list"]) == 2


def test_cli_corrupt_exit_3(tmp_path, capsys):
    run_cli(capsys, tmp_path, "set", "a", "1")
    p = seg_path(tmp_path)
    raw = bytearray(p.read_bytes()); raw[-1] ^= 0xFF
    p.write_bytes(bytes(raw))
    code, out, err = run_cli(capsys, tmp_path, "get", "a")
    assert (code, out) == (3, "") and "000001.seg" in err


def test_cli_subprocess(tmp_path):
    def run(*a):
        return subprocess.run([sys.executable, "-m", "kvstore", str(tmp_path / "data"), *a],
                              cwd=ROOT, capture_output=True, text=True)
    assert run("set", "a", "1").returncode == 0
    r = run("get", "a")
    assert (r.returncode, r.stdout) == (0, "1\n")
    assert run("get", "zz").returncode == 1
