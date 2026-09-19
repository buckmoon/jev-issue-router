"""Locate the shared checkout through the installed skill symlink and execute its CLI."""
import os
from pathlib import Path
import sys


def main():
    repository = Path(__file__).resolve().parents[3]
    executable = repository / ".venv" / "bin" / "issue-model"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        print(f"Router environment missing. Install the CLI in {repository}/.venv; see {repository}/docs/local.md",
              file=sys.stderr)
        return 1
    os.execv(str(executable), [str(executable), *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
