"""Command line: ``dusty`` (window) and ``dusty scan`` (read-only report)."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from typing import List, Optional

from . import __version__, i18n, system
from . import config as config_mod
from .scanner import Scanner, collect


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dusty",
        description="Find what has been gathering dust on your disks, back it up to cloud storage "
                    "and free up space. Without a command the window opens.")
    p.add_argument("--version", action="version", version=f"dusty {__version__}")
    p.add_argument("--config", metavar="FILE", help="settings file (default: %(default)s)",
                   default=config_mod.default_path())
    p.add_argument("--lang", choices=["auto", "en", "tr"], help="UI language")
    sub = p.add_subparsers(dest="command")

    g = sub.add_parser("gui", help="open the window (default)")
    g.add_argument("--root", action="append", metavar="PATH", help="pre-tick this drive/folder (repeatable)")
    g.add_argument("--dest", metavar="PATH", help="backup destination")
    g.add_argument("--scan", action="store_true", help="start scanning right away")

    s = sub.add_parser("scan", help="read-only scan; prints candidates and changes nothing")
    s.add_argument("--root", action="append", metavar="PATH",
                   help="drive or folder to scan (repeatable; default: all local drives)")
    s.add_argument("--days", type=float, help="untouched for at least this many days")
    s.add_argument("--min-mb", type=float, help="at least this big")
    s.add_argument("--access-time", action="store_true", help="also require 'not opened since'")
    s.add_argument("--exclude", action="append", default=[], metavar="PATH", help="never report this path")
    s.add_argument("--format", choices=["table", "json", "csv"], default="table")
    s.add_argument("--limit", type=int, default=0, help="show only the N biggest (table only)")
    s.add_argument("--quiet", action="store_true", help="no progress on stderr")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    cfg = config_mod.load(args.config)
    i18n.set_language(args.lang or cfg.language)
    if args.command == "scan":
        return _scan(cfg, args)
    from .gui import run

    run(cfg, args.config, roots=getattr(args, "root", None), dest=getattr(args, "dest", None),
        autoscan=getattr(args, "scan", False))
    return 0


def _scan(cfg, args) -> int:
    roots = args.root or [d.path for d in system.list_drives() if not d.cloud]
    days = args.days if args.days is not None else cfg.days
    min_mb = args.min_mb if args.min_mb is not None else cfg.min_mb
    use_atime = args.access_time or cfg.use_access_time
    sc = Scanner(roots, cfg, extra_excludes=args.exclude + ([cfg.destination] if cfg.destination else []))
    th = threading.Thread(target=sc.run, daemon=True)
    th.start()
    try:
        while th.is_alive():
            th.join(1.0)
            if not args.quiet:
                print(f"\r  {sc.files_seen:>12,} files  {sc.current[-60:]:<60}", end="", file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        sc.cancel()
        th.join()
        print("\ncancelled", file=sys.stderr)
        return 130
    if not args.quiet:
        print(f"\r  {sc.files_seen:,} files in {sc.elapsed:.0f}s".ljust(80), file=sys.stderr)
    if sc.error:
        print(f"error: {sc.error}", file=sys.stderr)
        return 1
    found = sorted(collect(sc.trees, days, min_mb, use_atime), key=lambda n: -n.size)
    rows = [{"path": n.path, "bytes": n.size, "files": n.files, "kind": n.kind + (n.ext and f" {n.ext}"),
             "modified": time.strftime("%Y-%m-%d", time.localtime(n.mtime)) if n.mtime else "",
             "opened": time.strftime("%Y-%m-%d", time.localtime(n.atime)) if n.atime else ""}
            for n in found]
    if args.format == "json":
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        print()
    elif args.format == "csv":
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]) if rows else ["path"])
        w.writeheader()
        w.writerows(rows)
    else:
        shown = rows[:args.limit] if args.limit else rows
        for r in shown:
            print(f"{i18n.human_size(r['bytes']):>9}  {r['modified']:>10}  {r['kind']:<14} {r['path']}")
        total = sum(r["bytes"] for r in rows)
        print(f"\n{len(rows)} candidates, {i18n.human_size(total)} "
              f"(untouched {days:g}+ days, {min_mb:g}+ MB{', not opened' if use_atime else ''})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
