"""Small OS helpers: file attributes, drives, cloud folders, paths. Windows first, POSIX safe."""
from __future__ import annotations

import os
import shutil
import stat
import string
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

IS_WIN = os.name == "nt"

if IS_WIN:
    _REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
    _DIRECTORY = stat.FILE_ATTRIBUTE_DIRECTORY
    _HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
    _READONLY = stat.FILE_ATTRIBUTE_READONLY


def entry_info(entry: os.DirEntry) -> Tuple[os.stat_result, bool, bool, bool]:
    """(lstat, is_dir, is_link, is_hidden) without following links.

    On Windows every reparse point counts as a link: symlinks, junctions, mount points and cloud
    placeholders. They are never followed, so nothing outside a folder is ever counted, copied or
    deleted through it.
    """
    st = entry.stat(follow_symlinks=False)
    if IS_WIN:
        a = st.st_file_attributes
        return st, bool(a & _DIRECTORY), bool(a & _REPARSE), bool(a & _HIDDEN)
    return st, stat.S_ISDIR(st.st_mode), stat.S_ISLNK(st.st_mode), entry.name.startswith(".")


def is_readonly(st: os.stat_result) -> bool:
    if IS_WIN:
        return bool(st.st_file_attributes & _READONLY)
    return not st.st_mode & stat.S_IWUSR


def long_path(p: str) -> str:
    """Add the \\\\?\\ prefix on Windows so paths longer than 260 characters work."""
    if not IS_WIN:
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def short_path(p: str) -> str:
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


def norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def is_inside(child: str, parent: str) -> bool:
    """True when ``child`` is ``parent`` or somewhere below it."""
    c, p = norm(child), norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def is_fs_root(p: str) -> bool:
    p = os.path.abspath(p)
    return os.path.dirname(p) == p


def is_users_dir(p: str) -> bool:
    p = os.path.abspath(p)
    return os.path.basename(p).lower() in ("users", "home") and is_fs_root(os.path.dirname(p))


def is_profile(p: str) -> bool:
    p = os.path.abspath(p)
    return norm(p) == norm(os.path.expanduser("~")) or is_users_dir(os.path.dirname(p))


@dataclass
class Drive:
    path: str
    label: str = ""
    cloud: bool = False

    @property
    def title(self) -> str:
        name = self.path.rstrip("\\") or self.path
        return f"{name} ({self.label})" if self.label else name


def _volume_label(root: str) -> str:
    import ctypes

    buf = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 261,
                                                      None, None, None, fs, 261)
    return buf.value if ok else ""


def _letters() -> List[Tuple[str, int]]:
    import ctypes

    k = ctypes.windll.kernel32
    mask = k.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask >> i & 1:
            root = f"{letter}:\\"
            out.append((root, k.GetDriveTypeW(ctypes.c_wchar_p(root))))
    return out


def list_drives() -> List[Drive]:
    """Local fixed drives on Windows; the home folder elsewhere."""
    if not IS_WIN:
        return [Drive(os.path.expanduser("~"))]
    drives = []
    for root, dtype in _letters():
        if dtype != 3:          # DRIVE_FIXED only: no USB sticks, DVDs or network shares
            continue
        try:
            label = _volume_label(root)
        except OSError:
            label = ""
        drives.append(Drive(root, label, "google drive" in label.lower()))
    return drives


def cloud_folders() -> List[str]:
    """Folders of sync clients found on this machine (Google Drive, OneDrive, Dropbox, iCloud…)."""
    found: List[str] = []
    home = os.path.expanduser("~")
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.environ.get(env)
        if v:
            found.append(v)
    for name in ("Google Drive", "My Drive", "Dropbox", "iCloudDrive", "iCloud Drive", "pCloud Drive",
                 "Box", "MEGA", "Nextcloud", "Yandex.Disk"):
        found.append(os.path.join(home, name))
    cs = os.path.join(home, "Library", "CloudStorage")     # macOS File Provider
    try:
        found += [e.path for e in os.scandir(cs) if e.is_dir()]
    except OSError:
        pass
    if IS_WIN:
        # Google Drive for desktop mounts a virtual drive (label "Google Drive") whose first folder
        # is "My Drive" in the user's language (Drive'ım, Meine Ablage, Mi unidad…).
        try:
            for root, _ in _letters():
                if "google drive" in _volume_label(root).lower():
                    for e in os.scandir(root):
                        if e.is_dir() and not e.name.startswith((".", "$")):
                            found.append(e.path)
        except OSError:
            pass
    out, seen = [], set()
    for f in found:
        if os.path.isdir(f) and norm(f) not in seen:
            seen.add(norm(f))
            out.append(f)
    return out


def suggested_destinations() -> List[str]:
    return [os.path.join(f, "dusty-backup") for f in cloud_folders()]


def free_space(path: str) -> Optional[int]:
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def system_drive() -> str:
    return (os.environ.get("SystemDrive", "C:") + "\\") if IS_WIN else "/"


def open_location(path: str) -> None:
    if IS_WIN:
        subprocess.Popen(f'explorer /select,"{path}"')
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) or path])


def enable_dpi_awareness() -> None:
    if not IS_WIN:
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - purely cosmetic
        pass


def ui_language() -> str:
    """Two-letter UI language of the user ("tr", "en", …)."""
    if IS_WIN:
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return {0x1F: "tr", 0x09: "en"}.get(lang_id, "en")
        except Exception:  # noqa: BLE001
            pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        v = os.environ.get(var)
        if v:
            return v[:2].lower()
    return "en"
