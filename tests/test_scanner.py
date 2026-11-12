import os

from conftest import MB, make_file, make_link

from dusty.scanner import Scanner, collect


def scan(root, cfg, days=365, min_mb=1, atime=False, excludes=()):
    s = Scanner([str(root)], cfg, extra_excludes=excludes)
    s.run()
    assert s.error is None
    return {os.path.relpath(n.path, root): n for n in collect(s.trees, days, min_mb, atime)}


def test_stale_folder_is_one_row(tmp_path, cfg):
    make_file(tmp_path / "old" / "a.bin", 2 * MB, age_days=500)
    make_file(tmp_path / "old" / "sub" / "b.bin", 2 * MB, age_days=400)
    make_file(tmp_path / "fresh" / "c.bin", 2 * MB, age_days=1)
    found = scan(tmp_path, cfg)
    assert list(found) == ["old"]
    assert found["old"].size == 4 * MB
    assert found["old"].files == 2
    assert found["old"].kind == "folder"


def test_recent_file_splits_parent(tmp_path, cfg):
    make_file(tmp_path / "mixed" / "stale" / "x.bin", 3 * MB, age_days=800)
    make_file(tmp_path / "mixed" / "notes.txt", 10, age_days=2)
    found = scan(tmp_path, cfg)
    assert list(found) == [os.path.join("mixed", "stale")]


def test_big_loose_file_is_offered(tmp_path, cfg):
    make_file(tmp_path / "downloads" / "old.iso", 5 * MB, age_days=900)
    make_file(tmp_path / "downloads" / "today.txt", 10)
    found = scan(tmp_path, cfg)
    assert os.path.join("downloads", "old.iso") in found
    assert found[os.path.join("downloads", "old.iso")].kind == "file"


def test_project_is_never_split(tmp_path, cfg):
    make_file(tmp_path / "proj" / "data" / "images.bin", 5 * MB, age_days=700)
    make_file(tmp_path / "proj" / "main.py", 100, age_days=3)
    assert scan(tmp_path, cfg) == {}


def test_stale_project_is_offered_whole(tmp_path, cfg):
    make_file(tmp_path / "proj" / "data" / "images.bin", 5 * MB, age_days=700)
    make_file(tmp_path / "proj" / "package.json", 100, age_days=700)
    found = scan(tmp_path, cfg)
    assert list(found) == ["proj"]
    assert found["proj"].kind == "project"


def test_min_size_threshold(tmp_path, cfg):
    make_file(tmp_path / "tiny" / "a.txt", 1000, age_days=999)
    assert scan(tmp_path, cfg, min_mb=1) == {}
    assert list(scan(tmp_path, cfg, min_mb=0)) == ["tiny"]


def test_days_threshold(tmp_path, cfg):
    make_file(tmp_path / "half_year" / "a.bin", 2 * MB, age_days=200)
    assert scan(tmp_path, cfg, days=365) == {}
    assert list(scan(tmp_path, cfg, days=180)) == ["half_year"]


def test_access_time_makes_it_safer(tmp_path, cfg):
    make_file(tmp_path / "read_recently" / "a.bin", 2 * MB, age_days=600, opened_days=5)
    assert list(scan(tmp_path, cfg, atime=False)) == ["read_recently"]
    assert scan(tmp_path, cfg, atime=True) == {}


def test_excluded_path_and_its_parents_are_protected(tmp_path, cfg):
    make_file(tmp_path / "archive" / "keep" / "a.bin", 2 * MB, age_days=900)
    make_file(tmp_path / "archive" / "other" / "b.bin", 2 * MB, age_days=900)
    found = scan(tmp_path, cfg, excludes=[str(tmp_path / "archive" / "keep")])
    assert list(found) == [os.path.join("archive", "other")]


def test_config_excludes_are_used(tmp_path, cfg):
    make_file(tmp_path / "secret" / "a.bin", 2 * MB, age_days=900)
    cfg.excludes = [str(tmp_path / "secret")]
    assert scan(tmp_path, cfg) == {}


def test_links_are_not_followed(tmp_path, cfg):
    outside = tmp_path / "outside"
    make_file(outside / "big.bin", 5 * MB, age_days=900)
    root = tmp_path / "root"
    make_file(root / "folder" / "small.bin", 2 * MB, age_days=900)
    make_link(str(root / "folder" / "link"), str(outside))
    found = scan(root, cfg)
    assert list(found) == ["folder"]
    assert found["folder"].size == 2 * MB          # the 5 MB behind the link is not counted


def test_hidden_folder_is_not_offered(tmp_path, cfg):
    make_file(tmp_path / ".cache" / "a.bin", 2 * MB, age_days=900)
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(tmp_path / ".cache"), 0x2)
    assert ".cache" not in scan(tmp_path, cfg)


def test_deep_levels_are_aggregated(tmp_path, cfg):
    cfg.max_depth = 2
    make_file(tmp_path / "a" / "b" / "c" / "d" / "e.bin", 2 * MB, age_days=900)
    make_file(tmp_path / "a" / "fresh.txt", 10)
    found = scan(tmp_path, cfg)
    assert list(found) == [os.path.join("a", "b")]


def test_future_timestamps_are_ignored(tmp_path, cfg):
    make_file(tmp_path / "weird" / "a.bin", 2 * MB, age_days=900)
    make_file(tmp_path / "weird" / "b.bin", 10, age_days=-3650)   # 10 years in the future
    assert list(scan(tmp_path, cfg, min_mb=1)) == ["weird"]


def test_thresholds_can_change_without_rescan(tmp_path, cfg):
    make_file(tmp_path / "one" / "a.bin", 2 * MB, age_days=100)
    make_file(tmp_path / "two" / "b.bin", 2 * MB, age_days=400)
    s = Scanner([str(tmp_path)], cfg)
    s.run()
    assert len(collect(s.trees, 365, 1)) == 1
    assert len(collect(s.trees, 30, 1)) == 2
