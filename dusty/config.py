"""User settings, stored as JSON.

Location: ``%APPDATA%\\dusty\\config.json`` on Windows, ``$XDG_CONFIG_HOME/dusty/config.json``
(or ``~/.config/dusty/config.json``) elsewhere. Override with the ``DUSTY_CONFIG`` environment variable.
Unknown keys are ignored and values of the wrong type fall back to the default, so a hand-edited
file can never break the app.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from typing import List

# Top-level folders of a drive / filesystem root that are never scanned.
_WINDOWS_SYSTEM_NAMES = [
    "Windows", "Program Files", "Program Files (x86)", "ProgramData", "Recovery", "PerfLogs",
    "boot", "ESD", "Config.Msi", "OneDriveTemp", "$Recycle.Bin", "System Volume Information",
    "Documents and Settings", "$WINDOWS.~BT", "$Windows.~WS", "$GetCurrent", "$SysReset",
    "MSOCache", "inetpub", "Microsoft Shared", "Intel", "WindowsApps", "WpSystem",
]
_UNIX_SYSTEM_NAMES = [
    "bin", "boot", "dev", "etc", "lib", "lib32", "lib64", "libx32", "proc", "run", "sbin", "sys",
    "usr", "var", "opt", "snap", "tmp", "lost+found", "System", "Library", "Applications",
    "Volumes", "private", "cores",
]
DEFAULT_SYSTEM_NAMES = _WINDOWS_SYSTEM_NAMES if os.name == "nt" else _UNIX_SYSTEM_NAMES

# Children of the "Users" / "home" folder that are not real people.
DEFAULT_USERS_SKIP = ["Public", "Default", "Default User", "All Users", "defaultuser0", "Shared"]

# Inside a user profile: app data and shell folders. Names starting with "." and "OneDrive*"
# are always skipped too.
DEFAULT_PROFILE_SKIP = [
    "AppData", "Application Data", "Local Settings", "Favorites", "Links", "Contacts", "Searches",
    "Saved Games", "Cookies", "NetHood", "PrintHood", "Recent", "SendTo", "Start Menu", "Templates",
    "My Documents", "MicrosoftEdgeBackups", "IntelGraphicsProfiles", "Library",
]

# A folder containing one of these is a "project": it is offered as a whole or not at all.
DEFAULT_PROJECT_MARKERS = [
    ".git", ".hg", ".svn", "package.json", "pyproject.toml", "requirements.txt", "setup.py",
    "Cargo.toml", "go.mod", "composer.json", "CMakeLists.txt", "platformio.ini", "project.godot",
    "ProjectSettings", "Gemfile", "pom.xml", "build.gradle",
]

# ... and so is a folder with a source file directly inside it, so data folders that sit next to
# code are never split away from it.
DEFAULT_CODE_EXTENSIONS = [
    ".sln", ".csproj", ".uproject", ".py", ".ipynb", ".js", ".ts", ".tsx", ".jsx", ".php", ".cs",
    ".cpp", ".c", ".h", ".go", ".java", ".rs", ".rb", ".gd", ".vue", ".html", ".kt", ".swift",
    ".dart", ".lua", ".ino",
]


@dataclass
class Config:
    destination: str = ""                      # backup folder, e.g. "G:\\My Drive\\dusty-backup"
    roots: List[str] = field(default_factory=list)          # last ticked scan roots; empty = automatic
    custom_roots: List[str] = field(default_factory=list)   # extra folders added in the window
    days: int = 365                            # untouched for at least this many days
    min_mb: float = 50.0                       # and at least this big
    use_access_time: bool = False              # also require "not opened" (needs NTFS last-access)
    delete_after_copy: bool = True
    verify: str = "size"                       # "size" or "hash" (SHA-256)
    pack_small: bool = True                    # folders of many small files → one .zip (much faster)
    pack_min_files: int = 200                  # ... when they hold at least this many files
    pack_max_avg_mb: float = 4.0               # ... and the average file is smaller than this
    copy_workers: int = 8                      # files copied in parallel
    max_depth: int = 4                         # deepest level offered as a separate row
    workers: int = 8                           # scan threads
    language: str = "auto"                     # "auto", "en", "tr"
    excludes: List[str] = field(default_factory=list)       # never touched, including everything inside
    system_names: List[str] = field(default_factory=lambda: list(DEFAULT_SYSTEM_NAMES))
    users_skip: List[str] = field(default_factory=lambda: list(DEFAULT_USERS_SKIP))
    profile_skip: List[str] = field(default_factory=lambda: list(DEFAULT_PROFILE_SKIP))
    project_markers: List[str] = field(default_factory=lambda: list(DEFAULT_PROJECT_MARKERS))
    code_extensions: List[str] = field(default_factory=lambda: list(DEFAULT_CODE_EXTENSIONS))


def default_path() -> str:
    env = os.environ.get("DUSTY_CONFIG")
    if env:
        return env
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "dusty", "config.json")


def load(path: str | None = None) -> Config:
    path = path or default_path()
    cfg = Config()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    for fl in fields(Config):
        if fl.name not in data:
            continue
        value, default = data[fl.name], getattr(cfg, fl.name)
        if isinstance(default, bool):
            ok = isinstance(value, bool)
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            value = float(value) if ok else value
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif isinstance(default, list):
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        else:
            ok = isinstance(value, type(default))
        if ok:
            setattr(cfg, fl.name, value)
    if cfg.verify not in ("size", "hash"):
        cfg.verify = "size"
    cfg.days = max(1, cfg.days)
    cfg.max_depth = min(max(1, cfg.max_depth), 8)
    cfg.workers = min(max(1, cfg.workers), 32)
    cfg.copy_workers = min(max(1, cfg.copy_workers), 32)
    cfg.pack_min_files = max(1, cfg.pack_min_files)
    return cfg


def save(cfg: Config, path: str | None = None) -> None:
    path = path or default_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
