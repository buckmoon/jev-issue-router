"""The iOS app is a Swift port of the engine; these checks fail when the two drift apart."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from issue_router import evaluators
from issue_router.core import MAX_INPUT_CHARS, MAX_QUESTIONS, POLICY_VERSION, PROVIDERS, TOP_CANDIDATES
from issue_router.core import ASSESSMENT_INSTRUCTIONS, EFFORT_BOUNDARIES, SELECTION_INSTRUCTIONS
from issue_router.core import load_catalog, route, render
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

    def test_question_boundaries_match_exactly(self):
        swift = source("Engine/Rubrics.swift")
        for mapping in (ASSESSMENT_INSTRUCTIONS, EFFORT_BOUNDARIES):
            for key, value in mapping.items():
                self.assertIn(json.dumps(key) + ": " + json.dumps(value), swift)
        self.assertIn("static let selectionInstructions = " + json.dumps(SELECTION_INSTRUCTIONS), swift)
        router = source("Engine/Router.swift")
        self.assertIn('Question(name: "order_" + provider', router)
        self.assertIn('("order_check", .fields', router)

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


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "Swift parity needs the macOS toolchain")
class IOSRuntimeParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.binary = str(Path(cls.tmp.name) / "ios-parity")
        files = [IOS / "Engine" / (name + ".swift") for name in
                 ("JSONValue", "Catalog", "Policies", "Rubrics", "Evaluator", "Router", "Render")]
        # WMO avoids Swift's cross-file enum-reference compilation issue in a standalone harness.
        subprocess.run(["swiftc", "-whole-module-optimization", "-parse-as-library", *map(str, files),
                        str(Path(__file__).with_name("ios_parity.swift")), "-o", cls.binary],
                       capture_output=True, text=True, check=True, timeout=90)

    @staticmethod
    def response(request, mode):
        answers = {}
        for name, question in request["questions"].items():
            key = name.removeprefix("order_")
            choices = list(question["criteria"])
            choice = choices[0]
            if key in PROVIDERS:
                choice = next((c for c in choices if c != "needs_context"), "needs_context")
                if mode == "held" or (mode == "disagree" and name.startswith("order_")):
                    choice = "needs_context"
            if mode == "unready" and key == "readiness":
                choice = "insufficient"
            if mode == "unready" and key == "context_goal":
                choice = "missing"
            answers[name] = {"type": "choice", "choice": choice, "confidence": 1,
                             "probabilities": {c: float(c == choice) for c in choices}}
        return {"model": "test-jev", "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 5}}

    def test_requests_results_and_render_match_with_order_checks_and_abstention(self):
        for policy in ("balanced", "value", "min-cost", "max-quality"):
            for mode in ("consistent", "disagree", "held", "unready"):
                with self.subTest(policy=policy, mode=mode):
                    issue = {"title": "変更", "body": "Change button label", "context": ""}
                    requests, responses = [], []

                    def call(request):
                        requests.append(request)
                        response = self.response(request, mode)
                        responses.append(response)
                        return response

                    result = route(issue, policy=policy, call=call)
                    text = render(result).replace("--policy ", "方針 ")
                    path = Path(self.tmp.name) / "input.json"
                    path.write_text(json.dumps({"issue": issue, "policy": policy,
                                                "catalog": load_catalog(), "responses": responses}), encoding="utf-8")
                    proc = subprocess.run([self.binary, str(path)], capture_output=True, text=True,
                                          check=True, timeout=20)
                    swift = json.loads(proc.stdout)
                    self.assertEqual(requests, swift["requests"])
                    result.pop("created_at")
                    swift["result"].pop("created_at")
                    self.assertEqual(result, swift["result"])
                    self.assertEqual(text, swift["render"])


if __name__ == "__main__":
    unittest.main()
