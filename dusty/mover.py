"""Copy → verify → delete, one item at a time.

Safety rules
------------
* An item is deleted only after **every** file in it was copied and verified (size, or SHA-256
  with ``verify="hash"``). One error and the original is left alone.
* Links (symlinks, junctions) are never followed. Inside a folder they are not copied, and
  deleting the folder removes only the link, never its target.
* Stopping halfway leaves the current item untouched. A rerun skips files already copied
  (same size and mtime), so an interrupted batch can simply be restarted.
* Each item gets one row in ``_dusty_log.csv`` in the destination folder.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import os
import shutil
import stat
from typing import Dict, List, Optional, Sequence

from . import system

LOG_NAME = "_dusty_log.csv"
CHUNK = 8 * 1024 * 1024

MOVED = "moved"                       # copied, verified, original deleted
COPIED = "copied"                     # copied and verified, original kept on purpose
COPIED_NOT_DELETED = "copied_not_deleted"   # copied and verified, but deleting failed
FAILED = "failed"                     # copy error → original kept


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
    """What to move. ``size`` is only used for progress."""

    def __init__(self, path: str, is_dir: bool, size: int = 0):
        self.path = path
        self.is_dir = is_dir
        self.size = size


class Mover:
    """Run :meth:`run` (blocking) in a thread; poll ``done_bytes`` / ``current`` / ``done``."""

    def __init__(self, items: Sequence[Item], destination: str, delete: bool = True,
                 verify: str = "size"):
        self.items = list(items)
        self.destination = os.path.abspath(destination)
        self.delete = delete
        self.verify = verify
        self.total_bytes = sum(i.size for i in self.items)
        self.done_bytes = 0
        self.current = ""
        self.phase = ""            # "copy" | "delete"
        self.cancelled = False
        self.done = False
        self.error: Optional[str] = None
        self.results: Dict[str, str] = {}
        self.notes: Dict[str, str] = {}

    def cancel(self) -> None:
        self.cancelled = True

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
                    if note:
                        self.notes[item.path] = note
                    w.writerow([dt.datetime.now().isoformat(timespec="seconds"), status, item.path,
                                target, item.size, note.replace("\n", " ")])
                    f.flush()
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.error = f"{type(e).__name__}: {e}"
        self.done = True

    def _process(self, item: Item):
        target = dest_path(self.destination, item.path)
        if system.is_inside(self.destination, item.path) or system.is_inside(item.path, self.destination):
            return FAILED, target, "destination and source overlap"
        if not os.path.lexists(item.path):
            return FAILED, target, "source not found"
        errors: List[str] = []
        self.phase, self.current = "copy", item.path
        try:
            if item.is_dir:
                self._copy_dir(system.long_path(item.path), system.long_path(target), errors)
            else:
                os.makedirs(system.long_path(os.path.dirname(target)), exist_ok=True)
                self._copy_file(system.long_path(item.path), system.long_path(target), errors)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
        if errors:
            return FAILED, target, f"{len(errors)} error(s): {errors[0]}"
        if not self.delete:
            return COPIED, target, ""
        self.phase = "delete"
        try:
            self._remove(system.long_path(item.path), item.is_dir)
        except Exception as e:  # noqa: BLE001
            return COPIED_NOT_DELETED, target, str(e)
        return MOVED, target, ""

    # ------------------------------------------------------------------ copy
    def _copy_dir(self, src: str, dst: str, errors: List[str]) -> None:
        os.makedirs(dst, exist_ok=True)
        try:
            with os.scandir(src) as it:
                entries = list(it)
        except OSError as e:
            errors.append(f"{system.short_path(src)}: {e}")
            return
        for e in entries:
            if self.cancelled:
                errors.append("cancelled")
                return
            try:
                st, is_dir, is_link, _ = system.entry_info(e)
            except OSError as x:
                errors.append(f"{system.short_path(e.path)}: {x}")
                continue
            target = os.path.join(dst, e.name)
            if is_link:
                if is_dir or os.path.isdir(e.path):
                    continue          # folder link: its content lives elsewhere and stays there
                self._copy_file(e.path, target, errors)   # file link: back up what it points to
            elif is_dir:
                self._copy_dir(e.path, target, errors)
            else:
                self._copy_file(e.path, target, errors)

    def _copy_file(self, src: str, dst: str, errors: List[str]) -> None:
        try:
            s = os.stat(src)
            if os.path.exists(dst):
                d = os.stat(dst)
                if d.st_size == s.st_size and abs(d.st_mtime - s.st_mtime) < 2 and (
                        self.verify != "hash" or _sha256(src) == _sha256(dst)):
                    self.done_bytes += s.st_size          # already backed up by an earlier run
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
                    self.done_bytes += len(chunk)
            if self.cancelled:
                os.remove(dst)
                errors.append("cancelled")
                return
            shutil.copystat(src, dst)
            if written != s.st_size or os.stat(dst).st_size != s.st_size:
                errors.append(f"size mismatch: {system.short_path(src)}")
            elif h and _sha256(dst) != h.hexdigest():
                errors.append(f"checksum mismatch: {system.short_path(src)}")
        except OSError as x:
            errors.append(f"{system.short_path(src)}: {x}")

    # ---------------------------------------------------------------- delete
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
