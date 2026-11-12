# Changelog

## 1.2.0: portable Windows exe

- **`dusty.exe`**: a single portable file with no installer, Python or admin rights needed. It is
  built, smoke-tested and published by GitHub Actions on every tag.
- Settings are kept next to the exe (`dusty-config.json`), so it runs from a USB stick.
- New app icon, and version details in the exe's file properties.
- Streaming cloud drives (Google Drive) are suggested before folders that keep a full local copy
  (OneDrive, Dropbox).
- On the first run every local drive is ticked. The destination folder itself is still never
  scanned.

## 1.1.0: much faster backups to cloud drives

- Folders with many small files are stored as one verified `.zip`. 1,500 small files to Google
  Drive: 98 s → 1.4 s.
- Other folders are copied 8 files at a time.
- A size change in `desktop.ini` / `Thumbs.db` (rewritten by sync clients) no longer blocks
  deleting a folder.

## 1.0.0: first release

- Parallel scanner that offers the largest untouched folders and files, keeps projects whole and
  never touches system folders or links.
- Copy → verify → delete with resume and a CSV log.
- English and Turkish window, read-only `dusty scan` command, JSON settings.
