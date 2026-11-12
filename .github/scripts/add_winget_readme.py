"""Add the `winget install bugraskl.dusty` line to README.md (idempotent).

Run by .github/workflows/winget-readme.yml once the winget-pkgs PR is merged.
Exits 0 with "changed" or "already there" on stdout; exits 1 if the anchors moved.
"""
import sys

PATH = "README.md"
CMD = "winget install bugraskl.dusty"

EN_ANCHOR = "and double-click it. There is no installer, and you don't need Python or admin rights.\n"
EN_LINE = ("\nOr install it with [winget](https://learn.microsoft.com/windows/package-manager/winget/), "
           f"which also lets you update it later: `{CMD}`\n")
TR_ANCHOR = "- **Python ile:**"
TR_LINE = f"- **winget ile:** `{CMD}` (güncellemek için: `winget upgrade bugraskl.dusty`)\n"


def main() -> int:
    with open(PATH, encoding="utf-8") as f:
        text = f.read()
    if CMD in text:
        print("already there")
        return 0
    if EN_ANCHOR not in text or TR_ANCHOR not in text:
        print("README anchors not found; add the winget line by hand", file=sys.stderr)
        return 1
    text = text.replace(EN_ANCHOR, EN_ANCHOR + EN_LINE, 1)
    text = text.replace(TR_ANCHOR, TR_LINE + TR_ANCHOR, 1)
    with open(PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
