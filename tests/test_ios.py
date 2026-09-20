"""The iOS app is a Swift port of the engine; these checks fail when the two drift apart."""
import json
from pathlib import Path
import re
import unittest

from issue_router.core import MAX_INPUT_CHARS, POLICY_VERSION, PROVIDERS, TOP_CANDIDATES
from issue_router.policies import ORDINAL_POLICIES, POLICIES, POLICY_DESCRIPTIONS, TOP_MODEL_POLICIES

IOS = Path(__file__).resolve().parent.parent / "ios" / "JevIssueRouter"


def source(name):
    return (IOS / name).read_text(encoding="utf-8")


class IOSPortTest(unittest.TestCase):
    def test_bundled_catalog_matches_engine_catalog(self):
        engine = Path(__file__).resolve().parent.parent / "issue_router" / "catalog.json"
        bundled = IOS / "Resources" / "catalog.json"
        self.assertEqual(json.loads(engine.read_text(encoding="utf-8")),
                         json.loads(bundled.read_text(encoding="utf-8")),
                         "Run ios/sync-catalog.sh after changing the catalog")

    def test_constants_match(self):
        router = source("Engine/Router.swift")
        self.assertIn(f'policyVersion = "{POLICY_VERSION}"', router)
        self.assertIn(f"maxInputChars = {MAX_INPUT_CHARS}", router)
        self.assertIn(f"topCandidates = {TOP_CANDIDATES}", router)
        catalog = source("Engine/Catalog.swift")
        self.assertIn('providers = [' + ", ".join(f'"{p}"' for p in PROVIDERS) + ']', catalog)

    def test_policies_match(self):
        swift = source("Engine/Policies.swift")
        names = re.search(r"static let names = \[(.*?)\]", swift, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', names), list(POLICIES))
        for policy in POLICIES:
            self.assertIn(f'"{policy}":', swift)
        for group, name in ((ORDINAL_POLICIES, "ordinal"), (TOP_MODEL_POLICIES, "topModel")):
            listed = re.search(rf"static let {name}: Set<String> = \[(.*?)\]", swift, re.S).group(1)
            self.assertEqual(set(re.findall(r'"([^"]+)"', listed)), set(group))
        for policy in POLICY_DESCRIPTIONS:
            self.assertIn(f'"{policy}":', swift)

    def test_rubric_options_match(self):
        from issue_router.core import CONTEXT_CHECKS, RUBRICS
        swift = source("Engine/Rubrics.swift")
        names = re.search(r"static let names = \[(.*?)\]", swift, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', names), list(RUBRICS))
        context = re.search(r"static let contextNames = \[(.*?)\]", swift, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', context), list(CONTEXT_CHECKS))
        for rubric, options in {**RUBRICS, **CONTEXT_CHECKS}.items():
            for option in options:
                self.assertIn(f'("{option}"', swift, f"{rubric}/{option} missing from the Swift port")

    def test_secrets_are_not_committed(self):
        for path in IOS.rglob("*.swift"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("Bearer sk-", text)
            self.assertNotIn("TYPESAFE_API_KEY=", text)


if __name__ == "__main__":
    unittest.main()
