"""Build the standalone, no-install ``dist/dusty.exe`` with PyInstaller.

    pip install pyinstaller
    python packaging/build_exe.py

The exe bundles Python and Tk (~10 MB), starts in a second or two and needs nothing installed.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD = os.path.join(ROOT, "build")


def version() -> str:
    with open(os.path.join(ROOT, "dusty", "__init__.py"), encoding="utf-8") as f:
        return re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)


def version_file(ver: str) -> str:
    """Windows file properties (Details tab) for the exe."""
    nums = (ver.split(".") + ["0"] * 4)[:4]
    tup = ", ".join(str(int(re.sub(r"\D.*", "", n) or 0)) for n in nums)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'dusty'),
      StringStruct('FileDescription', 'dusty - back up what you no longer use and free up space'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'dusty'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'dusty.exe'),
      StringStruct('ProductName', 'dusty'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main() -> int:
    ver = version()
    sep = ";" if os.name == "nt" else ":"
    assets = os.path.join(ROOT, "dusty", "assets")
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "dusty",
        "--icon", os.path.join(assets, "dusty.ico"),
        "--add-data", f"{assets}{sep}dusty/assets",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", BUILD,
        "--specpath", BUILD,
        "--paths", ROOT,
    ]
    if os.name == "nt":
        cmd += ["--version-file", version_file(ver)]
    cmd.append(os.path.join(ROOT, "packaging", "dusty_entry.py"))
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = os.path.join(ROOT, "dist", "dusty.exe" if os.name == "nt" else "dusty")
    print(f"\nbuilt {exe}  ({os.path.getsize(exe) / 1024 / 1024:.1f} MB, v{ver})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
