"""GitHub Actions entry point; configuration arrives via environment, never shell interpolation."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .core import RouterError, route, render
from .github import fetch_issue, publish_comment
from .settings import add_routing_arguments, routing_options


def run(environ=None, *, fetch=fetch_issue, select=route, publish=publish_comment):
    env = os.environ if environ is None else environ
    repo = env.get("ROUTER_REPOSITORY") or env.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise RouterError("Invalid repository; expected OWNER/REPO")
    number = env.get("ROUTER_ISSUE_NUMBER", "")
    if not re.fullmatch(r"[1-9][0-9]*", number):
        raise RouterError("Invalid issue number")
    post = env.get("ROUTER_POST_COMMENT", "false")
    if post not in ("true", "false"):
        raise RouterError("post-comment must be true or false")
    if not env.get("GITHUB_STEP_SUMMARY") or not env.get("GITHUB_OUTPUT"):
        raise RouterError("This entry point requires GitHub Actions summary/output files")
    parser = argparse.ArgumentParser()
    add_routing_arguments(parser)
    args = parser.parse_args([])
    args.policy = env.get("ISSUE_MODEL_POLICY") or "balanced"
    args.jev_model = env.get("JEV_MODEL") or "jev-latest"
    args.catalog = env.get("ISSUE_MODEL_CATALOG") or None
    options = routing_options(args)
    url = f"https://github.com/{repo}/issues/{number}"
    result = select(fetch(url), **options)
    report = f"対象: {url}\n\n" + render(result)
    with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write(report + "\n")
    directory = Path(tempfile.mkdtemp(prefix="jev-issue-router-", dir=env.get("RUNNER_TEMP")))
    result_path = directory / "result.json"
    report_path = directory / "report.md"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(report + "\n", encoding="utf-8")
    with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"status={result['status']}\nresult-path={result_path}\nreport-path={report_path}\n")
    if post == "true":
        publish(url, report)
    return result


def main():
    try:
        run()
        return 0
    except (RouterError, OSError, ValueError) as exc:
        print(str(exc) if isinstance(exc, RouterError) else "Action configuration/output error", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
