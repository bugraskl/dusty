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
