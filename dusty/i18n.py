"""UI strings. Add a language by adding a dict with the same keys to ``STRINGS``."""
from __future__ import annotations

from . import system

STRINGS = {
    "en": {
        "app_title": "dusty — move what you no longer use to the cloud",
        "destination": "Back up to:",
        "browse": "Browse…",
        "settings": "Settings…",
        "roots": "Scan:",
        "add_folder": "+ Folder…",
        "untouched": "Untouched for",
        "days_bigger": "days, larger than",
        "mb": "MB",
        "use_atime": "Also require not opened (safer)",
        "scan": "Scan",
        "stop": "Stop",
        "filter": "Filter:",
        "col_path": "Path", "col_size": "Size", "col_modified": "Modified", "col_accessed": "Opened",
        "col_age": "Days", "col_kind": "Type", "col_files": "Files",
        "kind_project": "Project", "kind_program": "Program?", "kind_folder": "Folder", "kind_file": "File",
        "select_all": "Select all", "select_none": "Select none",
        "selected": "Selected: {n} items, {size}    (listed: {total_n} items, {total_size})",
        "delete_after": "Delete originals after a verified copy",
        "btn_move": "Back up and delete", "btn_copy": "Back up only",
        "hint": "Choose where to back up, then press Scan. Scanning never changes anything.",
        "scanning": "Scanning… {n} files — {cur}",
        "sizing": "Adding up folder sizes…",
        "scan_done": "{n} files scanned in {s:.0f}s — {c} candidates. Click ☐ to select (or Space). "
                     "Double-click opens, right-click for more.",
        "scan_stopped": "Scan stopped.",
        "error": "Error",
        "need_root": "Tick at least one place to scan.",
        "need_dest": "Choose a backup destination first.",
        "dest_missing": "The destination's parent folder does not exist:\n{p}\n\n"
                        "Is the drive connected / the sync app running?",
        "no_selection": "Tick some rows first (☐ column).",
        "no_space": "Not enough free space at the destination.\nNeeded: {need}\nFree: {free}",
        "cache_warn": "\n\nNote: sync apps (Google Drive, OneDrive…) usually cache files on {drive} "
                      "before uploading. This selection is close to or over its free space ({free}). "
                      "Smaller batches are safer.",
        "confirm_title": "Confirm",
        "confirm_head": "{n} items, {size} in total, will be copied to\n{dest}\n"
                        "(original paths are mirrored: …\\C\\Users\\…, …\\D\\…).\n\n",
        "confirm_delete": "After each item's copy is verified, the ORIGINAL IS DELETED PERMANENTLY "
                          "(not moved to the Recycle Bin). Items with any copy error are never deleted.",
        "confirm_keep": "Originals are kept.",
        "proceed": "\n\nContinue?",
        "progress": "{done} / {total} — {cur}",
        "phase_copy": "Copying", "phase_delete": "Deleting",
        "st_moved": "Backed up and deleted", "st_copied": "Backed up",
        "st_copied_not_deleted": "Backed up, could not delete", "st_failed": "Error, not deleted",
        "not_processed": "Not processed (stopped): {n}",
        "details": "Details: {p}",
        "finished": "Done. Log: {p}",
        "busy_close": "An operation is running. Stop it and close?\n(The item in progress is never deleted.)",
        "ctx_toggle": "Select / unselect", "ctx_open": "Open location", "ctx_exclude": "Never offer this again",
        "settings_title": "Settings",
        "set_excludes": "Never touch these paths (one per line, everything inside is protected too):",
        "set_verify": "Copy check:", "verify_size": "size (fast)", "verify_hash": "SHA-256 (thorough, slower)",
        "set_depth": "Deepest listing level:", "set_workers": "Scan threads:",
        "set_lang": "Language (after restart):", "set_config": "Config file: {p}",
        "save": "Save", "cancel": "Cancel",
        "choose_dest": "Choose the backup folder", "choose_root": "Add a folder to scan",
    },
    "tr": {
        "app_title": "dusty — kullanmadıklarını buluta taşı",
        "destination": "Yedek hedefi:",
        "browse": "Gözat…",
        "settings": "Ayarlar…",
        "roots": "Taranacak:",
        "add_folder": "+ Klasör…",
        "untouched": "Son",
        "days_bigger": "günde dokunulmamış,",
        "mb": "MB'tan büyük",
        "use_atime": "Açılmamış da olsun (daha temkinli)",
        "scan": "Tara",
        "stop": "Durdur",
        "filter": "Filtre:",
        "col_path": "Yol", "col_size": "Boyut", "col_modified": "Son değişiklik", "col_accessed": "Son açılma",
        "col_age": "Gün", "col_kind": "Tür", "col_files": "Dosya",
        "kind_project": "Proje", "kind_program": "Program?", "kind_folder": "Klasör", "kind_file": "Dosya",
        "select_all": "Tümünü seç", "select_none": "Seçimi kaldır",
        "selected": "Seçili: {n} öğe, {size}    (listede: {total_n} öğe, {total_size})",
        "delete_after": "Doğrulanmış kopyadan sonra orijinali sil",
        "btn_move": "Yedekle ve sil", "btn_copy": "Sadece yedekle",
        "hint": "Yedek hedefini seçip Tara'ya basın. Tarama hiçbir şeyi değiştirmez.",
        "scanning": "Taranıyor… {n} dosya — {cur}",
        "sizing": "Klasör boyutları toplanıyor…",
        "scan_done": "{n} dosya {s:.0f} sn'de tarandı — {c} aday. Seçmek için ☐'ye tıklayın (veya Boşluk). "
                     "Çift tık: aç, sağ tık: diğer.",
        "scan_stopped": "Tarama durduruldu.",
        "error": "Hata",
        "need_root": "Taranacak en az bir yer işaretleyin.",
        "need_dest": "Önce bir yedek hedefi seçin.",
        "dest_missing": "Hedefin üst klasörü yok:\n{p}\n\nSürücü bağlı mı / eşitleme uygulaması açık mı?",
        "no_selection": "Önce satır işaretleyin (☐ sütunu).",
        "no_space": "Hedefte yeterli boş yer yok.\nGereken: {need}\nBoş: {free}",
        "cache_warn": "\n\nNot: Eşitleme uygulamaları (Google Drive, OneDrive…) dosyaları yüklemeden önce "
                      "{drive} sürücüsünde önbelleğe alır. Bu seçim oradaki boş alana ({free}) yakın ya da "
                      "fazla. Daha küçük parçalar daha güvenli.",
        "confirm_title": "Onay",
        "confirm_head": "{n} öğe, toplam {size}\n{dest}\nkonumuna kopyalanacak "
                        "(orijinal yollar korunur: …\\C\\Users\\…, …\\D\\…).\n\n",
        "confirm_delete": "Her öğenin kopyası doğrulandıktan sonra ORİJİNALİ KALICI OLARAK SİLİNİR "
                          "(Geri Dönüşüm Kutusu'na gitmez). Kopyalamada hata olan öğe asla silinmez.",
        "confirm_keep": "Orijinaller silinmez.",
        "proceed": "\n\nDevam edilsin mi?",
        "progress": "{done} / {total} — {cur}",
        "phase_copy": "Kopyalanıyor", "phase_delete": "Siliniyor",
        "st_moved": "Yedeklendi ve silindi", "st_copied": "Yedeklendi",
        "st_copied_not_deleted": "Yedeklendi, silinemedi", "st_failed": "Hata, silinmedi",
        "not_processed": "İşlenmedi (durduruldu): {n}",
        "details": "Ayrıntı: {p}",
        "finished": "Bitti. Günlük: {p}",
        "busy_close": "İşlem sürüyor. Durdurup kapatılsın mı?\n(Yarım kalan öğe asla silinmez.)",
        "ctx_toggle": "Seç / kaldır", "ctx_open": "Konumu aç", "ctx_exclude": "Bunu bir daha önerme",
        "settings_title": "Ayarlar",
        "set_excludes": "Bu yollara asla dokunma (her satıra bir yol; içindekiler de korunur):",
        "set_verify": "Kopya kontrolü:", "verify_size": "boyut (hızlı)", "verify_hash": "SHA-256 (kesin, yavaş)",
        "set_depth": "En derin listeleme seviyesi:", "set_workers": "Tarama iş parçacığı:",
        "set_lang": "Dil (yeniden başlatınca):", "set_config": "Ayar dosyası: {p}",
        "save": "Kaydet", "cancel": "Vazgeç",
        "choose_dest": "Yedek klasörünü seçin", "choose_root": "Taranacak klasör ekleyin",
    },
}

_lang = "en"


def set_language(code: str) -> str:
    global _lang
    if code == "auto" or code not in STRINGS:
        code = system.ui_language()
    _lang = code if code in STRINGS else "en"
    return _lang


def t(key: str, **kw) -> str:
    s = STRINGS[_lang].get(key) or STRINGS["en"].get(key, key)
    return s.format(**kw) if kw else s


def human_size(b: float) -> str:
    for unit, factor in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2)):
        if b >= factor:
            return f"{b / factor:.1f} {unit}" if unit != "MB" else f"{b / factor:.0f} {unit}"
    return f"{b / 1024:.0f} KB"
