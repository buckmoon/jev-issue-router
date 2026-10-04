"""Run the shared CLI with a freshly fetched public main catalog."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

CATALOG_URL = "https://raw.githubusercontent.com/buckmoon/jev-issue-router/main/issue_router/catalog.json"


def main():
    repository = Path(__file__).resolve().parents[3]
    executable = repository / ".venv" / "bin" / "issue-model"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        print(f"Router environment missing. Install the CLI in {repository}/.venv", file=sys.stderr)
        return 1
    # A caller cannot silently substitute an old catalog for the shared skill.
    if any(arg == "--catalog" or arg.startswith("--catalog=") for arg in sys.argv[1:]):
        print("The shared skill always uses the latest public main catalog.", file=sys.stderr)
        return 1
    try:
        request = urllib.request.Request(CATALOG_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=20) as response:
            catalog = json.loads(response.read(2_000_001))
        if not isinstance(catalog, dict) or not isinstance(catalog.get("models"), list):
            raise ValueError("Invalid catalog")
        with tempfile.TemporaryDirectory(prefix="jev-latest-catalog-") as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            return subprocess.call([str(executable), *sys.argv[1:], "--catalog", str(path)])
    except (OSError, ValueError):
        print("Latest catalog unavailable or invalid; evaluation stopped. No stale fallback.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
