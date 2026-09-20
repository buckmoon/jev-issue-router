"""Bounded, metadata-only snapshot of a local Git repository. File contents are never read."""
from collections import Counter
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from .core import RouterError

MAX_FILES = 50000
MAX_RELATED = 20
MAX_COMMITS = 10
MAX_DEPTH = 4
MAX_DIRECTORIES = 80
TEXT_LIMIT = 100
MANIFESTS = {"pyproject.toml", "setup.py", "requirements.txt", "package.json", "go.mod", "Cargo.toml",
             "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json", "Package.swift",
             "pubspec.yaml", "mix.exs", "CMakeLists.txt", "Makefile", "Dockerfile"}
CI_MARKERS = (".github/workflows/", ".gitlab-ci.yml", ".circleci/", "Jenkinsfile", "azure-pipelines.yml",
              "bitbucket-pipelines.yml", ".buildkite/")
TEST_PATTERN = re.compile(r"(^|/)(tests?|spec|__tests__|e2e)(/|$)|(^|/)test_[^/]*$|[._-](test|spec)\.[^/]+$",
                          re.IGNORECASE)
MIGRATION_PATTERN = re.compile(r"(^|/)(migrations?|migrate)(/|$)", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")
# Common words that would match most paths and say nothing about the issue.
STOPWORDS = {"test", "tests", "spec", "src", "main", "index", "file", "files", "code", "with", "from",
             "this", "that", "should", "when", "update", "change", "https", "http", "github", "issue",
             "error", "data", "type", "types", "util", "utils", "docs", "readme", "config"}


def git(root, *args):
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        raise RouterError("Git unavailable or timed out while reading the repository") from None
    if proc.returncode:
        raise RouterError("Not a readable Git repository; supply the path of a local clone")
    return proc.stdout


def clip(text):
    text = " ".join(text.split())
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT - 1] + "…"


def related_paths(files, text):
    """Tracked paths whose own file or directory names appear in the issue text."""
    words = {w.lower() for w in WORD.findall(text)} - STOPWORDS
    if not words:
        return []
    scored = []
    for path in files:
        parts = PurePosixPath(path).parts
        names = {re.sub(r"\.[^.]+$", "", part).lower() for part in parts[-2:]}
        tokens = {t for name in names for t in [name, *re.split(r"[^a-z0-9]+", name)] if len(t) > 3}
        hits = len(tokens & words)
        if hits:
            scored.append((-hits, len(parts), path))
    return [path for _, _, path in sorted(scored)[:MAX_RELATED]]


def snapshot(path, issue_text=""):
    root = Path(path).expanduser()
    if not root.is_dir():
        raise RouterError("Repository path is not a directory")
    root = Path(git(root, "rev-parse", "--show-toplevel").strip())
    files = [f for f in git(root, "ls-files", "-z").split("\0") if f]
    if len(files) > MAX_FILES:
        raise RouterError(f"Repository has more than {MAX_FILES} tracked files; describe it in the context instead")
    extensions = Counter(PurePosixPath(f).suffix.lower() or "(none)" for f in files)
    top_level = Counter(f.split("/", 1)[0] + "/" if "/" in f else "(root files)" for f in files)
    # Directory names carry feature and layer names even when the issue shares no words with them.
    directories = Counter("/".join(PurePosixPath(f).parts[:depth]) + "/"
                          for f in files for depth in range(1, min(len(PurePosixPath(f).parts), MAX_DEPTH + 1)))
    manifests = sorted(f for f in files if PurePosixPath(f).name in MANIFESTS)
    status = [line for line in git(root, "status", "--porcelain").splitlines() if line]
    log = git(root, "log", f"-{MAX_COMMITS}", "--format=%cs %s") if git(root, "rev-list", "-n1", "--all").strip() else ""
    recent = git(root, "rev-list", "--count", "--since=90.days", "HEAD").strip() if log else "0"
    return {
        "collected": "Machine-collected metadata of a local Git checkout. File contents were not read.",
        "name": root.name,
        "branch": clip(git(root, "branch", "--show-current").strip() or "(detached)"),
        "tracked_files": len(files),
        "files_by_extension": dict(extensions.most_common(12)),
        "files_by_top_level": dict(top_level.most_common(20)),
        "files_by_directory": dict(directories.most_common(MAX_DIRECTORIES)),
        "manifests": manifests[:30],
        "manifest_count": len(manifests),
        "test_files": sum(bool(TEST_PATTERN.search(f)) for f in files),
        "has_ci": any(f.startswith(m) or f == m for f in files for m in CI_MARKERS),
        "has_migrations": any(MIGRATION_PATTERN.search(f) for f in files),
        "uncommitted_changes": len(status),
        "commits_last_90_days": int(recent or 0),
        "recent_commit_subjects": [clip(line) for line in log.splitlines()],
        "paths_matching_issue_terms": related_paths(files, issue_text),
    }
