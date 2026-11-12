"""Tk window: pick roots and destination, scan, tick rows, back up (and delete)."""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Sequence, Tuple

from . import __version__, system
from . import config as config_mod
from .config import Config
from .i18n import human_size, t
from .mover import COPIED, COPIED_NOT_DELETED, FAILED, LOG_NAME, MOVED, Item, Mover
from .scanner import Node, Scanner, collect

STATUS_KEYS = {MOVED: "st_moved", COPIED: "st_copied",
               COPIED_NOT_DELETED: "st_copied_not_deleted", FAILED: "st_failed"}
COLUMNS = [  # id, title key, width, anchor
    ("sel", None, 44, "center"), ("path", "col_path", 560, "w"), ("size", "col_size", 90, "e"),
    ("mtime", "col_modified", 115, "center"), ("atime", "col_accessed", 115, "center"),
    ("age", "col_age", 70, "e"), ("kind", "col_kind", 110, "w"), ("files", "col_files", 90, "e"),
]
ON, OFF = "☑", "☐"
GB = 1024 ** 3


def _date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if 0 < ts < 4e9 else "-"


def _int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class App:
    def __init__(self, cfg: Config, config_path: Optional[str] = None,
                 roots: Optional[Sequence[str]] = None, dest: Optional[str] = None,
                 autoscan: bool = False):
        self.cfg = cfg
        self.config_path = config_path
        if dest:
            cfg.destination = dest
        system.enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.title(f"{t('app_title')}   v{__version__}")
        self.root.geometry("1320x780")
        self.root.minsize(900, 480)
        self._icon()
        self._style()

        self.trees: List[Node] = []
        self.candidates: List[Node] = []
        self.selected: set = set()
        self.rows: Dict[str, Node] = {}
        self.job = None
        self.mode: Optional[str] = None
        self.sort_key, self.sort_desc = "size", True
        self.root_vars: List[Tuple[str, tk.BooleanVar]] = []
        self._refresh_after = None
        self._t0 = 0.0

        self._build(roots)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if autoscan:
            self.root.after(400, self.scan)

    # ================================================================ layout
    def _icon(self) -> None:
        assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        try:
            if system.IS_WIN:
                self.root.iconbitmap(default=os.path.join(assets, "dusty.ico"))
            else:
                self._icon_img = tk.PhotoImage(file=os.path.join(assets, "dusty.png"))
                self.root.iconphoto(True, self._icon_img)
        except (tk.TclError, OSError):
            pass

    def _style(self) -> None:
        st = ttk.Style(self.root)
        if "vista" in st.theme_names():
            st.theme_use("vista")
        f = tkfont.nametofont("TkDefaultFont")
        st.configure("Treeview", rowheight=int(f.metrics("linespace") * 1.55))
        st.configure("Accent.TButton", font=(f.actual("family"), f.actual("size"), "bold"))

    def _build(self, roots_override: Optional[Sequence[str]]) -> None:
        r = self.root
        pad = {"padx": 10, "pady": (8, 0)}
        lw = max(len(t(k)) for k in ("destination", "roots", "untouched")) + 1   # aligned first column

        row = ttk.Frame(r)
        row.pack(fill="x", **pad)
        ttk.Label(row, text=t("destination"), width=lw).pack(side="left")
        suggestions = system.suggested_destinations()
        self.dest_var = tk.StringVar(value=self.cfg.destination or (suggestions[0] if suggestions else ""))
        ttk.Combobox(row, textvariable=self.dest_var, values=suggestions).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text=t("browse"), command=self.browse_dest).pack(side="left")
        ttk.Button(row, text=t("settings"), command=self.open_settings).pack(side="left", padx=(6, 0))

        row = ttk.Frame(r)
        row.pack(fill="x", **pad)
        ttk.Label(row, text=t("roots"), width=lw).pack(side="left")
        self.roots_frame = ttk.Frame(row)
        self.roots_frame.pack(side="left", padx=4)
        ttk.Button(row, text=t("add_folder"), command=self.add_root).pack(side="left", padx=6)
        self._init_roots(roots_override)

        row = ttk.Frame(r)
        row.pack(fill="x", **pad)
        ttk.Label(row, text=t("untouched"), width=lw).pack(side="left")
        self.days_var = tk.StringVar(value=str(self.cfg.days))
        self.mb_var = tk.StringVar(value=f"{self.cfg.min_mb:g}")
        ttk.Spinbox(row, from_=1, to=10000, increment=30, width=7, textvariable=self.days_var).pack(
            side="left", padx=6)
        ttk.Label(row, text=t("days_bigger")).pack(side="left")
        ttk.Spinbox(row, from_=0, to=1_000_000, increment=10, width=8, textvariable=self.mb_var).pack(
            side="left", padx=6)
        ttk.Label(row, text=t("mb")).pack(side="left")
        self.atime_var = tk.BooleanVar(value=self.cfg.use_access_time)
        ttk.Checkbutton(row, text=t("use_atime"), variable=self.atime_var,
                        command=self._schedule_refresh).pack(side="left", padx=14)
        self.btn_scan = ttk.Button(row, text=t("scan"), style="Accent.TButton", command=self.scan)
        self.btn_scan.pack(side="left", padx=(4, 4))
        self.btn_stop = ttk.Button(row, text=t("stop"), state="disabled", command=self.stop)
        self.btn_stop.pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.filter_var, width=28).pack(side="right")
        ttk.Label(row, text=t("filter")).pack(side="right", padx=4)
        for v in (self.days_var, self.mb_var):
            v.trace_add("write", lambda *_: self._schedule_refresh())
        self.filter_var.trace_add("write", lambda *_: self.render())

        mid = ttk.Frame(r)
        mid.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree = ttk.Treeview(mid, columns=[c[0] for c in COLUMNS], show="headings", selectmode="extended")
        for cid, key, width, anchor in COLUMNS:
            self.tree.heading(cid, text=t(key) if key else "✓", command=lambda c=cid: self.sort_by(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=(cid == "path"))
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Button-3>", self._on_context)
        self.menu = tk.Menu(self.root, tearoff=False)

        bottom = ttk.Frame(r)
        bottom.pack(fill="x", padx=10)
        ttk.Button(bottom, text=t("select_all"), command=lambda: self.select_all(True)).pack(side="left")
        ttk.Button(bottom, text=t("select_none"), command=lambda: self.select_all(False)).pack(
            side="left", padx=6)
        self.sel_label = ttk.Label(bottom, text="")
        self.sel_label.pack(side="left", padx=12)
        self.btn_move = ttk.Button(bottom, style="Accent.TButton", command=self.move)
        self.btn_move.pack(side="right")
        self.delete_var = tk.BooleanVar(value=self.cfg.delete_after_copy)
        ttk.Checkbutton(bottom, text=t("delete_after"), variable=self.delete_var,
                        command=self._update_move_text).pack(side="right", padx=10)
        self._update_move_text()

        status = ttk.Frame(r)
        status.pack(fill="x", padx=10, pady=8)
        self.progress = ttk.Progressbar(status, length=280, maximum=1000)
        self.progress.pack(side="right")
        self.status = ttk.Label(status, text=t("hint"))
        self.status.pack(side="left", fill="x", expand=True)
        self._update_selection()

    def _init_roots(self, override: Optional[Sequence[str]]) -> None:
        drives = system.list_drives()
        labels = {system.norm(d.path): d.title for d in drives}
        cloud = {system.norm(d.path) for d in drives if d.cloud}
        paths: List[str] = [d.path for d in drives]
        paths += [p for p in self.cfg.custom_roots if os.path.isdir(p)]
        paths += [os.path.abspath(p) for p in (override or [])]
        chosen = {system.norm(p) for p in (override or self.cfg.roots)}
        seen = set()
        for p in paths:
            n = system.norm(p)
            if n in seen:
                continue
            seen.add(n)
            # first run: every local drive except cloud drives (the destination folder itself is
            # always excluded from scanning, so its drive can stay ticked)
            on = n in chosen if chosen else n not in cloud
            self._add_root_widget(p, labels.get(n, p), on)

    def _add_root_widget(self, path: str, text: str, on: bool) -> None:
        v = tk.BooleanVar(value=on)
        ttk.Checkbutton(self.roots_frame, text=text, variable=v).pack(side="left", padx=(0, 10))
        self.root_vars.append((path, v))

    def _update_move_text(self) -> None:
        self.btn_move.config(text=t("btn_move") if self.delete_var.get() else t("btn_copy"))

    # ============================================================ list view
    def _thresholds(self) -> Tuple[float, float]:
        try:
            days = max(1.0, float(self.days_var.get()))
        except ValueError:
            days = self.cfg.days
        try:
            mb = max(0.0, float(self.mb_var.get()))
        except ValueError:
            mb = self.cfg.min_mb
        return days, mb

    def _schedule_refresh(self) -> None:
        if self._refresh_after:
            self.root.after_cancel(self._refresh_after)
        self._refresh_after = self.root.after(250, self.refresh)

    def refresh(self) -> None:
        self._refresh_after = None
        if not self.trees or self.mode:
            return
        days, mb = self._thresholds()
        self.candidates = collect(self.trees, days, mb, self.atime_var.get())
        self.selected &= {c.path for c in self.candidates}
        self._sort()
        self.render()

    def _kind_text(self, n: Node) -> str:
        if n.kind == "file":
            return f"{t('kind_file')} {n.ext}".strip()
        return t(f"kind_{n.kind}")

    def _sort(self) -> None:
        use_atime = self.atime_var.get()
        keys = {
            "sel": lambda n: n.path in self.selected, "path": lambda n: n.path.lower(),
            "size": lambda n: n.size, "mtime": lambda n: n.mtime, "atime": lambda n: n.atime,
            "age": lambda n: -n.last_used(use_atime), "kind": lambda n: self._kind_text(n),
            "files": lambda n: n.files,
        }
        self.candidates.sort(key=keys[self.sort_key], reverse=self.sort_desc)

    def sort_by(self, key: str) -> None:
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key not in ("path", "kind")
        self._sort()
        self.render()

    def render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        needle = self.filter_var.get().strip().lower()
        now = time.time()
        use_atime = self.atime_var.get()
        for i, n in enumerate(self.candidates):
            if needle and needle not in n.path.lower():
                continue
            iid = str(i)
            self.rows[iid] = n
            self.tree.insert("", "end", iid=iid, values=(
                ON if n.path in self.selected else OFF, n.path, human_size(n.size), _date(n.mtime),
                _date(n.atime), int((now - n.last_used(use_atime)) // 86400), self._kind_text(n),
                _int(n.files)))
        self._update_selection()

    def _update_selection(self) -> None:
        sel = [c for c in self.candidates if c.path in self.selected]
        self.sel_label.config(text=t("selected", n=len(sel), size=human_size(sum(c.size for c in sel)),
                                     total_n=len(self.candidates),
                                     total_size=human_size(sum(c.size for c in self.candidates))))

    def toggle(self, iids: Sequence[str]) -> None:
        for iid in iids:
            n = self.rows.get(iid)
            if not n:
                continue
            if n.path in self.selected:
                self.selected.discard(n.path)
                self.tree.set(iid, "sel", OFF)
            else:
                self.selected.add(n.path)
                self.tree.set(iid, "sel", ON)
        self._update_selection()

    def select_all(self, on: bool) -> None:
        if self.mode:
            return
        visible = {n.path for n in self.rows.values()}
        self.selected = (self.selected | visible) if on else (self.selected - visible)
        self.render()

    def _on_click(self, ev):
        if self.mode:
            return None
        if self.tree.identify("region", ev.x, ev.y) == "cell" and self.tree.identify_column(ev.x) == "#1":
            iid = self.tree.identify_row(ev.y)
            if iid:
                self.toggle([iid])
                return "break"
        return None

    def _on_space(self, _ev):
        if not self.mode:
            self.toggle(self.tree.selection())
        return "break"

    def _on_double(self, ev):
        n = self.rows.get(self.tree.identify_row(ev.y))
        if n and os.path.exists(n.path):
            system.open_location(n.path)

    def _on_context(self, ev):
        iid = self.tree.identify_row(ev.y)
        n = self.rows.get(iid)
        if not n or self.mode:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        self.menu.delete(0, "end")
        self.menu.add_command(label=t("ctx_toggle"), command=lambda: self.toggle(self.tree.selection()))
        self.menu.add_command(label=t("ctx_open"), command=lambda: system.open_location(n.path))
        self.menu.add_separator()
        self.menu.add_command(label=t("ctx_exclude"), command=lambda: self.exclude(self.tree.selection()))
        self.menu.tk_popup(ev.x_root, ev.y_root)

    def exclude(self, iids: Sequence[str]) -> None:
        for iid in iids:
            n = self.rows.get(iid)
            if n:
                if n.path not in self.cfg.excludes:
                    self.cfg.excludes.append(n.path)
                n.removed = True
                self.selected.discard(n.path)
        self.save_config()
        self.refresh()

    # ============================================================== actions
    def browse_dest(self) -> None:
        p = filedialog.askdirectory(title=t("choose_dest"), initialdir=self.dest_var.get() or None)
        if p:
            self.dest_var.set(os.path.normpath(p))

    def add_root(self) -> None:
        p = filedialog.askdirectory(title=t("choose_root"))
        if not p:
            return
        p = os.path.normpath(p)
        if any(system.norm(p) == system.norm(q) for q, _ in self.root_vars):
            return
        self.cfg.custom_roots.append(p)
        self._add_root_widget(p, p, True)

    def _lock(self, mode: Optional[str]) -> None:
        self.mode = mode
        busy = mode is not None
        self.btn_scan.config(state="disabled" if busy else "normal")
        self.btn_move.config(state="disabled" if busy else "normal")
        self.btn_stop.config(state="normal" if busy else "disabled")

    def scan(self) -> None:
        if self.mode:
            return
        roots = [p for p, v in self.root_vars if v.get()]
        if not roots:
            messagebox.showwarning("dusty", t("need_root"))
            return
        self.save_config()
        dest = self.dest_var.get().strip()
        self.trees, self.candidates, self.selected = [], [], set()
        self.render()
        self.job = Scanner(roots, self.cfg, extra_excludes=[dest] if dest else [])
        self._t0 = time.time()
        threading.Thread(target=self.job.run, daemon=True).start()
        self._lock("scan")
        self.progress.config(mode="indeterminate")
        self.progress.start(15)
        self._poll()

    def stop(self) -> None:
        if self.job:
            self.job.cancel()

    def move(self) -> None:
        if self.mode:
            return
        chosen = [c for c in self.candidates if c.path in self.selected]
        if not chosen:
            messagebox.showinfo("dusty", t("no_selection"))
            return
        dest = self.dest_var.get().strip()
        if not dest:
            messagebox.showwarning("dusty", t("need_dest"))
            return
        dest = os.path.abspath(dest)
        if not os.path.isdir(dest) and not os.path.isdir(os.path.dirname(dest)):
            messagebox.showerror("dusty", t("dest_missing", p=os.path.dirname(dest)))
            return
        total = sum(c.size for c in chosen)
        free = system.free_space(dest)
        if free is not None and total > free:
            messagebox.showerror("dusty", t("no_space", need=human_size(total), free=human_size(free)))
            return
        warn = ""
        sysdrive = system.system_drive()
        sys_free = system.free_space(sysdrive)
        if sys_free is not None and not system.is_inside(dest, sysdrive) and total > sys_free - 10 * GB:
            warn = t("cache_warn", drive=sysdrive.rstrip("\\"), free=human_size(sys_free))
        delete = self.delete_var.get()
        text = t("confirm_head", n=len(chosen), size=human_size(total), dest=dest)
        if self.cfg.pack_small:
            text += t("confirm_pack", n=self.cfg.pack_min_files)
        text += t("confirm_delete") if delete else t("confirm_keep")
        if not messagebox.askyesno(t("confirm_title"), text + warn + t("proceed"),
                                   icon="warning" if delete else "question"):
            return
        self.save_config()
        items = [Item(c.path, c.is_dir, c.size, c.files) for c in sorted(chosen, key=lambda c: c.size)]
        cfg = self.cfg
        self.job = Mover(items, dest, delete=delete, verify=cfg.verify, workers=cfg.copy_workers,
                         pack=cfg.pack_small, pack_min_files=cfg.pack_min_files,
                         pack_max_avg_mb=cfg.pack_max_avg_mb)
        threading.Thread(target=self.job.run, daemon=True).start()
        self._lock("move")
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self._poll()

    def _poll(self) -> None:
        job = self.job
        if self.mode == "scan":
            if not job.done:
                cur = t("sizing") if not job.current else job.current
                self.status.config(text=t("scanning", n=_int(job.files_seen), cur=cur))
                self.root.after(200, self._poll)
                return
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self._lock(None)
            if job.error:
                messagebox.showerror("dusty", job.error)
            if job.cancelled:
                self.status.config(text=t("scan_stopped"))
                return
            self.trees = job.trees
            self.refresh()
            self.status.config(text=t("scan_done", n=_int(job.files_seen), s=job.elapsed,
                                      c=len(self.candidates)))
        elif self.mode == "move":
            self.progress.config(value=int(1000 * job.done_bytes / max(1, job.total_bytes)))
            if not job.done:
                phase = t({"delete": "phase_delete", "pack": "phase_pack"}.get(job.phase, "phase_copy"))
                self.status.config(text=t("progress", done=human_size(job.done_bytes),
                                          total=human_size(job.total_bytes), cur=f"{phase}: {job.current}"))
                self.root.after(250, self._poll)
                return
            self._lock(None)
            self._finish_move(job)

    def _finish_move(self, job: Mover) -> None:
        counts: Dict[str, int] = {}
        for c in self.candidates:
            status = job.results.get(c.path)
            if status:
                counts[status] = counts.get(status, 0) + 1
            if status == MOVED:
                c.removed = True
                self.selected.discard(c.path)
        self.candidates = [c for c in self.candidates if not c.removed]
        self.render()
        log = os.path.join(job.destination, LOG_NAME)
        lines = [f"{t(STATUS_KEYS[s])}: {n}" for s, n in counts.items()]
        skipped = len(job.items) - len(job.results)
        if skipped:
            lines.append(t("not_processed", n=skipped))
        failed = [p for p, s in job.results.items() if s in (FAILED, COPIED_NOT_DELETED)]
        for p in failed[:5]:
            lines.append(f"  • {p}\n    {job.notes.get(p, '')[:160]}")
        if job.error:
            lines.append(f"\n{t('error')}: {job.error}")
        self.status.config(text=t("finished", p=log))
        (messagebox.showwarning if failed or job.error else messagebox.showinfo)(
            "dusty", "\n".join(lines) + "\n\n" + t("details", p=log))

    # ============================================================ settings
    def open_settings(self) -> None:
        w = tk.Toplevel(self.root)
        w.title(t("settings_title"))
        w.transient(self.root)
        w.grab_set()
        frm = ttk.Frame(w, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=t("set_excludes")).grid(row=0, column=0, columnspan=2, sticky="w")
        txt = tk.Text(frm, width=80, height=10, font=tkfont.nametofont("TkFixedFont"))
        txt.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(4, 10))
        txt.insert("1.0", "\n".join(self.cfg.excludes))

        verify_opts = {"size": t("verify_size"), "hash": t("verify_hash")}
        ttk.Label(frm, text=t("set_verify")).grid(row=2, column=0, sticky="w")
        verify = ttk.Combobox(frm, state="readonly", values=list(verify_opts.values()), width=34)
        verify.set(verify_opts[self.cfg.verify])
        verify.grid(row=2, column=1, sticky="w", pady=2)

        ttk.Label(frm, text=t("set_depth")).grid(row=3, column=0, sticky="w")
        depth = tk.StringVar(value=str(self.cfg.max_depth))
        ttk.Spinbox(frm, from_=1, to=8, width=6, textvariable=depth).grid(row=3, column=1, sticky="w", pady=2)

        ttk.Label(frm, text=t("set_workers")).grid(row=4, column=0, sticky="w")
        workers = tk.StringVar(value=str(self.cfg.workers))
        ttk.Spinbox(frm, from_=1, to=32, width=6, textvariable=workers).grid(row=4, column=1, sticky="w", pady=2)

        ttk.Label(frm, text=t("set_copy_workers")).grid(row=5, column=0, sticky="w")
        copy_workers = tk.StringVar(value=str(self.cfg.copy_workers))
        ttk.Spinbox(frm, from_=1, to=32, width=6, textvariable=copy_workers).grid(
            row=5, column=1, sticky="w", pady=2)

        pack = tk.BooleanVar(value=self.cfg.pack_small)
        ttk.Checkbutton(frm, text=t("set_pack"), variable=pack).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(8, 2))
        ttk.Label(frm, text=t("set_pack_min")).grid(row=7, column=0, sticky="w", padx=(22, 0))
        pack_min = tk.StringVar(value=str(self.cfg.pack_min_files))
        ttk.Spinbox(frm, from_=10, to=1_000_000, increment=50, width=8, textvariable=pack_min).grid(
            row=7, column=1, sticky="w", pady=2)

        ttk.Label(frm, text=t("set_lang")).grid(row=8, column=0, sticky="w")
        lang = ttk.Combobox(frm, state="readonly", values=["auto", "en", "tr"], width=8)
        lang.set(self.cfg.language)
        lang.grid(row=8, column=1, sticky="w", pady=(8, 2))

        ttk.Label(frm, text=t("set_config", p=self.config_path or config_mod.default_path()),
                  foreground="gray").grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))

        def save():
            self.cfg.excludes = [ln.strip() for ln in txt.get("1.0", "end").splitlines() if ln.strip()]
            self.cfg.verify = "hash" if verify.get() == verify_opts["hash"] else "size"
            try:
                self.cfg.max_depth = min(8, max(1, int(depth.get())))
                self.cfg.workers = min(32, max(1, int(workers.get())))
                self.cfg.copy_workers = min(32, max(1, int(copy_workers.get())))
                self.cfg.pack_min_files = max(1, int(pack_min.get()))
            except ValueError:
                pass
            self.cfg.pack_small = pack.get()
            self.cfg.language = lang.get()
            for c in self.candidates:   # hide rows that are now protected
                if any(system.is_inside(c.path, e) or system.is_inside(e, c.path) for e in self.cfg.excludes):
                    c.removed = True
            self.save_config()
            w.destroy()
            self.refresh()

        btns = ttk.Frame(frm)
        btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text=t("cancel"), command=w.destroy).pack(side="right")
        ttk.Button(btns, text=t("save"), style="Accent.TButton", command=save).pack(side="right", padx=6)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(1, weight=1)

    def save_config(self) -> None:
        c = self.cfg
        c.destination = self.dest_var.get().strip()
        c.roots = [p for p, v in self.root_vars if v.get()]
        days, mb = self._thresholds()
        c.days, c.min_mb = int(days), mb
        c.use_access_time = self.atime_var.get()
        c.delete_after_copy = self.delete_var.get()
        try:
            config_mod.save(c, self.config_path)
        except OSError:
            pass

    def close(self) -> None:
        if self.mode:
            if not messagebox.askyesno("dusty", t("busy_close")):
                return
            self.job.cancel()

            def wait():
                if self.job.done:
                    self.save_config()
                    self.root.destroy()
                else:
                    self.root.after(200, wait)
            wait()
            return
        self.save_config()
        self.root.destroy()


def run(cfg: Config, config_path: Optional[str] = None, roots: Optional[Sequence[str]] = None,
        dest: Optional[str] = None, autoscan: bool = False) -> App:
    app = App(cfg, config_path, roots, dest, autoscan)
    probe = os.environ.get("DUSTY_SELFTEST")
    if probe:   # used by the release build: prove the packaged exe can open its window
        def done():
            with open(probe, "w", encoding="utf-8") as f:
                f.write(f"ok {app.root.title()}\n")
            app.root.destroy()
        app.root.after(1500, done)
    app.root.mainloop()
    return app


def main() -> int:
    """Entry point of the ``dusty-gui`` launcher (no console window on Windows)."""
    from .cli import main as cli_main

    return cli_main(["gui"])
