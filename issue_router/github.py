import json
import re
import subprocess
from .core import RouterError, normalize_issue

ISSUE_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)/?")
COMMENT_MARKER = "<!-- jev-issue-router:v1 -->"


def parse_url(url):
    match = ISSUE_URL.fullmatch(url.strip())
    if not match:
        raise RouterError("Expected https://github.com/OWNER/REPO/issues/NUMBER")
    return match.group(1) + "/" + match.group(2), int(match.group(3))


def gh(args, payload=None):
    try:
        if args and args[0] == "api":
            args = ["api", "--hostname", "github.com", *args[1:]]
        proc = subprocess.run(["gh", *args], input=payload, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise RouterError("GitHub CLI unavailable or timed out") from None
    if proc.returncode:
        raise RouterError("GitHub request failed; check authentication, repository access and issue number")
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        raise RouterError("Invalid GitHub response") from None


def fetch_issue(url, allowed_repos=None):
    repo, number = parse_url(url)
    if allowed_repos is not None and repo.lower() not in {x.lower() for x in allowed_repos}:
        raise RouterError("Repository is not allowed")
    data = gh(["api", f"repos/{repo}/issues/{number}"])
    if not isinstance(data, dict) or not isinstance(data.get("title"), str):
        raise RouterError("Invalid GitHub Issue response")
    if "pull_request" in data:
        raise RouterError("Pull requests are not supported; supply an Issue")
    return normalize_issue({"title": data["title"], "body": data.get("body")})


def publish_comment(url, text, *, author="github-actions[bot]"):
    repo, number = parse_url(url)
    body = COMMENT_MARKER + "\n" + text
    pages = gh(["api", "--paginate", "--slurp", f"repos/{repo}/issues/{number}/comments?per_page=100"])
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise RouterError("Invalid GitHub comments response")
    existing = [c for page in pages for c in page if isinstance(c, dict)
                and c.get("user", {}).get("login") == author
                and (c.get("body") or "").startswith(COMMENT_MARKER)]
    if existing:
        return gh(["api", "--method", "PATCH", f"repos/{repo}/issues/comments/{existing[-1]['id']}", "--input", "-"],
                  json.dumps({"body": body}))
    return gh(["api", "--method", "POST", f"repos/{repo}/issues/{number}/comments", "--input", "-"],
              json.dumps({"body": body}))
