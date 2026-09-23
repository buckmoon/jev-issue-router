"""Compare the catalog with each provider's official model list and propose newly listed models.

New models are added disabled with placeholder guidance: model IDs come from the provider API, but
effort support, cost ordering and routing guidance need a reviewed decision before Jev may pick them.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

from .core import NoRedirect, PROVIDERS, RouterError, validate_catalog

PACKAGE = Path(__file__).resolve().parent
CATALOG = PACKAGE / "catalog.json"
WATCH = PACKAGE / "model_watch.json"
IOS_CATALOG = PACKAGE.parent / "ios" / "JevIssueRouter" / "Resources" / "catalog.json"
UNREVIEWED = "UNREVIEWED"
# Dated snapshots (gpt-x-2026-01-02, claude-x-20260102, gpt-4-0613) duplicate their alias.
SNAPSHOT = re.compile(r"-(\d{4}-\d{2}-\d{2}|\d{8}|\d{4})$")
ENDPOINTS = {
    "openai": ("https://api.openai.com/v1/models", "OPENAI_API_KEY"),
    "claude": ("https://api.anthropic.com/v1/models?limit=1000", "ANTHROPIC_API_KEY"),
    "grok": ("https://api.x.ai/v1/models", "XAI_API_KEY"),
}


def fetch_json(url, headers):
    request = urllib.request.Request(url, headers={**headers, "User-Agent": "jev-issue-router-model-watch"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RouterError(f"HTTP {exc.code}; response body omitted") from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise RouterError("network/timeout/JSON error") from None


def created(entry):
    """Creation time as a date, from Unix seconds (OpenAI, xAI) or RFC 3339 (Anthropic)."""
    value = entry.get("created", entry.get("created_at"))
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).date()
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError, OverflowError):
        return None


def list_models(provider, key, fetch=fetch_json):
    url, _ = ENDPOINTS[provider]
    if provider == "claude":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        headers = {"Authorization": "Bearer " + key}
    models, page = [], url
    for _ in range(20):
        data = fetch(page, headers)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise RouterError("unexpected model list format")
        models += [m for m in data["data"] if isinstance(m, dict) and isinstance(m.get("id"), str)]
        if provider != "claude" or not data.get("has_more") or not data.get("last_id"):
            return models
        page = url + "&after_id=" + urllib.request.quote(str(data["last_id"]))
    return models


def listed(catalog_id, ids):
    return catalog_id in ids or any(SNAPSHOT.sub("", i) == catalog_id for i in ids)


def compare(catalog, watch, listings):
    """listings: {provider: [model entries]} for providers that were checked successfully."""
    cutoff = dt.date.fromisoformat(catalog["verified_at"])
    known = {m["id"] for m in catalog["models"]} | set(watch.get("ignored", []))
    report = {}
    for provider, entries in listings.items():
        rules = watch["providers"][provider]
        include, exclude = re.compile(rules["include"]), rules.get("exclude") and re.compile(rules["exclude"])
        ids = {e["id"] for e in entries}
        new = []
        for entry in entries:
            model_id = entry["id"]
            day = created(entry)
            if (not include.search(model_id) or (exclude and exclude.search(model_id))
                    or SNAPSHOT.search(model_id) or model_id in known
                    or not re.fullmatch(r"[A-Za-z0-9.-]+", model_id)
                    # Models listed before the catalog was verified were already considered then.
                    or (day is not None and day < cutoff)):
                continue
            new.append({"id": model_id, "created": day.isoformat() if day else None})
        missing = [m["id"] for m in catalog["models"]
                   if m["provider"] == provider and m.get("enabled", True) and not listed(m["id"], ids)]
        report[provider] = {"new": sorted(new, key=lambda n: n["id"]), "missing": missing}
    return report


def apply(catalog, watch, report, today):
    """Append new models disabled; returns the updated catalog, or None when nothing changed."""
    added = [(p, n) for p, r in report.items() for n in r["new"]]
    if not added:
        return None
    catalog = json.loads(json.dumps(catalog))
    for provider, new in added:
        reference = [m for m in catalog["models"] if m["provider"] == provider and m.get("enabled", True)]
        catalog["models"].append({
            "id": new["id"], "provider": provider, "enabled": False,
            # Placeholder so the entry validates; review against the provider's effort documentation.
            "efforts": list(reference[-1]["efforts"]) if reference else [next(iter(catalog["effort_guidance"]))],
            "selection_guidance": f"{UNREVIEWED}: listed by the {provider} models API "
                                  f"(first seen {today}). Set efforts, guidance and cost order, then enable.",
            "sources": [watch["providers"][provider]["docs"]],
        })
    date, _, serial = catalog["version"].partition(".")
    serial = int(serial) + 1 if date == today and serial.isdigit() else 1
    catalog["version"] = f"{today}.{serial}"
    return validate_catalog(catalog)


def render_report(report, skipped, changed):
    lines = ["## モデルカタログの確認", ""]
    for provider in PROVIDERS:
        if provider in skipped:
            lines.append(f"- **{provider}**: 未確認（{skipped[provider]}）")
            continue
        result = report[provider]
        new = ", ".join(f"`{n['id']}`" for n in result["new"]) or "なし"
        lines.append(f"- **{provider}**: 新規 {new}")
        if result["missing"]:
            lines.append("  - 一覧に無い有効モデル: " + ", ".join(f"`{m}`" for m in result["missing"])
                         + "（廃止・アカウントの権限・一時的な欠落のいずれか。自動では無効化しません）")
    lines.append("")
    if changed:
        lines += ["新規モデルを **無効 (`enabled: false`)** でカタログに追加しました。Jevはまだ選びません。",
                  "",
                  "有効化する前に、公式資料で次を確認して編集してください:",
                  "- `efforts`: 同社の既存モデルからの仮コピーです。対応する推論設定に直す",
                  f"- `selection_guidance`: `{UNREVIEWED}` の仮文を位置づけの説明に置き換える",
                  "- 並び順: 各社のモデルを安い順（最後が最も高性能）に並べる。`min-cost` / `max-quality` が使います",
                  "- `sources` と `verified_at`: 実際に確認した資料と日付",
                  "- 不要なモデルは削除し、`issue_router/model_watch.json` の `ignored` に追加すると再提案されません"]
    else:
        lines.append("カタログの変更はありません。")
    return "\n".join(lines) + "\n"


def write_catalog(catalog, paths):
    text = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    for path in paths:
        if path.parent.is_dir():
            path.write_text(text, encoding="utf-8")


def main(argv=None, fetch=fetch_json, environ=None, today=None):
    parser = argparse.ArgumentParser(description="Check provider model lists against the model catalog")
    parser.add_argument("--write", action="store_true", help="Add newly listed models to the catalog, disabled")
    parser.add_argument("--summary", help="Append the Markdown report to this file (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    today = today or dt.date.today().isoformat()
    try:
        catalog = validate_catalog(json.loads(CATALOG.read_text(encoding="utf-8")))
        watch = json.loads(WATCH.read_text(encoding="utf-8"))
    except (OSError, ValueError, RouterError):
        print("Cannot read catalog.json or model_watch.json", file=sys.stderr)
        return 1
    listings, skipped = {}, {}
    for provider in PROVIDERS:
        key = env.get(ENDPOINTS[provider][1])
        if not key:
            skipped[provider] = ENDPOINTS[provider][1] + " 未設定"
            continue
        try:
            listings[provider] = list_models(provider, key, fetch)
        except RouterError as exc:  # never echo keys or response bodies
            skipped[provider] = str(exc)
    if not listings:
        print("No provider could be checked: " + "; ".join(f"{p}: {r}" for p, r in skipped.items()), file=sys.stderr)
        return 1
    report = compare(catalog, watch, listings)
    updated = apply(catalog, watch, report, today) if args.write else None
    if updated:
        write_catalog(updated, [CATALOG, IOS_CATALOG])
    text = render_report(report, skipped, bool(updated))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    print(json.dumps({"report": report, "skipped": skipped, "changed": bool(updated)}, ensure_ascii=False, indent=2)
          if args.json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
