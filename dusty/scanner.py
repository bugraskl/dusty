"""Read-only scanner.

How it works
------------
1. The first ``max_depth`` levels below each root are listed one folder at a time. This builds a
   small tree of nodes; system folders, app data, hidden items and links are left out.
2. Below that depth, and for every *project* folder, the scanner does not keep a tree. It only
   needs totals (size, file count, newest modification and access time), so those subtrees are
   counted in a thread pool.
3. Totals are added up bottom-up.
4. :func:`collect` walks the finished tree and picks the **largest stale units**: a node becomes
   a candidate when everything inside it is older than the threshold and it is big enough. If
   so, its children are not listed. Otherwise the scanner looks inside it. Changing the
   thresholds only re-runs step 4, which is instant.

The scanner never opens file contents and never writes anything.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Optional

from . import system
from .config import Config

IN_USE = 4102444800.0        # 2100-01-01 — stamp for anything we could not read: "treat as in use"
LIST_FILES_FROM = 1024 * 1024  # loose files at least this big get their own node (1 MB)

# Node kinds that are structural and therefore never offered themselves
ROOT, FSROOT, USERS, PROFILE = "root", "fsroot", "users", "profile"


class Node:
    __slots__ = ("path", "depth", "is_dir", "size", "files", "mtime", "atime", "own_mtime",
                 "children", "eligible", "project", "kind", "ext", "removed", "_future")

    def __init__(self, path: str, depth: int, is_dir: bool):
        self.path = path
        self.depth = depth
        self.is_dir = is_dir
        self.size = 0
        self.files = 0
        self.mtime = 0.0
        self.atime = 0.0
        self.own_mtime = 0.0
        self.children: List[Node] = []
        self.eligible = False
        self.project = False
        self.kind: Optional[str] = None      # "project" | "program" | "folder" | "file"
        self.ext = ""
        self.removed = False
        self._future = None

    def last_used(self, use_access_time: bool) -> float:
        return max(self.mtime, self.atime) if use_access_time else self.mtime

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Node({self.path!r}, size={self.size}, files={self.files})"


class Scanner:
    """Run :meth:`run` (blocking) in a thread; poll ``files_seen`` / ``current`` / ``done``."""

    def __init__(self, roots: Iterable[str], cfg: Config, extra_excludes: Iterable[str] = ()):
        self.roots = [os.path.abspath(r) for r in roots]
        self.cfg = cfg
        self.cancelled = False
        self.files_seen = 0
        self.current = ""
        self.trees: List[Node] = []
        self.done = False
        self.error: Optional[str] = None
        self.elapsed = 0.0
        self._now = time.time()
        self._excludes = [system.norm(p) for p in list(cfg.excludes) + list(extra_excludes) if p]
        self._system = {n.lower() for n in cfg.system_names}
        self._users_skip = {n.lower() for n in cfg.users_skip}
        self._profile_skip = {n.lower() for n in cfg.profile_skip}
        self._markers = list(cfg.project_markers)
        self._code_ext = tuple(e.lower() for e in cfg.code_extensions)
        self._max_depth = cfg.max_depth
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public
    def cancel(self) -> None:
        self.cancelled = True

    def run(self) -> None:
        t0 = time.time()
        try:
            with ThreadPoolExecutor(self.cfg.workers) as pool:
                self._pool = pool
                for r in self.roots:
                    if os.path.isdir(r) and not self._is_excluded(r):
                        self.trees.append(self._build(r, 0, self._root_kind(r), 0.0))
                self.current = ""
            for t in self.trees:
                self._total(t)
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.error = f"{type(e).__name__}: {e}"
        self.elapsed = time.time() - t0
        self.done = True

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _root_kind(path: str) -> str:
        if system.is_fs_root(path):
            return FSROOT
        if system.is_users_dir(path):
            return USERS
        if system.is_profile(path):
            return PROFILE
        return ROOT

    def _clamp(self, t: float) -> float:
        return t if t <= self._now + 86400 else 0.0     # ignore timestamps from the future

    def _is_excluded(self, path: str) -> bool:
        n = system.norm(path)
        return any(n == e or n.startswith(e.rstrip("\\/") + os.sep) for e in self._excludes)

    def _contains_excluded(self, path: str) -> bool:
        n = system.norm(path).rstrip("\\/") + os.sep
        return any(e.startswith(n) for e in self._excludes)

    def _is_project(self, path: str) -> bool:
        for m in self._markers:
            if os.path.exists(os.path.join(path, m)):
                return True
        try:
            with os.scandir(path) as it:
                return any(e.name.lower().endswith(self._code_ext) for e in it)
        except OSError:
            return False

    def _count(self, n: int) -> None:
        with self._lock:
            self.files_seen += n

    # ------------------------------------------------------------------- build
    def _build(self, path: str, depth: int, kind: Optional[str], own_mtime: float,
               parent_kind: Optional[str] = None) -> Node:
        node = Node(path, depth, True)
        node.own_mtime = own_mtime
        node.eligible = kind is None and not self._contains_excluded(path)
        if self.cancelled:
            node.mtime = node.atime = IN_USE
            return node
        # Shell folders such as Downloads / Desktop are never treated as one project.
        node.project = kind is None and parent_kind != PROFILE and self._is_project(path)
        if node.project or depth >= self._max_depth:
            node._future = self._pool.submit(self._measure, path)
            return node
        if depth <= 2:
            self.current = path
        try:
            with os.scandir(system.long_path(path)) as it:
                entries = list(it)
        except OSError:
            node.mtime = node.atime = IN_USE
            node.eligible = False
            return node

        files = 0
        for e in entries:
            try:
                st, is_dir, is_link, hidden = system.entry_info(e)
            except OSError:
                continue
            if is_link:
                continue
            child_path = system.short_path(e.path)
            name = e.name.lower()
            if is_dir:
                if self._is_excluded(child_path):
                    continue
                child_kind: Optional[str] = None
                if kind == FSROOT:
                    if hidden or name in self._system:
                        continue
                    if name in ("users", "home"):
                        child_kind = USERS
                elif kind == USERS:
                    if hidden or name in self._users_skip:
                        continue
                    child_kind = PROFILE
                elif kind == PROFILE:
                    if hidden or name.startswith((".", "onedrive")) or name in self._profile_skip:
                        continue
                child = self._build(child_path, depth + 1, child_kind, st.st_mtime, kind)
                if hidden:
                    child.eligible = False
                node.children.append(child)
            else:
                if kind == FSROOT:          # pagefile.sys, bootmgr… never touch drive-root files
                    continue
                files += 1
                mt, at = self._clamp(st.st_mtime), self._clamp(st.st_atime)
                node.size += st.st_size
                node.files += 1
                node.mtime = max(node.mtime, mt)
                node.atime = max(node.atime, at)
                if st.st_size >= LIST_FILES_FROM and kind not in (PROFILE, USERS) and not hidden:
                    f = Node(child_path, depth + 1, False)
                    f.size, f.files, f.mtime, f.atime = st.st_size, 1, mt, at
                    f.eligible = not self._is_excluded(child_path)
                    f.kind, f.ext = "file", os.path.splitext(e.name)[1].lower()
                    node.children.append(f)
        self._count(files)
        return node

    def _measure(self, path: str):
        """Totals of a whole subtree: (size, files, newest mtime, newest atime)."""
        size = files = 0
        mt = at = 0.0
        stack = [system.long_path(path)]
        while stack:
            if self.cancelled:
                return 0, 0, IN_USE, IN_USE
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    n = 0
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
                            n += 1
                            size += st.st_size
                            mt = max(mt, self._clamp(st.st_mtime))
                            at = max(at, self._clamp(st.st_atime))
                    files += n
                    self._count(n)
            except OSError:
                continue        # unreadable subfolder: skipped (it is also never deleted, see mover)
        return size, files, mt, at

    def _total(self, node: Node) -> None:
        if node._future is not None:
            node.size, node.files, node.mtime, node.atime = node._future.result()
            node._future = None
        else:
            for c in node.children:
                if c.is_dir:
                    self._total(c)
                    node.size += c.size
                    node.files += c.files
                    node.mtime = max(node.mtime, c.mtime)
                    node.atime = max(node.atime, c.atime)
        if node.files == 0:                 # empty folder: fall back to its own timestamp
            node.mtime = max(node.mtime, node.own_mtime)
            node.atime = max(node.atime, node.own_mtime)


def _is_program(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return any(e.name.lower().endswith(".exe") for e in it)
    except OSError:
        return False


def collect(trees: Iterable[Node], days: float, min_mb: float, use_access_time: bool = False,
            now: Optional[float] = None) -> List[Node]:
    """Largest non-overlapping stale units: untouched for ``days`` and at least ``min_mb`` big."""
    cutoff = (now or time.time()) - days * 86400
    min_bytes = min_mb * 1024 * 1024
    out: List[Node] = []

    def visit(n: Node) -> None:
        if n.removed:
            return
        if n.eligible and n.last_used(use_access_time) < cutoff and n.size >= min_bytes:
            if n.kind is None:
                n.kind = "project" if n.project else ("program" if _is_program(n.path) else "folder")
            out.append(n)
            return
        for c in n.children:
            visit(c)

    for t in trees:
        visit(t)
    return out
