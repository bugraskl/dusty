"""Copy → verify → delete, one item at a time.

Speed
-----
Cloud drives (Google Drive for desktop, OneDrive…) pay a fixed cost for *every file created*:
tens of milliseconds, whatever the file size. On Google Drive, 1,500 small files took 98 s to
copy one by one, 66 s with 8 parallel copies, and **1.4 s as a single zip**. So:

* A folder with many small files (``pack_min_files``+ files, average below ``pack_max_avg_mb``) is
  written as **one ``.zip``**: ``<backup>\\D\\Projects\\old-site.zip``. Already-compressed formats
  are stored, everything else uses fast deflate.
* Other folders are copied with ``workers`` files in parallel.

Safety rules
------------
* An item is deleted only after **everything** in it was written and verified. Copies are
  checked by size, or SHA-256 with ``verify="hash"``. A zip is reopened and every entry is
  CRC-checked and compared with the source sizes. One error and the original is left alone.
* Links (symlinks, junctions) are never followed. Folder links are not copied, and deleting
  the folder removes only the link, never its target.
* Stopping halfway leaves the current item untouched and removes its unfinished zip. A rerun
  skips files that were already copied (same size and mtime).
* Each item gets one row in ``_dusty_log.csv`` in the destination folder.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import os
import shutil
import stat
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Sequence, Tuple

from . import system

LOG_NAME = "_dusty_log.csv"
CHUNK = 8 * 1024 * 1024

MOVED = "moved"                       # backed up, verified, original deleted
COPIED = "copied"                     # backed up and verified, original kept on purpose
COPIED_NOT_DELETED = "copied_not_deleted"   # backed up and verified, but deleting failed
FAILED = "failed"                     # backup error → original kept

# Explorer / sync clients rewrite these on their own, so a size difference is not an error.
SHELL_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}

# Stored as-is inside zips: compressing them again costs time and saves nothing.
COMPRESSED_EXT = {
    ".zip", ".7z", ".rar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".cab", ".jar", ".apk", ".whl",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".avif", ".mp3", ".aac", ".m4a", ".ogg",
    ".opus", ".flac", ".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".pdf", ".docx",
    ".xlsx", ".pptx", ".odt", ".epub", ".iso", ".dmg", ".msi", ".woff", ".woff2",
}


def dest_path(dest_root: str, src: str) -> str:
    """Mirror the original location under the destination.

    ``C:\\Users\\me\\Old`` → ``<dest>\\C\\Users\\me\\Old``; ``\\\\nas\\share\\x`` → ``<dest>\\UNC\\nas\\share\\x``;
    ``/home/me/old`` → ``<dest>/home/me/old``.
    """
    src = os.path.abspath(src)
    drive, rest = os.path.splitdrive(src)
    rest = rest.lstrip("\\/")
    if drive.startswith(("\\\\", "//")):
        prefix = os.path.join("UNC", *[p for p in drive.replace("/", "\\").split("\\") if p])
    else:
        prefix = drive.rstrip(":")
    return os.path.join(dest_root, prefix, rest) if prefix else os.path.join(dest_root, rest)


class Item:
    """What to move. ``size`` and ``files`` come from the scan (0 = unknown)."""

    def __init__(self, path: str, is_dir: bool, size: int = 0, files: int = 0):
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.files = files


class Mover:
    """Run :meth:`run` (blocking) in a thread; poll ``done_bytes`` / ``current`` / ``done``."""

    def __init__(self, items: Sequence[Item], destination: str, delete: bool = True,
                 verify: str = "size", workers: int = 8, pack: bool = True,
                 pack_min_files: int = 200, pack_max_avg_mb: float = 4.0):
        self.items = list(items)
        self.destination = os.path.abspath(destination)
        self.delete = delete
        self.verify = verify
        self.workers = max(1, workers)
        self.pack = pack
        self.pack_min_files = max(1, pack_min_files)
        self.pack_max_avg = pack_max_avg_mb * 1024 * 1024
        self.total_bytes = sum(i.size for i in self.items)
        self.done_bytes = 0
        self.current = ""
        self.phase = ""            # "copy" | "pack" | "delete"
        self.cancelled = False
        self.done = False
        self.error: Optional[str] = None
        self.results: Dict[str, str] = {}
        self.targets: Dict[str, str] = {}
        self.notes: Dict[str, str] = {}
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self.cancelled = True

    def _progress(self, n: int) -> None:
        with self._lock:
            self.done_bytes += n

    # ------------------------------------------------------------------- run
    def run(self) -> None:
        try:
            os.makedirs(self.destination, exist_ok=True)
            log = os.path.join(self.destination, LOG_NAME)
            new = not os.path.exists(log)
            with open(log, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                if new:
                    w.writerow(["time", "status", "original", "backup", "bytes", "note"])
                for item in self.items:
                    if self.cancelled:
                        break
                    status, target, note = self._process(item)
                    self.results[item.path] = status
                    self.targets[item.path] = target
                    if note:
                        self.notes[item.path] = note
                    w.writerow([dt.datetime.now().isoformat(timespec="seconds"), status, item.path,
                                target, item.size, note.replace("\n", " ")])
                    f.flush()
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.error = f"{type(e).__name__}: {e}"
        self.done = True

    def should_pack(self, item: Item) -> bool:
        if not (self.pack and item.is_dir):
            return False
        files, size = item.files, item.size
        if not files:
            files, size = _count(item.path)
        return files >= self.pack_min_files and size / max(1, files) < self.pack_max_avg

    def _process(self, item: Item) -> Tuple[str, str, str]:
        packed = self.should_pack(item) if os.path.isdir(item.path) else False
        target = dest_path(self.destination, item.path) + (".zip" if packed else "")
        if system.is_inside(self.destination, item.path) or system.is_inside(item.path, self.destination):
            return FAILED, target, "destination and source overlap"
        if not os.path.lexists(item.path):
            return FAILED, target, "source not found"
        errors: List[str] = []
        note = ""
        self.current = item.path
        try:
            if packed:
                self.phase = "pack"
                n = self._pack(item.path, target, errors)
                note = f"packed {n} files into one zip"
            elif item.is_dir:
                self.phase = "copy"
                self._copy_dir(item.path, target, errors)
            else:
                self.phase = "copy"
                os.makedirs(system.long_path(os.path.dirname(target)), exist_ok=True)
                self._copy_file(system.long_path(item.path), system.long_path(target), errors)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")
        if errors:
            return FAILED, target, f"{len(errors)} error(s): {errors[0]}"
        if not self.delete:
            return COPIED, target, note
        self.phase = "delete"
        try:
            self._remove(system.long_path(item.path), item.is_dir)
        except Exception as e:  # noqa: BLE001
            return COPIED_NOT_DELETED, target, (note + "; " if note else "") + str(e)
        return MOVED, target, note

    # ------------------------------------------------------------- listing
    def _plan(self, src: str, rel: str, files: List[Tuple[str, str, int]], dirs: List[str],
              errors: List[str]) -> None:
        """Collect (source, relative path, size) of every file and every folder under ``src``."""
        dirs.append(rel)
        try:
            with os.scandir(src) as it:
                entries = list(it)
        except OSError as e:
            errors.append(f"{system.short_path(src)}: {e}")
            return
        for e in entries:
            try:
                st, is_dir, is_link, _ = system.entry_info(e)
            except OSError as x:
                errors.append(f"{system.short_path(e.path)}: {x}")
                continue
            r = os.path.join(rel, e.name) if rel else e.name
            if is_link:
                if is_dir or os.path.isdir(e.path):
                    continue          # folder link: its content lives elsewhere and stays there
                try:
                    files.append((e.path, r, os.stat(e.path).st_size))   # file link: back up its target
                except OSError as x:
                    errors.append(f"{system.short_path(e.path)}: {x}")
            elif is_dir:
                self._plan(e.path, r, files, dirs, errors)
            else:
                files.append((e.path, r, st.st_size))

    # ---------------------------------------------------------------- copy
    def _copy_dir(self, src: str, dst: str, errors: List[str]) -> None:
        files: List[Tuple[str, str, int]] = []
        dirs: List[str] = []
        self._plan(system.long_path(src), "", files, dirs, errors)
        if errors:
            return
        root = system.long_path(dst)
        for d in dirs:
            os.makedirs(os.path.join(root, d) if d else root, exist_ok=True)

        def one(job):
            if not self.cancelled:
                self._copy_file(job[0], os.path.join(root, job[1]), errors)

        if self.workers > 1 and len(files) > 1:
            with ThreadPoolExecutor(min(self.workers, len(files))) as ex:
                list(ex.map(one, files))
        else:
            for job in files:
                one(job)
        if self.cancelled:
            errors.append("cancelled")

    def _copy_file(self, src: str, dst: str, errors: List[str]) -> None:
        try:
            s = os.stat(src)
            if os.path.exists(dst):
                d = os.stat(dst)
                if d.st_size == s.st_size and abs(d.st_mtime - s.st_mtime) < 2 and (
                        self.verify != "hash" or _sha256(src) == _sha256(dst)):
                    self._progress(s.st_size)          # already backed up by an earlier run
                    return
                os.chmod(dst, stat.S_IWRITE | stat.S_IREAD)
            h = hashlib.sha256() if self.verify == "hash" else None
            written = 0
            with open(src, "rb") as fi, open(dst, "wb") as fo:
                while not self.cancelled:
                    chunk = fi.read(CHUNK)
                    if not chunk:
                        break
                    fo.write(chunk)
                    if h:
                        h.update(chunk)
                    written += len(chunk)
                    self._progress(len(chunk))
            if self.cancelled:
                os.remove(dst)
                errors.append("cancelled")
                return
            shutil.copystat(src, dst)
            if os.path.basename(src).lower() in SHELL_FILES:
                return
            if written != s.st_size or os.stat(dst).st_size != s.st_size:
                errors.append(f"size mismatch: {system.short_path(src)}")
            elif h and _sha256(dst) != h.hexdigest():
                errors.append(f"checksum mismatch: {system.short_path(src)}")
        except OSError as x:
            errors.append(f"{system.short_path(src)}: {x}")

    # ---------------------------------------------------------------- pack
    def _pack(self, src: str, target: str, errors: List[str]) -> int:
        """Write ``src`` as one zip (top folder included), verify it, then rename into place."""
        files: List[Tuple[str, str, int]] = []
        dirs: List[str] = []
        top = os.path.basename(os.path.normpath(src))
        self._plan(system.long_path(src), top, files, dirs, errors)
        if errors:
            return 0
        os.makedirs(system.long_path(os.path.dirname(target)), exist_ok=True)
        partial = system.long_path(target + ".partial")
        expected: Dict[str, int] = {}
        stream = None
        try:
            stream = _ForwardWriter(partial)
            with zipfile.ZipFile(stream, "w", allowZip64=True, strict_timestamps=False) as z:
                has_children = {os.path.dirname(r) for _, r, _ in files} | {os.path.dirname(d) for d in dirs}
                for d in dirs:
                    if d not in has_children:                     # keep empty folders
                        zi = zipfile.ZipInfo(d.replace(os.sep, "/") + "/")
                        zi.external_attr = (0o40775 << 16) | 0x10
                        z.writestr(zi, b"")
                for path, rel, size in files:
                    if self.cancelled:
                        raise _Cancelled
                    arc = rel.replace(os.sep, "/")
                    plain = os.path.splitext(rel)[1].lower() in COMPRESSED_EXT
                    z.write(path, arc, compress_type=zipfile.ZIP_STORED if plain else zipfile.ZIP_DEFLATED,
                            compresslevel=None if plain else 1)
                    expected[arc] = size
                    self._progress(size)
            stream.close()
            with zipfile.ZipFile(partial) as z:
                found = {i.filename: i.file_size for i in z.infolist() if not i.is_dir()}
                if found != expected:
                    errors.append("zip content does not match the source")
                bad = z.testzip()
                if bad:
                    errors.append(f"zip CRC error in {bad}")
        except _Cancelled:
            errors.append("cancelled")
        except (OSError, zipfile.BadZipFile, ValueError) as e:
            errors.append(f"zip: {e}")
        if stream is not None:
            stream.close()
        if errors:
            try:
                os.remove(partial)
            except OSError:
                pass
            return 0
        os.replace(partial, system.long_path(target))
        return len(files)

    # -------------------------------------------------------------- delete
    def _remove(self, path: str, is_dir: bool) -> None:
        if not is_dir:
            _make_writable(path)
            os.remove(path)
            return
        with os.scandir(path) as it:
            entries = list(it)
        for e in entries:
            st, e_dir, e_link, _ = system.entry_info(e)
            if e_link:
                # remove the link itself — never what it points to
                if e_dir or (system.IS_WIN and os.path.isdir(e.path)):
                    os.rmdir(e.path)
                else:
                    os.remove(e.path)
            elif e_dir:
                self._remove(e.path, True)
            else:
                if system.is_readonly(st):
                    _make_writable(e.path)
                os.remove(e.path)
        _make_writable(path)
        os.rmdir(path)


class _Cancelled(Exception):
    pass


class _ForwardWriter(io.RawIOBase):
    """Write-only, forward-only file with a 16 MB buffer.

    Because it is not seekable, :mod:`zipfile` writes data descriptors instead of seeking back to
    patch every entry header, so the file is written in a few large sequential chunks. On cloud
    drives that is ~5–15× faster than a normal file object (1,500 entries: 1 s instead of 4–15 s).
    """

    LIMIT = 16 * 1024 * 1024

    def __init__(self, path: str):
        super().__init__()
        self._f = open(path, "wb", buffering=0)
        self._buf = bytearray()
        self._pos = 0

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self._pos

    def write(self, b) -> int:
        self._buf += b
        self._pos += len(b)
        if len(self._buf) >= self.LIMIT:
            self._f.write(self._buf)
            self._buf.clear()
        return len(b)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if not self.closed:
            try:
                self._f.write(self._buf)
                self._buf.clear()
            finally:
                self._f.close()
        super().close()


def _count(path: str) -> Tuple[int, int]:
    files = size = 0
    stack = [system.long_path(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        st, is_dir, is_link, _ = system.entry_info(e)
                    except OSError:
                        continue
                    if is_link:
                        continue
                    if is_dir:
                        stack.append(e.path)
                    else:
                        files += 1
                        size += st.st_size
        except OSError:
            continue
    return files, size


def _make_writable(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | (stat.S_IEXEC if os.path.isdir(path) else 0))
    except OSError:
        pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()
