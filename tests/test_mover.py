import csv
import os
import stat

import pytest
from conftest import MB, make_file, make_link

from dusty.mover import COPIED, COPIED_NOT_DELETED, FAILED, LOG_NAME, MOVED, Item, Mover, dest_path


def run(items, dest, **kw):
    m = Mover(items, str(dest), **kw)
    m.run()
    assert m.error is None
    return m


def test_dest_path_mirrors_original():
    if os.name == "nt":
        assert dest_path(r"G:\Backup", r"C:\Users\me\Old") == r"G:\Backup\C\Users\me\Old"
        assert dest_path(r"G:\Backup", r"\\nas\share\x\y") == r"G:\Backup\UNC\nas\share\x\y"
    else:
        assert dest_path("/backup", "/home/me/old") == "/backup/home/me/old"


def test_move_folder(tmp_path):
    src = tmp_path / "src" / "old"
    make_file(src / "a.bin", MB)
    make_file(src / "sub" / "b.txt", 10)
    ro = make_file(src / "sub" / "readonly.bin", 1000)
    os.chmod(ro, stat.S_IREAD)
    (src / "empty").mkdir()
    dest = tmp_path / "backup"
    m = run([Item(str(src), True, MB + 1010)], dest)
    assert m.results[str(src)] == MOVED
    assert not src.exists()
    target = dest_path(str(dest), str(src))
    assert os.path.getsize(os.path.join(target, "a.bin")) == MB
    assert os.path.getsize(os.path.join(target, "sub", "readonly.bin")) == 1000
    assert os.path.isdir(os.path.join(target, "empty"))
    assert m.done_bytes == m.total_bytes


def test_move_single_file_keeps_mtime(tmp_path):
    f = make_file(tmp_path / "src" / "movie.mp4", 2 * MB, age_days=400)
    mtime = os.stat(f).st_mtime
    dest = tmp_path / "backup"
    m = run([Item(str(f), False, 2 * MB)], dest)
    assert m.results[str(f)] == MOVED
    copy = dest_path(str(dest), str(f))
    assert abs(os.stat(copy).st_mtime - mtime) < 2


def test_copy_only_keeps_original(tmp_path):
    src = tmp_path / "src" / "keep"
    make_file(src / "a.bin", 1000)
    m = run([Item(str(src), True, 1000)], tmp_path / "backup", delete=False)
    assert m.results[str(src)] == COPIED
    assert (src / "a.bin").exists()


def test_hash_verify(tmp_path):
    src = tmp_path / "src" / "h"
    make_file(src / "a.bin", 3 * MB)
    m = run([Item(str(src), True, 3 * MB)], tmp_path / "backup", verify="hash")
    assert m.results[str(src)] == MOVED


def test_copy_error_means_no_delete(tmp_path, monkeypatch):
    src = tmp_path / "src" / "x"
    make_file(src / "a.bin", 1000)
    monkeypatch.setattr(Mover, "_copy_file", lambda self, s, d, errors: errors.append("disk on fire"))
    m = run([Item(str(src), True, 1000)], tmp_path / "backup")
    assert m.results[str(src)] == FAILED
    assert "disk on fire" in m.notes[str(src)]
    assert (src / "a.bin").exists()


def test_delete_error_is_reported(tmp_path, monkeypatch):
    src = tmp_path / "src" / "x"
    make_file(src / "a.bin", 1000)

    def boom(self, path, is_dir):
        raise PermissionError("in use")
    monkeypatch.setattr(Mover, "_remove", boom)
    m = run([Item(str(src), True, 1000)], tmp_path / "backup")
    assert m.results[str(src)] == COPIED_NOT_DELETED


def test_link_target_is_never_touched(tmp_path):
    outside = tmp_path / "outside"
    make_file(outside / "precious.txt", 10)
    src = tmp_path / "src" / "old"
    make_file(src / "a.bin", 1000)
    make_link(str(src / "link"), str(outside))
    dest = tmp_path / "backup"
    m = run([Item(str(src), True, 1000)], dest)
    assert m.results[str(src)] == MOVED
    assert (outside / "precious.txt").exists()
    assert not os.path.exists(os.path.join(dest_path(str(dest), str(src)), "link", "precious.txt"))


def test_overlapping_destination_is_refused(tmp_path):
    src = tmp_path / "src"
    make_file(src / "a.bin", 1000)
    m = run([Item(str(src), True, 1000)], src / "backup")
    assert m.results[str(src)] == FAILED
    assert (src / "a.bin").exists()


def test_missing_source(tmp_path):
    m = run([Item(str(tmp_path / "nope"), True, 0)], tmp_path / "backup")
    assert m.results[str(tmp_path / "nope")] == FAILED


def test_rerun_skips_already_copied_files(tmp_path, monkeypatch):
    src = tmp_path / "src" / "resume"
    make_file(src / "a.bin", MB)
    dest = tmp_path / "backup"
    run([Item(str(src), True, MB)], dest, delete=False)
    opened = []
    real_open = open

    def spy(path, mode="r", *a, **k):
        if "w" in mode:
            opened.append(path)
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", spy)
    m = run([Item(str(src), True, MB)], dest, delete=False)
    assert m.results[str(src)] == COPIED
    assert not any(str(p).endswith("a.bin") for p in opened)


def test_cancel_before_start_processes_nothing(tmp_path):
    src = tmp_path / "src" / "c"
    make_file(src / "a.bin", 1000)
    m = Mover([Item(str(src), True, 1000)], str(tmp_path / "backup"))
    m.cancel()
    m.run()
    assert m.results == {}
    assert (src / "a.bin").exists()


def test_log_is_written(tmp_path):
    src = tmp_path / "src" / "logged"
    make_file(src / "a.bin", 1000)
    dest = tmp_path / "backup"
    run([Item(str(src), True, 1000)], dest)
    run([Item(str(tmp_path / "missing"), True, 0)], dest)
    with open(dest / LOG_NAME, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert rows[0][:3] == ["time", "status", "original"]
    assert [r[1] for r in rows[1:]] == [MOVED, FAILED]


def test_many_files_parallel(tmp_path):
    src = tmp_path / "src" / "many"
    for i in range(60):
        make_file(src / f"d{i % 7}" / f"f{i}.txt", 100 + i)
    dest = tmp_path / "backup"
    m = run([Item(str(src), True, 0)], dest, workers=8, pack=False)
    assert m.results[str(src)] == MOVED
    target = dest_path(str(dest), str(src))
    copied = [os.path.join(r, f) for r, _, fs in os.walk(target) for f in fs]
    assert len(copied) == 60


def test_small_files_are_packed_into_zip(tmp_path):
    import zipfile
    src = tmp_path / "src" / "node_stuff"
    for i in range(30):
        make_file(src / "lib" / f"m{i}.js", 500 + i, age_days=400)
    make_file(src / "img" / "logo.png", 2000)
    (src / "empty").mkdir()
    dest = tmp_path / "backup"
    m = run([Item(str(src), True, 0)], dest, pack_min_files=10)
    assert m.results[str(src)] == MOVED
    assert "packed 31 files" in m.notes[str(src)]
    target = dest_path(str(dest), str(src)) + ".zip"
    assert m.targets[str(src)] == target
    assert not os.path.exists(target + ".partial")
    with zipfile.ZipFile(target) as z:
        names = z.namelist()
        assert "node_stuff/lib/m0.js" in names
        assert "node_stuff/empty/" in names
        assert z.getinfo("node_stuff/img/logo.png").compress_type == zipfile.ZIP_STORED
        assert z.getinfo("node_stuff/lib/m0.js").file_size == 500
        assert z.testzip() is None
    assert not src.exists()


def test_few_or_big_files_are_not_packed(tmp_path):
    src = tmp_path / "src" / "videos"
    make_file(src / "a.mp4", 3 * MB)
    make_file(src / "b.mp4", 3 * MB)
    m = Mover([Item(str(src), True, 0)], str(tmp_path / "b"), pack_min_files=2, pack_max_avg_mb=1)
    assert not m.should_pack(Item(str(src), True, 0))
    assert not m.should_pack(Item(str(src), True, 6 * MB, 2))
    assert m.should_pack(Item(str(src), True, 1000, 2))


def test_pack_error_keeps_original(tmp_path, monkeypatch):
    import zipfile
    src = tmp_path / "src" / "p"
    for i in range(5):
        make_file(src / f"f{i}.txt", 100)

    def broken(self, *a, **k):
        raise OSError("drive vanished")
    monkeypatch.setattr(zipfile.ZipFile, "write", broken)
    dest = tmp_path / "backup"
    m = run([Item(str(src), True, 0)], dest, pack_min_files=2)
    assert m.results[str(src)] == FAILED
    assert (src / "f0.txt").exists()
    assert not os.path.exists(dest_path(str(dest), str(src)) + ".zip.partial")


def test_shell_files_may_differ(tmp_path, monkeypatch):
    src = tmp_path / "src" / "s"
    make_file(src / "desktop.ini", 100)
    make_file(src / "real.txt", 100)
    real_stat = os.stat

    def fake_stat(p, *a, **k):
        st = real_stat(p, *a, **k)
        if "backup" in str(p) and str(p).lower().endswith("desktop.ini"):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                                   999, st.st_atime, st.st_mtime, st.st_ctime))
        return st
    monkeypatch.setattr(os, "stat", fake_stat)
    m = run([Item(str(src), True, 200)], tmp_path / "backup", pack=False)
    assert m.results[str(src)] == MOVED


@pytest.mark.skipif(os.name != "nt", reason="Windows long paths")
def test_long_paths(tmp_path):
    deep = tmp_path / "src" / "long"
    p = deep
    for i in range(12):
        p = p / ("very_long_folder_name_" + str(i) * 4)
    from dusty.system import long_path
    os.makedirs(long_path(str(p)))
    with open(long_path(str(p / "f.txt")), "wb") as f:
        f.write(b"x" * 100)
    assert len(str(p / "f.txt")) > 260
    m = run([Item(str(deep), True, 100)], tmp_path / "b")
    assert m.results[str(deep)] == MOVED
    assert not deep.exists()
