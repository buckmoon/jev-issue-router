import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from issue_router.benchmark import load_cases, main, run_cases, summarize
from issue_router.core import RouterError, route, render
from issue_router.evaluators import make_evaluator
from test_router import FakeJev


class OrderCheckTests(unittest.TestCase):
    issue = {"title": "Change label", "body": "Change Save to Save changes; update snapshot."}

    def consistent(self, request):
        response = FakeJev()(request)
        for name in ("openai", "claude", "grok"):
            if name in response["answers"]:
                response["answers"]["order_" + name] = copy.deepcopy(response["answers"][name])
        return response

    def test_same_call_same_semantics_reversed_order_and_raw_answers(self):
        requests = []

        def call(request):
            requests.append(request)
            return self.consistent(request)

        result = route(self.issue, call=call)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(requests[1]["questions"]), 6)
        for name, rec in result["recommendations"].items():
            original, reverse = (requests[1]["questions"][k] for k in (name, "order_" + name))
            self.assertEqual(original["instructions"], reverse["instructions"])
            self.assertEqual(list(original["criteria"].items()), list(reversed(list(reverse["criteria"].items()))))
            self.assertTrue(rec["order_check"]["consistent"])
            self.assertEqual(rec["judgment"], rec["order_check"]["reversed_judgment"])

    def test_disagreement_does_not_replace_or_average_the_winner(self):
        original_answer = None

        def call(request):
            nonlocal original_answer
            response = self.consistent(request)
            if "openai" in request["questions"]:
                original_answer = copy.deepcopy(response["answers"]["openai"])
                other = list(request["questions"]["openai"]["criteria"])[-1]
                response["answers"]["order_openai"].update(
                    choice=other, probabilities={c: float(c == other)
                                                 for c in request["questions"]["openai"]["criteria"]})
            return response

        result = route(self.issue, call=call)
        rec = result["recommendations"]["openai"]
        self.assertEqual(rec["judgment"], original_answer)
        self.assertFalse(rec["order_check"]["consistent"])
        self.assertEqual(rec["model"] + "__" + rec["effort"], original_answer["choice"])
        self.assertIn("順序反転で不一致", render(result))

    def test_reversed_abstention_is_visible_without_losing_original(self):
        def call(request):
            response = self.consistent(request)
            if "openai" in request["questions"]:
                response["answers"]["order_openai"].update(
                    choice="needs_context", probabilities={c: float(c == "needs_context")
                                                          for c in request["questions"]["openai"]["criteria"]})
            return response

        result = route(self.issue, call=call)
        self.assertEqual(result["recommendations"]["openai"]["status"], "selected")
        self.assertIn("順序反転で不一致: 選定保留", render(result))

    def test_bad_check_fails_closed_and_never_retries(self):
        fake = FakeJev()

        def call(request):
            response = fake(request)
            if "order_openai" in response["answers"]:
                del response["answers"]["order_openai"]
            return response

        with self.assertRaises(RouterError):
            route(self.issue, call=call)
        self.assertEqual(len(fake.requests), 2)

    def test_jev_and_clef_question_bodies_remain_identical(self):
        requests = []
        for evaluator in (make_evaluator("jev"), make_evaluator("clef", clef_host="local")):
            fake = FakeJev()
            route(self.issue, evaluator=evaluator, call=fake)
            requests.append([{k: v for k, v in r.items() if k != "model"} for r in fake.requests])
        self.assertEqual(requests[0], requests[1])


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.cases = [{"id": "copy", "issue": {"body": "Change button label"},
                       "expected_assessment": {"reasoning": "routine"}}]

    def test_no_issue_body_in_saved_rows_and_no_unlabeled_accuracy(self):
        rows = run_cases(self.cases, call=FakeJev())
        self.assertNotIn("Change button label", json.dumps(rows))
        summary = summarize(rows)[0]
        self.assertEqual(summary["assessment_labels"], {"labeled": 1, "matched": 1})
        for provider in summary["providers"].values():
            self.assertIsNone(provider["label_agreement"])
            self.assertEqual(provider["labeled"], 0)

    def test_dominance_excludes_abstentions_and_tracks_labels_and_equivalence(self):
        rows = run_cases(self.cases, repeat=2, call=FakeJev())
        for row in rows:
            row["equivalence_group"] = "copy"
            row["expected_recommendations"] = {"openai": [{"model": "not-selected", "effort": "low"}]}
        rows[1]["result"]["recommendations"]["openai"] = {"status": "needs_context"}
        provider = summarize(rows)[0]["providers"]["openai"]
        self.assertEqual(provider["selected"], 1)
        self.assertEqual(provider["held"], 1)
        self.assertEqual(provider["dominant_pair_share"], 1)
        self.assertEqual(provider["label_agreement"], 0)
        self.assertEqual(provider["equivalence_disagreements"], 1)

    def test_versions_do_not_get_combined(self):
        rows = run_cases(self.cases, repeat=2, call=FakeJev())
        rows[1]["result"]["catalog_version"] = "other"
        self.assertEqual(len(summarize(rows)), 2)

    @patch("issue_router.evaluators.Evaluator.call", side_effect=AssertionError("No network"))
    def test_offline_report_does_not_access_credentials_or_call_evaluator(self, call):
        rows = run_cases(self.cases, call=FakeJev())
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / "input.json", Path(tmp) / "report.json"
            source.write_text(json.dumps({"rows": rows}))
            self.assertEqual(main(["--results", str(source), "--output", str(dest)]), 0)
            self.assertIn("summary", json.loads(dest.read_text()))
        call.assert_not_called()

    def test_invalid_dataset_rejected_before_any_live_call(self):
        for data in ([], [{"id": "private text with spaces", "issue": {"body": "x"}}],
                     self.cases * 2, [{**self.cases[0], "expected_assessment": {"risk": "nonsense"}}]):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "cases.json"
                path.write_text(json.dumps(data))
                with self.assertRaises(RouterError):
                    load_cases(path)

    def test_live_is_explicit_and_repeat_is_bounded(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main([])
        fake = FakeJev()
        for repeat in (0, 11, True):
            with self.assertRaises(RouterError):
                run_cases(self.cases, repeat=repeat, call=fake)
        self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
