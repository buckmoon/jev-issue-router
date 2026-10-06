"""Shared routing flags, with the same defaults across local, Slack and Actions."""
import os
from .core import load_catalog, RouterError
from .evaluators import CLEF_HOSTS, EVALUATORS, make_evaluator
from .policies import POLICIES


def add_routing_arguments(parser):
    parser.add_argument("--catalog", default=os.getenv("ISSUE_MODEL_CATALOG"), help="Custom catalog JSON")
    parser.add_argument("--policy", choices=list(POLICIES),
                        default=os.getenv("ISSUE_MODEL_POLICY", "balanced"))
    parser.add_argument("--evaluator", choices=list(EVALUATORS), default=os.getenv("ISSUE_MODEL_EVALUATOR", "jev"),
                        help="Decision model that judges the issue: Jev (TypeSafe) or Clef (Cloudflare)")
    parser.add_argument("--jev-model", default=os.getenv("JEV_MODEL", "jev-latest"))
    parser.add_argument("--clef-host", choices=list(CLEF_HOSTS), default=os.getenv("CLEF_HOST", "workers-ai"),
                        help="Where Clef runs: Cloudflare Workers AI or a local System One server")
    parser.add_argument("--clef-model", default=os.getenv("CLEF_MODEL", "clef"),
                        help="Clef model for the selection stage (and the assessment stage unless overridden)")
    parser.add_argument("--clef-assess-model", default=os.getenv("CLEF_ASSESS_MODEL"),
                        help="Clef model for the assessment stage only, e.g. clef-flash")
    parser.add_argument("--clef-url", default=os.getenv("CLEF_URL"),
                        help="Local System One server (loopback http or https)")


def routing_options(args):
    if args.policy not in POLICIES:
        raise RouterError("ISSUE_MODEL_POLICY must be one of: " + ", ".join(POLICIES))
    # Non-secret settings are validated here; credentials are read on the first API call.
    evaluator = make_evaluator(args.evaluator, jev_model=args.jev_model, clef_host=args.clef_host,
                               clef_model=args.clef_model, clef_assess_model=args.clef_assess_model,
                               clef_url=args.clef_url)
    return {"catalog": load_catalog(args.catalog), "policy": args.policy, "evaluator": evaluator}
