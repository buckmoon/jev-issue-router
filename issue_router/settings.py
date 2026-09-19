"""Shared routing flags, with the same defaults across local, Slack and Actions."""
import os
from .core import load_catalog, RouterError
from .policies import POLICIES


def add_routing_arguments(parser):
    parser.add_argument("--catalog", default=os.getenv("ISSUE_MODEL_CATALOG"), help="Custom catalog JSON")
    parser.add_argument("--policy", choices=list(POLICIES),
                        default=os.getenv("ISSUE_MODEL_POLICY", "balanced"))
    parser.add_argument("--jev-model", default=os.getenv("JEV_MODEL", "jev-latest"))


def routing_options(args):
    if args.policy not in POLICIES:
        raise RouterError("ISSUE_MODEL_POLICY must be one of: " + ", ".join(POLICIES))
    if not args.jev_model.strip():
        raise RouterError("JEV_MODEL must not be empty")
    return {"catalog": load_catalog(args.catalog), "policy": args.policy, "jev_model": args.jev_model}
