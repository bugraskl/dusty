"""Entry point of the standalone dusty.exe (no arguments → the window)."""
import sys

from dusty.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["gui"]))
