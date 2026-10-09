"""The iOS app is a Swift port of the engine; these checks fail when the two drift apart."""
import json
from pathlib import Path
import re
import unittest

from issue_router import evaluators
from issue_router.core import MAX_INPUT_CHARS, MAX_QUESTIONS, POLICY_VERSION, PROVIDERS, TOP_CANDIDATES
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
        self.assertIn(f"maxQuestions = {MAX_QUESTIONS}", router)
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

    def test_evaluators_match(self):
        swift = source("Engine/Evaluator.swift")

        def listed(name):
            return re.findall(r'"([^"]+)"', re.search(rf"static let {name} = \[(.*?)\]", swift, re.S).group(1))

        self.assertEqual(listed("names"), list(evaluators.EVALUATORS))
        self.assertEqual(listed("stages"), list(evaluators.STAGES))
        self.assertEqual(listed("workersAIModels"), list(evaluators.WORKERS_AI_MODELS))
        hosts = listed("hosts")
        self.assertEqual(hosts, ["typesafe", "workers-ai"])
        self.assertTrue(set(hosts) <= set(evaluators.TIMEOUTS), "iOS hosts must be a subset of the Python hosts")
        for name, label in evaluators.LABELS.items():
            self.assertIn(f'"{name}": "{label}"', swift)
        for name, service in evaluators.KEYCHAIN.items():
            self.assertIn(f'"{name}": "{service}"', swift)
        for host in hosts:
            self.assertIn(f'"{host}": {evaluators.TIMEOUTS[host]}', swift)
        self.assertIn(f'jevURL = "{evaluators.JEV_URL}"', swift)
        self.assertIn(f'workersAIURL = "{evaluators.WORKERS_AI_URL}"', swift)
        limits = re.search(r"static let clefContextTokens = \[(.*?)\]", swift).group(1)
        self.assertEqual(dict((m, int(n)) for m, n in re.findall(r'"([^"]+)": (\d+)', limits)),
                         evaluators.CLEF_CONTEXT_TOKENS)
        self.assertIn(f'cloudflareService = "{evaluators.KEYCHAIN["clef"]}"', source("Services/Keychain.swift"))
        client = source("Engine/SystemOneClient.swift")
        for text in ("Cloudflare error codes", "response body omitted", "NoRedirect", "evaluator.envelope"):
            self.assertIn(text, client)
        self.assertFalse((IOS / "Engine" / "JevClient.swift").exists())

    def test_result_and_render_carry_the_evaluator(self):
        router = source("Engine/Router.swift")
        self.assertIn('("evaluator", evaluator.describe())', router)
        self.assertIn('("jev_calls", .array(calls))', router)
        self.assertIn("Clefでは未校正です", router)
        self.assertIn("コンテキスト上限に近づいています", router)
        render = source("Engine/Render.swift")
        self.assertIn("評価モデル: ", render)
        self.assertIn(" → ", render)

    def test_secrets_are_not_committed(self):
        for path in IOS.rglob("*.swift"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("Bearer sk-", text)
            self.assertNotIn("TYPESAFE_API_KEY=", text)
            self.assertNotIn("CLOUDFLARE_API_TOKEN=", text)
            self.assertIsNone(re.search(r'accounts/[0-9a-f]{32}', text), f"{path.name} contains an account ID")


if __name__ == "__main__":
    unittest.main()
