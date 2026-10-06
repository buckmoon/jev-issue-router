"""Evaluator backends (Jev and Clef). No test reaches TypeSafe, Cloudflare or a local server."""
import argparse
import contextlib
import copy
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from issue_router import cli
from issue_router.core import RouterError, render, route
from issue_router.evaluators import (JEV_URL, LOCAL_URL, Evaluator, local_url, make_evaluator,
                                     unwrap_workers_ai)
from issue_router.settings import add_routing_arguments, routing_options
from test_router import FakeJev

ACCOUNT = "0123456789abcdef0123456789abcdef"  # obviously fake
TOKEN = "cf_example_not_a_real_token"
ISSUE = {"title": "Change button label", "body": "Save to Save changes; update UI test"}


def clef(**kwargs):
    return make_evaluator("clef", account_id=ACCOUNT, environ={}, **kwargs)


def fake_opener(payload=None, error=None):
    """Patch target for urllib.request.build_opener; records the Request it was asked to open."""
    opener = MagicMock()
    if error is not None:
        opener.open.side_effect = error
    else:
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        opener.open.return_value = response
    return MagicMock(return_value=opener), opener


class MakeEvaluatorTests(unittest.TestCase):
    def test_default_is_jev_on_typesafe(self):
        evaluator = make_evaluator()
        self.assertEqual((evaluator.name, evaluator.host), ("jev", "typesafe"))
        self.assertEqual(evaluator.models, {"assess": "jev-latest", "select": "jev-latest"})
        self.assertEqual(evaluator.url_for("jev-latest"), JEV_URL)
        self.assertFalse(evaluator.envelope)
        self.assertIsNone(evaluator.context_tokens)

    def test_workers_ai_url_carries_account_and_model(self):
        evaluator = clef(clef_model="clef", clef_assess_model="clef-flash")
        self.assertEqual(evaluator.host, "workers-ai")
        self.assertTrue(evaluator.envelope)
        base = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/@cf/cloudflare/"
        self.assertEqual(evaluator.url_for("clef"), base + "clef")
        self.assertEqual(evaluator.url_for("clef-flash"), base + "clef-flash")
        self.assertNotIn(ACCOUNT, json.dumps(evaluator.describe()))

    def test_account_id_is_read_from_environment(self):
        evaluator = make_evaluator("clef", environ={"CLOUDFLARE_ACCOUNT_ID": ACCOUNT})
        self.assertIn(ACCOUNT, evaluator.url_for("clef"))

    def test_assess_model_defaults_to_clef_model(self):
        self.assertEqual(clef().models, {"assess": "clef", "select": "clef"})
        self.assertEqual(clef(clef_model="clef-flash").models, {"assess": "clef-flash", "select": "clef-flash"})

    def test_invalid_settings_fail_before_network(self):
        cases = [
            dict(name="bogus"),
            dict(name="jev", jev_model=" "),
            dict(name="clef", clef_host="cloud", account_id=ACCOUNT),
            dict(name="clef", account_id="not-an-account"),
            dict(name="clef", account_id=ACCOUNT.upper()),
            dict(name="clef"),  # no account id at all
            dict(name="clef", account_id=ACCOUNT, clef_model="clef-mega"),
            dict(name="clef", account_id=ACCOUNT, clef_assess_model="clef-mega"),
            dict(name="clef", account_id=ACCOUNT, clef_model="clef:27b"),  # local tags are not Workers AI models
            dict(name="clef", clef_host="local", clef_model="clef flash"),
            dict(name="clef", clef_host="local", clef_assess_model="../x/" * 20),
            dict(name="clef", clef_host="local", clef_url="http://10.0.0.5:11434/v1/systemone"),
            dict(name="clef", account_id=ACCOUNT, timeout="5"),
            dict(name="clef", account_id=ACCOUNT, timeout="soon"),
        ]
        with patch("urllib.request.build_opener") as opener:
            for kwargs in cases:
                with self.subTest(kwargs=kwargs), self.assertRaises(RouterError):
                    make_evaluator(environ={}, **kwargs)
            opener.assert_not_called()

    def test_local_host_accepts_ollama_tags_and_longer_timeout(self):
        evaluator = make_evaluator("clef", clef_host="local", clef_model="clef:27b-q8_0",
                                   clef_assess_model="clef-flash", environ={})
        self.assertEqual(evaluator.models, {"assess": "clef-flash", "select": "clef:27b-q8_0"})
        self.assertEqual(evaluator.url_for("clef-flash"), LOCAL_URL)
        self.assertEqual(evaluator.timeout, 300)
        self.assertFalse(evaluator.envelope)
        self.assertEqual(make_evaluator("clef", clef_host="local", environ={"CLEF_TIMEOUT": "42"}).timeout, 42)

    def test_url_for_rejects_unconfigured_models(self):
        evaluator = clef()
        for model in ("clef-flash", "", None, "../other"):
            with self.subTest(model=model), self.assertRaises(RouterError):
                evaluator.url_for(model)


class LocalUrlTests(unittest.TestCase):
    def test_loopback_http_and_any_https_only(self):
        for url in ("http://127.0.0.1:11434/v1/systemone", "http://localhost:8000/v1/systemone",
                    "http://[::1]:11434/v1/systemone", "https://gpu.example.test/v1/systemone"):
            with self.subTest(url=url):
                self.assertEqual(local_url(url), url)
        for url in ("http://10.0.0.5/v1/systemone", "http://example.test/v1/systemone",
                    "https://gpu.example.test/v1/systemone?key=x", "https://gpu.example.test/v1#frag",
                    "ftp://127.0.0.1/v1/systemone", "file:///tmp/x", "https:///v1/systemone",
                    "http://[::1/v1/systemone"):
            with self.subTest(url=url), self.assertRaises(RouterError):
                local_url(url)


class CallTests(unittest.TestCase):
    request = {"model": "clef", "state": {"text": "ping"}, "questions": {}}

    def test_workers_ai_sends_model_and_token_and_unwraps(self):
        result = {"model": "clef", "answers": {}, "usage": {"input_tokens": 3, "output_tokens": 0}}
        build, opener = fake_opener({"result": result, "success": True, "errors": [], "messages": []})
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": TOKEN}), \
                patch("urllib.request.build_opener", build):
            self.assertEqual(clef().call(self.request), result)
        sent = opener.open.call_args.args[0]
        self.assertEqual(json.loads(sent.data)["model"], "clef")
        self.assertTrue(sent.full_url.endswith("/ai/run/@cf/cloudflare/clef"))
        self.assertEqual(sent.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 60)

    def test_missing_token_fails_before_network(self):
        build, opener = fake_opener({})
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.build_opener", build), \
                patch("issue_router.evaluators.keychain_secret", return_value=None):
            with self.assertRaisesRegex(RouterError, "CLOUDFLARE_API_TOKEN"):
                clef().call(self.request)
        opener.open.assert_not_called()

    def test_local_without_key_sends_no_authorization(self):
        evaluator = make_evaluator("clef", clef_host="local", environ={})
        build, opener = fake_opener({"model": "clef", "answers": {}})
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.build_opener", build):
            self.assertEqual(evaluator.call(self.request), {"model": "clef", "answers": {}})
        sent = opener.open.call_args.args[0]
        self.assertIsNone(sent.get_header("Authorization"))
        self.assertEqual(sent.full_url, LOCAL_URL)

    def test_local_with_optional_key(self):
        evaluator = make_evaluator("clef", clef_host="local", environ={})
        build, opener = fake_opener({"model": "clef", "answers": {}})
        with patch.dict(os.environ, {"CLEF_API_KEY": "local_example_not_a_real_key"}), \
                patch("urllib.request.build_opener", build):
            evaluator.call(self.request)
        self.assertEqual(opener.open.call_args.args[0].get_header("Authorization"),
                         "Bearer local_example_not_a_real_key")

    def test_http_error_omits_body(self):
        body = io.BytesIO(b'{"errors":[{"code":7003,"message":"secret issue text"}]}')
        error = urllib.error.HTTPError("https://api.cloudflare.com/x", 400, "Bad Request", {}, body)
        self.addCleanup(error.close)
        build, _ = fake_opener(error=error)
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": TOKEN}), \
                patch("urllib.request.build_opener", build):
            with self.assertRaises(RouterError) as caught:
                clef().call(self.request)
        message = str(caught.exception)
        self.assertIn("Clef HTTP 400", message)
        self.assertNotIn("secret issue text", message)
        self.assertNotIn(TOKEN, message)
        self.assertNotIn(ACCOUNT, message)

    def test_network_error_is_labelled(self):
        build, _ = fake_opener(error=urllib.error.URLError("refused"))
        evaluator = make_evaluator("clef", clef_host="local", environ={})
        with patch("urllib.request.build_opener", build):
            with self.assertRaisesRegex(RouterError, "^Clef network"):
                evaluator.call(self.request)


class UnwrapTests(unittest.TestCase):
    def test_success_returns_result(self):
        result = {"model": "clef", "answers": {}}
        self.assertIs(unwrap_workers_ai({"result": result, "success": True, "errors": []}, "Clef"), result)

    def test_failure_reports_numeric_codes_only(self):
        payload = {"result": None, "success": False,
                   "errors": [{"code": 5006, "message": "echo: private issue text"},
                              {"code": "7000", "message": "x"}, "junk", {"code": 3001}]}
        with self.assertRaises(RouterError) as caught:
            unwrap_workers_ai(payload, "Clef")
        message = str(caught.exception)
        self.assertIn("[3001, 5006]", message)
        self.assertNotIn("private issue text", message)
        self.assertNotIn("7000", message)

    def test_malformed_envelopes_fail(self):
        for payload in ({"success": True}, {"success": True, "result": []}, {"success": "true", "result": {}},
                        [], None, {"success": False, "result": {}, "errors": None}):
            with self.subTest(payload=payload), self.assertRaises(RouterError):
                unwrap_workers_ai(payload, "Clef")


class RouteTests(unittest.TestCase):
    def test_default_call_style_still_works(self):
        result = route(ISSUE, call=FakeJev())
        self.assertEqual(result["evaluator"],
                         {"name": "jev", "host": "typesafe", "models": {"assess": "jev-latest", "select": "jev-latest"}})
        self.assertEqual(result["schema_version"], 1)
        self.assertFalse(any("Clef" in warning for warning in result["warnings"]))

    def test_jev_and_clef_requests_differ_only_in_model(self):
        jev, clef_fake = FakeJev(), FakeJev()
        route(ISSUE, call=jev, evaluator=make_evaluator("jev"))
        result = route(ISSUE, call=clef_fake, evaluator=clef())
        self.assertEqual(len(jev.requests), 2)
        self.assertEqual(len(clef_fake.requests), 2)
        for sent_jev, sent_clef in zip(jev.requests, clef_fake.requests):
            self.assertEqual((sent_jev["model"], sent_clef["model"]), ("jev-latest", "clef"))
            self.assertEqual({k: v for k, v in sent_jev.items() if k != "model"},
                             {k: v for k, v in sent_clef.items() if k != "model"})
        self.assertEqual(result["evaluator"],
                         {"name": "clef", "host": "workers-ai", "models": {"assess": "clef", "select": "clef"}})
        self.assertEqual(len(result["jev_calls"]), 2)
        self.assertTrue(any("未校正" in warning and "Clef" in warning for warning in result["warnings"]))

    def test_tiered_models_per_stage(self):
        fake = FakeJev()
        result = route(ISSUE, call=fake, evaluator=clef(clef_model="clef", clef_assess_model="clef-flash"))
        self.assertEqual([r["model"] for r in fake.requests], ["clef-flash", "clef"])
        self.assertEqual(result["evaluator"]["models"],
                         {"assess": fake.requests[0]["model"], "select": fake.requests[1]["model"]})

    def test_tiered_request_flows_through_evaluator_call(self):
        evaluator = clef(clef_model="clef", clef_assess_model="clef-flash")
        fake, urls = FakeJev(), []

        def transport(url, request):
            urls.append(url)
            return {"result": fake(request), "success": True, "errors": []}

        def call(request):  # the real Evaluator.call path minus the socket
            return unwrap_workers_ai(transport(evaluator.url_for(request["model"]), request), evaluator.label)

        route(ISSUE, call=call, evaluator=evaluator)
        self.assertEqual([u.rsplit("/", 1)[1] for u in urls], ["clef-flash", "clef"])

    def test_context_limit_warning(self):
        for tokens, warned in ((58982, False), (58983, True)):
            fake = FakeJev()

            def reply(request, fake=fake, tokens=tokens):
                response = fake(request)
                response["usage"] = {"input_tokens": tokens, "output_tokens": 0}
                return response

            with self.subTest(tokens=tokens):
                result = route(ISSUE, call=reply, evaluator=clef())
                self.assertEqual(any("切り詰め" in w for w in result["warnings"]), warned)
                jev_result = route(ISSUE, call=reply)
                self.assertFalse(any("切り詰め" in w for w in jev_result["warnings"]))

    def test_evaluator_failure_has_no_fallback(self):
        def unavailable(request):
            raise RouterError("Clef HTTP 503; response body omitted to protect input and credentials")
        with self.assertRaisesRegex(RouterError, "Clef HTTP 503"):
            route(ISSUE, call=unavailable, evaluator=clef())


class RenderTests(unittest.TestCase):
    def test_clef_labels_and_models(self):
        result = route(ISSUE, call=FakeJev(), evaluator=clef())
        text = render(result)
        self.assertTrue(text.startswith("Clef モデル推薦（暫定）"))
        self.assertIn("評価モデル: Clef (workers-ai / clef) / 方針: balanced", text)

    def test_tiered_shows_both_stages(self):
        result = route(ISSUE, call=FakeJev(), evaluator=clef(clef_model="clef", clef_assess_model="clef-flash"))
        self.assertIn("評価モデル: Clef (workers-ai / clef-flash → clef)", render(result))

    def test_clef_abstention_names_clef(self):
        result = route({"body": "?"}, call=FakeJev(insufficient=True), evaluator=clef())
        result["missing_context"] = ["goal"]
        self.assertIn("Clefが不足と判断した情報", render(result))

    def test_old_results_render_as_jev(self):
        result = route(ISSUE, call=FakeJev())
        old = copy.deepcopy(result)
        del old["evaluator"]
        text = render(old)
        self.assertTrue(text.startswith("Jev モデル推薦（暫定）"))
        self.assertIn("評価モデル: Jev (typesafe / jev-latest)", text)
        self.assertEqual(text, render(result))


class SettingsTests(unittest.TestCase):
    def parse(self, argv):
        parser = argparse.ArgumentParser()
        add_routing_arguments(parser)
        return parser.parse_args(argv)

    def test_clef_from_flags_and_environment(self):
        with patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": ACCOUNT}):
            options = routing_options(self.parse(["--evaluator", "clef", "--clef-assess-model", "clef-flash"]))
        evaluator = options["evaluator"]
        self.assertIsInstance(evaluator, Evaluator)
        self.assertEqual(evaluator.host, "workers-ai")
        self.assertEqual(evaluator.models, {"assess": "clef-flash", "select": "clef"})

    def test_environment_selects_clef(self):
        env = {"ISSUE_MODEL_EVALUATOR": "clef", "CLEF_HOST": "local", "CLEF_MODEL": "clef-flash"}
        with patch.dict(os.environ, env):
            evaluator = routing_options(self.parse([]))["evaluator"]
        self.assertEqual((evaluator.name, evaluator.host), ("clef", "local"))
        self.assertEqual(evaluator.models, {"assess": "clef-flash", "select": "clef-flash"})

    def test_flags_override_environment(self):
        with patch.dict(os.environ, {"ISSUE_MODEL_EVALUATOR": "clef"}):
            self.assertEqual(routing_options(self.parse(["--evaluator", "jev"]))["evaluator"].name, "jev")

    def test_bogus_evaluator_rejected(self):
        with patch.dict(os.environ, {"ISSUE_MODEL_EVALUATOR": "bogus"}):
            with self.assertRaises(RouterError):
                routing_options(self.parse([]))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse(["--evaluator", "bogus"])

    def test_no_keychain_read_while_configuring(self):
        with patch.dict(os.environ, {"CLOUDFLARE_ACCOUNT_ID": ACCOUNT}), \
                patch("issue_router.evaluators.keychain_secret") as keychain, \
                patch("subprocess.run") as run:
            routing_options(self.parse(["--evaluator", "clef"]))
            routing_options(self.parse([]))
        keychain.assert_not_called()
        run.assert_not_called()

    def test_cli_rejects_missing_account_before_github_or_api(self):
        env = {k: v for k, v in os.environ.items() if k != "CLOUDFLARE_ACCOUNT_ID"}
        env["ISSUE_MODEL_EVALUATOR"] = "clef"
        stderr = io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch("issue_router.cli.fetch_issue") as fetch, \
                patch("issue_router.cli.route") as select, contextlib.redirect_stderr(stderr):
            self.assertEqual(cli.main(["https://github.com/o/r/issues/1"]), 1)
        fetch.assert_not_called()
        select.assert_not_called()
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
