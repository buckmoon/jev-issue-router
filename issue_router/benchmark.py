"""Explicit live evaluation and offline summaries; never runs the recommended models."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

from .core import PROVIDERS, RUBRICS, RouterError, normalize_issue, route
from .settings import add_routing_arguments, routing_options


def load_cases(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not 1 <= len(data) <= 100:
        raise RouterError("Benchmark dataset must contain 1 to 100 cases")
    seen = set()
    for case in data:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", case["id"]) or case["id"] in seen):
            raise RouterError("Benchmark case IDs must be unique short ASCII identifiers")
        seen.add(case["id"])
        case["issue"] = normalize_issue(case.get("issue"))
        if "equivalence_group" in case and (
                not isinstance(case["equivalence_group"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", case["equivalence_group"])):
            raise RouterError("Invalid benchmark equivalence group")
        expected = case.get("expected_assessment", {})
        if (not isinstance(expected, dict)
                or any(k not in RUBRICS or not isinstance(v, str) or v not in RUBRICS[k]
                       for k, v in expected.items())):
            raise RouterError("Invalid benchmark assessment labels")
        expected = case.get("expected_recommendations", {})
        if not isinstance(expected, dict) or any(k not in PROVIDERS for k in expected):
            raise RouterError("Invalid benchmark recommendation labels")
        for pairs in expected.values():
            if (not isinstance(pairs, list) or not pairs
                    or any(not isinstance(p, dict) or set(p) != {"model", "effort"}
                           or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", v)
                                  for v in p.values()) for p in pairs)):
                raise RouterError("Recommendation labels must list acceptable {model, effort} pairs")
    return data


def pair(rec):
    if rec.get("status") != "selected":
        return "needs_context"
    return rec["model"] + "__" + rec["effort"]


def summarize(rows):
    """Concentration is descriptive; labeled agreement and order stability are distinct measures."""
    if not isinstance(rows, list) or not rows:
        raise RouterError("Benchmark results must contain non-empty rows")
    groups = defaultdict(list)
    for row in rows:
        result = row["result"]
        ev = result["evaluator"]
        signature = (result["policy_version"], result["catalog_version"], result["policy"],
                     ev["name"], ev["host"], json.dumps(ev["models"], sort_keys=True),
                     tuple(sorted({call["model"] for call in result["jev_calls"]
                                   if isinstance(call.get("model"), str)})))
        groups[signature].append(row)
    reports = []
    for signature, subset in groups.items():
        providers = {}
        assessment_labels = Counter()
        for row in subset:
            for axis, label in row.get("expected_assessment", {}).items():
                assessment_labels["labeled"] += 1
                assessment_labels["matched"] += row["result"]["assessment"][axis]["choice"] == label
        for provider in PROVIDERS:
            counts, models = Counter(), Counter()
            checked = disagreed = labeled = matched = 0
            equivalent = defaultdict(list)
            selected = held = absent = 0
            for row in subset:
                rec = row["result"]["recommendations"].get(provider)
                if rec:
                    value = pair(rec)
                    counts[value] += 1
                    if rec["status"] == "selected":
                        selected += 1
                        models[rec["model"]] += 1
                    else:
                        held += 1
                    check = rec.get("order_check")
                    if check:
                        checked += 1
                        disagreed += not check["consistent"]
                else:
                    absent += 1
                    value = "needs_context"
                expected = row.get("expected_recommendations", {}).get(provider)
                if expected:
                    labeled += 1
                    matched += bool(rec and rec.get("status") == "selected"
                                    and {"model": rec["model"], "effort": rec["effort"]} in expected)
                if row.get("equivalence_group"):
                    equivalent[row["equivalence_group"]].append(value)
            comparisons = [v for v in equivalent.values() if len(v) > 1]
            # Compare selected pairs only; abstentions must not inflate model concentration.
            selected_pairs = {k: v for k, v in counts.items() if k != "needs_context"}
            providers[provider] = {
                "selected": selected, "held": held, "not_evaluated": absent,
                "pair_counts": dict(counts), "model_counts": dict(models),
                "distinct_pairs": len(selected_pairs), "distinct_models": len(models),
                "dominant_pair_share": max(selected_pairs.values()) / selected if selected else None,
                "order_checked": checked, "order_disagreements": disagreed,
                "labeled": labeled, "matched": matched,
                "label_agreement": matched / labeled if labeled else None,
                "equivalence_groups": len(comparisons),
                "equivalence_disagreements": sum(len(set(v)) > 1 for v in comparisons),
            }
        tokens = sum(c.get("usage", {}).get("input_tokens", 0)
                     for row in subset for c in row["result"]["jev_calls"]
                     if isinstance(c.get("usage"), dict) and type(c["usage"].get("input_tokens")) is int)
        reports.append({
            "policy_version": signature[0], "catalog_version": signature[1], "policy": signature[2],
            "evaluator": subset[0]["result"]["evaluator"], "response_models": list(signature[6]),
            "runs": len(subset), "input_tokens": tokens,
            "assessment_labels": dict(assessment_labels), "providers": providers,
        })
    return reports


def run_cases(cases, *, repeat=1, options=None, call=None):
    if type(repeat) is not int or not 1 <= repeat <= 10:
        raise RouterError("Benchmark repeat must be between 1 and 10")
    rows = []
    for run in range(repeat):
        for case in cases:
            result = route(case["issue"], call=call, **(options or {}))
            # Input bodies and credentials are never copied into the report.
            rows.append({"id": case["id"], "run": run + 1,
                         "equivalence_group": case.get("equivalence_group"),
                         "expected_assessment": case.get("expected_assessment", {}),
                         "expected_recommendations": case.get("expected_recommendations", {}),
                         "result": result})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit router concentration, labels and option-order stability")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true",
                      help="Send dataset issue text to the selected evaluator; external hosts incur usage")
    mode.add_argument("--results", help="Summarize a saved benchmark JSON offline; makes no API calls")
    parser.add_argument("--dataset", help="JSON array of cases (required for --live)")
    parser.add_argument("--repeat", type=int, default=1, help="1 to 10 runs per case; more runs incur more usage")
    parser.add_argument("--output", help="Write JSON report to a file")
    add_routing_arguments(parser)
    args = parser.parse_args(argv)
    if args.live and not args.dataset:
        parser.error("--live requires --dataset")
    if args.results and (args.dataset or args.repeat != 1):
        parser.error("--dataset and --repeat apply only to --live")
    try:
        if args.results:
            report = json.loads(Path(args.results).read_text(encoding="utf-8"))
            rows = report["rows"]
        else:
            cases = load_cases(args.dataset)
            rows = run_cases(cases, repeat=args.repeat, options=routing_options(args))
            report = {"dataset_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
                      "rows": rows}
        report["summary"] = summarize(rows)
        report["limitations"] = [
            "Concentration or agreement does not prove correctness. A one-model catalog necessarily repeats the model.",
            "Labels are human routing hypotheses unless grounded in measured task outcomes; unlabeled precision is null.",
            "Order agreement is a sensitivity check, not independent proof or a success probability.",
            "No recommended model is executed; costs, completion and rework must be measured separately.",
        ]
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0
    except (RouterError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(str(exc) if isinstance(exc, RouterError) else
              "Benchmark input/configuration/evaluation error; input and response bodies omitted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
