import json
import os

from conftest import MB, make_file

from dusty import cli, config, i18n


def test_missing_file_gives_defaults(tmp_path):
    c = config.load(str(tmp_path / "nope.json"))
    assert c == config.Config()


def test_roundtrip(tmp_path):
    p = str(tmp_path / "c" / "config.json")
    c = config.Config(destination="X:\\backup", days=90, min_mb=12.5, excludes=["a", "b"])
    config.save(c, p)
    assert config.load(p) == c


def test_bad_values_fall_back(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"days": "lots", "verify": "maybe", "excludes": [1, 2], "min_mb": 5,
                             "unknown": True, "max_depth": 99}), encoding="utf-8")
    c = config.load(str(p))
    assert c.days == 365 and c.verify == "size" and c.excludes == []
    assert c.min_mb == 5.0 and c.max_depth == 8


def test_corrupt_file(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    assert config.load(str(p)) == config.Config()


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DUSTY_CONFIG", str(tmp_path / "x.json"))
    assert config.default_path() == str(tmp_path / "x.json")


def test_translations_have_same_keys():
    en = set(i18n.STRINGS["en"])
    for lang, table in i18n.STRINGS.items():
        assert set(table) == en, lang


def test_human_size():
    assert i18n.human_size(500) == "0 KB"
    assert i18n.human_size(5 * MB) == "5 MB"
    assert i18n.human_size(1.5 * 1024 ** 3) == "1.5 GB"


def test_cli_scan_json(tmp_path, capsys):
    make_file(tmp_path / "root" / "old" / "a.bin", 2 * MB, age_days=500)
    make_file(tmp_path / "root" / "new" / "b.bin", 2 * MB)
    rc = cli.main(["--config", str(tmp_path / "cfg.json"), "scan", "--root", str(tmp_path / "root"),
                   "--min-mb", "1", "--format", "json", "--quiet"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert [os.path.basename(r["path"]) for r in rows] == ["old"]
    assert rows[0]["bytes"] == 2 * MB


def test_cli_scan_table(tmp_path, capsys):
    make_file(tmp_path / "root" / "old" / "a.bin", 2 * MB, age_days=500)
    rc = cli.main(["--config", str(tmp_path / "cfg.json"), "scan", "--root", str(tmp_path / "root"),
                   "--min-mb", "1", "--quiet"])
    assert rc == 0
    assert "1 candidates" in capsys.readouterr().out
