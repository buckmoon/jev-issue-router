import argparse
import json
from pathlib import Path
import sys
from .core import RouterError, normalize_issue, route, render
from .github import fetch_issue
from .repo import snapshot
from .settings import add_routing_arguments, routing_options


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jev selects model/effort pairs for OpenAI, Claude and Grok")
    parser.add_argument("url", nargs="?", help="GitHub Issue URL (same as --issue)")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--issue", help="GitHub Issue URL; reads title and body only")
    source.add_argument("--file", help="Issue JSON {title, body, context}; '-' reads stdin")
    source.add_argument("--text", help="Plain Issue text; '-' reads stdin")
    parser.add_argument("--context", help="Explicit UTF-8 context file to send to Jev")
    parser.add_argument("--repo", metavar="PATH", help="Local Git clone; sends its metadata (structure, tests, CI, "
                        "Git state, matching paths) to Jev. File contents are not read")
    add_routing_arguments(parser)
    parser.add_argument("--format", choices=["text", "json", "slack"], default="text")
    parser.add_argument("--output", help="Write result to a UTF-8 file instead of stdout")
    args = parser.parse_args(argv)
    if sum(value is not None for value in (args.url, args.issue, args.file, args.text)) != 1:
        parser.error("Supply exactly one URL, --issue, --file or --text")
    try:
        options = routing_options(args)
        if args.url or args.issue:
            issue = fetch_issue(args.url or args.issue)
        elif args.text is not None:
            issue = {"body": sys.stdin.read() if args.text == "-" else args.text}
        else:
            issue = json.loads(sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8"))
        issue = normalize_issue(issue)
        if args.context:
            issue["context"] = Path(args.context).read_text(encoding="utf-8")
        if args.repo:
            options["repository"] = snapshot(args.repo, "\n".join(issue.values()))
        result = route(issue, **options)
        output = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else render(result, args.format == "slack")
        if args.output:
            Path(args.output).write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return 0
    except (RouterError, OSError, ValueError) as exc:
        # No raw external response bodies, issue content or secrets in errors.
        print(str(exc) if isinstance(exc, RouterError) else "Input/configuration error", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
