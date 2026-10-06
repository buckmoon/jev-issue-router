import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from issue_router import action, cli, slack
from issue_router.core import RouterError, load_catalog, route, validate_response
from issue_router.github import COMMENT_MARKER, publish_comment
from issue_router.slack import RecentRequests, handle_command, parse_command
from test_router import FakeJev

ACCOUNT = '0123456789abcdef0123456789abcdef'  # obviously fake
CF_TOKEN = 'cf_example_not_a_real_token'


class CliTests(unittest.TestCase):
    @patch('issue_router.cli.route')
    @patch('issue_router.cli.fetch_issue')
    def test_positional_url_and_output(self, fetch, select):
        issue = {'title': 'Task', 'body': 'Scoped edit'}
        fetch.return_value = issue
        select.return_value = route(issue, call=FakeJev())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            self.assertEqual(cli.main(['https://github.com/o/r/issues/1', '--format', 'json',
                                       '--output', str(path)]), 0)
            self.assertEqual(json.loads(path.read_text())['status'], 'selected')
        fetch.assert_called_once_with('https://github.com/o/r/issues/1')

    @patch('issue_router.cli.route')
    def test_stdin_and_environment_override(self, select):
        issue = {'body': 'Change a label and test it'}
        select.return_value = route(issue, call=FakeJev())
        with patch.dict(os.environ, {'ISSUE_MODEL_POLICY': 'cost'}), patch('sys.stdin', io.StringIO(issue['body'])):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--text', '-', '--policy', 'quality']), 0)
        self.assertEqual(select.call_args.kwargs['policy'], 'quality')
        self.assertEqual(select.call_args.args[0]['body'], issue['body'])

    def test_invalid_json_is_safe_error(self):
        out = io.StringIO()
        with patch('sys.stdin', io.StringIO('{ secret-invalid')), contextlib.redirect_stderr(out):
            self.assertEqual(cli.main(['--file', '-']), 1)
        self.assertNotIn('secret-invalid', out.getvalue())

    def test_conflicting_sources_are_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            cli.main(['https://github.com/o/r/issues/1', '--text', 'task'])
        self.assertEqual(exc.exception.code, 2)


class GitHubTests(unittest.TestCase):
    @patch('issue_router.github.gh')
    def test_updates_only_owned_marker_comment(self, gh):
        gh.side_effect = [[[
            {'id': 1, 'user': {'login': 'human'}, 'body': COMMENT_MARKER + '\nforeign'},
            {'id': 2, 'user': {'login': 'github-actions[bot]'}, 'body': 'Other tool'},
        ], [
            {'id': 3, 'user': {'login': 'github-actions[bot]'}, 'body': COMMENT_MARKER + '\nold'},
        ]], {'id': 3}]
        publish_comment('https://github.com/o/r/issues/1', 'new')
        args = gh.call_args.args[0]
        self.assertIn('PATCH', args)
        self.assertIn('repos/o/r/issues/comments/3', args)
        self.assertEqual(json.loads(gh.call_args.args[1])['body'], COMMENT_MARKER + '\nnew')

    @patch('issue_router.github.gh')
    def test_first_comment_created(self, gh):
        gh.side_effect = [[[]], {'id': 1}]
        publish_comment('https://github.com/o/r/issues/1', 'new')
        self.assertIn('POST', gh.call_args.args[0])

    @patch('issue_router.github.subprocess.run')
    def test_github_host_cannot_be_changed_by_environment(self, run):
        from issue_router.github import gh
        run.return_value = Mock(returncode=0, stdout='{}')
        with patch.dict(os.environ, {'GH_HOST': 'other.example'}):
            gh(['api', 'repos/o/r/issues/1'])
        self.assertEqual(run.call_args.args[0][:4], ['gh', 'api', '--hostname', 'github.com'])


class ActionTests(unittest.TestCase):
    def test_summary_json_outputs_and_opt_in_publication(self):
        for post in ('false', 'true'):
            with self.subTest(post=post), tempfile.TemporaryDirectory() as directory:
                env = {'GITHUB_REPOSITORY': 'o/r', 'ROUTER_ISSUE_NUMBER': '1',
                       'ROUTER_POST_COMMENT': post, 'RUNNER_TEMP': directory,
                       'TYPESAFE_API_KEY': 'ts_example_not_a_real_key',
                       'GITHUB_STEP_SUMMARY': directory + '/summary',
                       'GITHUB_OUTPUT': directory + '/output'}
                issue = {'body': 'Update label with explicit UI test'}
                publish = Mock()
                def select(issue, **options):
                    return route(issue, call=FakeJev(), **options)
                action.run(env, fetch=lambda url: issue, select=select, publish=publish)
                self.assertEqual(publish.call_count, int(post == 'true'))
                self.assertIn('https://github.com/o/r/issues/1', Path(env['GITHUB_STEP_SUMMARY']).read_text())
                outputs = dict(line.split('=', 1) for line in Path(env['GITHUB_OUTPUT']).read_text().splitlines())
                self.assertEqual(outputs['status'], 'selected')
                result = json.loads(Path(outputs['result-path']).read_text())
                self.assertEqual(set(result['recommendations']), {'openai', 'claude', 'grok'})

    def action_env(self, directory, **extra):
        return {'GITHUB_REPOSITORY': 'o/r', 'ROUTER_ISSUE_NUMBER': '1', 'RUNNER_TEMP': directory,
                'GITHUB_STEP_SUMMARY': directory + '/summary', 'GITHUB_OUTPUT': directory + '/output', **extra}

    def test_missing_evaluator_secret_stops_before_fetch(self):
        cases = [({'TYPESAFE_API_KEY': ''}, 'TYPESAFE_API_KEY'),
                 ({'ISSUE_MODEL_EVALUATOR': 'clef', 'CLOUDFLARE_ACCOUNT_ID': ACCOUNT,
                   'CLOUDFLARE_API_TOKEN': '', 'TYPESAFE_API_KEY': 'ts_example_not_a_real_key'},
                  'CLOUDFLARE_API_TOKEN is required when evaluator is clef'),
                 ({'ISSUE_MODEL_EVALUATOR': 'clef', 'CLOUDFLARE_ACCOUNT_ID': '',
                   'CLOUDFLARE_API_TOKEN': CF_TOKEN}, 'CLOUDFLARE_ACCOUNT_ID'),
                 ({'ISSUE_MODEL_EVALUATOR': 'clef', 'CLOUDFLARE_ACCOUNT_ID': ACCOUNT, 'CLOUDFLARE_API_TOKEN': CF_TOKEN,
                   'CLEF_MODEL': 'clef:27b'}, 'clef or clef-flash'),
                 ({'ISSUE_MODEL_EVALUATOR': 'bogus'}, 'ISSUE_MODEL_EVALUATOR')]
        for extra, message in cases:
            fetch = Mock()
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(RouterError, message):
                    action.run(self.action_env(directory, **extra), fetch=fetch)
            fetch.assert_not_called()

    def test_clef_settings_reach_the_engine(self):
        seen = {}

        def select(issue, **options):
            seen.update(options)
            return route(issue, call=FakeJev(), **options)

        env_extra = {'ISSUE_MODEL_EVALUATOR': 'clef', 'CLEF_HOST': 'workers-ai', 'CLEF_MODEL': 'clef',
                     'CLEF_ASSESS_MODEL': 'clef-flash', 'CLEF_URL': '', 'CLOUDFLARE_ACCOUNT_ID': ACCOUNT,
                     'CLOUDFLARE_API_TOKEN': CF_TOKEN, 'TYPESAFE_API_KEY': ''}
        # The account ID comes from the Action's environment, not the test process.
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            env = self.action_env(directory, **env_extra)
            result = action.run(env, fetch=lambda url: {'body': 'Update label'}, select=select, publish=Mock())
            summary = Path(env['GITHUB_STEP_SUMMARY']).read_text()
            saved = json.loads(Path(dict(line.split('=', 1) for line in
                                         Path(env['GITHUB_OUTPUT']).read_text().splitlines())['result-path']).read_text())
        self.assertEqual((seen['evaluator'].name, seen['evaluator'].host), ('clef', 'workers-ai'))
        self.assertEqual(result['evaluator']['models'], {'assess': 'clef-flash', 'select': 'clef'})
        self.assertIn('評価モデル: Clef (workers-ai / clef-flash → clef)', summary)
        for text in (summary, json.dumps(saved)):
            self.assertNotIn(ACCOUNT, text)
            self.assertNotIn(CF_TOKEN, text)

    def test_local_clef_needs_no_token(self):
        seen = {}

        def select(issue, **options):
            seen.update(options)
            return route(issue, call=FakeJev(), **options)

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            action.run(self.action_env(directory, ISSUE_MODEL_EVALUATOR='clef', CLEF_HOST='local',
                                       CLEF_MODEL='clef-flash', CLEF_URL='http://127.0.0.1:11434/v1/systemone'),
                       fetch=lambda url: {'body': 'Update label'}, select=select, publish=Mock())
        self.assertEqual(seen['evaluator'].host, 'local')

    def test_action_yml_declares_evaluator_inputs(self):
        text = (Path(__file__).resolve().parent.parent / 'action.yml').read_text(encoding='utf-8')
        for name in ('evaluator', 'clef-host', 'clef-model', 'clef-assess-model', 'clef-url',
                     'cloudflare-account-id', 'cloudflare-api-token'):
            self.assertIn(f'\n  {name}:\n', text)
        for env in ('ISSUE_MODEL_EVALUATOR', 'CLEF_HOST', 'CLEF_MODEL', 'CLEF_ASSESS_MODEL', 'CLEF_URL',
                    'CLOUDFLARE_ACCOUNT_ID', 'CLOUDFLARE_API_TOKEN'):
            self.assertIn(f'        {env}: ${{{{ inputs.', text)
        self.assertIn('typesafe-api-key:\n    description: TypeSafe API key, supplied from an Actions Secret '
                      '(required when evaluator is jev)\n    required: false', text)

    def test_injected_issue_number_rejected_before_network(self):
        fetch = Mock()
        with self.assertRaises(RouterError):
            action.run({'GITHUB_REPOSITORY': 'o/r', 'ROUTER_ISSUE_NUMBER': '1; echo secret'}, fetch=fetch)
        fetch.assert_not_called()


class SlackTests(unittest.TestCase):
    def test_main_accepts_evaluator_flags_without_starting(self):
        env = {'SLACK_ALLOWED_USERS': '', 'GITHUB_ALLOWED_REPOS': ''}
        with patch.dict(os.environ, env, clear=True):
            # Valid evaluator settings get past configuration and stop at the Slack allowlists.
            with self.assertRaisesRegex(SystemExit, 'SLACK_ALLOWED_USERS'):
                slack.main(['--evaluator', 'clef', '--clef-host', 'local', '--clef-model', 'clef-flash'])
            with self.assertRaisesRegex(SystemExit, 'CLOUDFLARE_ACCOUNT_ID'):
                slack.main(['--evaluator', 'clef'])

    def test_command_policy_and_slack_link_format(self):
        self.assertEqual(parse_command('<https://github.com/o/r/issues/1|Issue> quality'),
                         ('https://github.com/o/r/issues/1', 'quality'))
        for value in ('', 'https://evil.example/x', 'https://github.com/o/r/issues/1 bogus'):
            with self.assertRaises(RouterError):
                parse_command(value)

    def test_other_workspace_rejected_before_fetch(self):
        fetch, respond = Mock(), Mock()
        handle_command(Mock(), respond, {'team_id': 'T2', 'user_id': 'U1'},
                       allowed_users={'U1'}, allowed_repos={'o/r'}, team_id='T1',
                       gate=threading.BoundedSemaphore(1), fetch=fetch)
        fetch.assert_not_called()
        self.assertEqual(respond.call_args.kwargs['response_type'], 'ephemeral')

    def test_policy_override_and_duplicate_request(self):
        select = Mock(return_value=route({'body': 'Update label'}, call=FakeJev()))
        fetch = Mock(return_value={'body': 'Update label'})
        gate, recent = threading.BoundedSemaphore(1), RecentRequests()
        command = {'user_id': 'U1', 'trigger_id': 'unique', 'text': 'https://github.com/o/r/issues/1 cost'}
        for _ in range(2):
            handle_command(Mock(), Mock(), command, allowed_users={'U1'}, allowed_repos={'o/r'},
                           gate=gate, recent=recent, select=select, fetch=fetch)
        select.assert_called_once_with({'body': 'Update label'}, policy='cost')
        self.assertTrue(gate.acquire(blocking=False))

    def test_busy_and_exception_release_gate(self):
        gate = threading.BoundedSemaphore(1)
        gate.acquire()
        fetch, respond = Mock(), Mock()
        params = dict(allowed_users={'U1'}, allowed_repos={'o/r'}, gate=gate, fetch=fetch)
        command = {'user_id': 'U1', 'text': 'https://github.com/o/r/issues/1'}
        handle_command(Mock(), respond, command, **params)
        fetch.assert_not_called()
        gate.release()
        fetch.side_effect = RouterError('Unavailable')
        handle_command(Mock(), respond, command, **params)
        self.assertTrue(gate.acquire(blocking=False))


class ValidationTests(unittest.TestCase):
    def test_invalid_catalog_before_api(self):
        variants = []
        bad = copy.deepcopy(load_catalog())
        bad['verified_at'] = 'yesterday'
        variants.append(bad)
        bad = copy.deepcopy(load_catalog())
        bad['models'][0]['efforts'] = ['invented']
        variants.append(bad)
        bad = copy.deepcopy(load_catalog())
        bad['models'][0]['enabled'] = 'false'
        variants.append(bad)
        for catalog in variants:
            call = Mock()
            with self.assertRaises(RouterError):
                route({'body': 'Task'}, catalog=catalog, call=call)
            call.assert_not_called()

    def test_bad_answer_types_and_nonfinite_probabilities(self):
        questions = {'q': {'criteria': {'yes': 'yes', 'no': 'no'}}}
        for answer in ([], None, {'type': 'choice', 'choice': [], 'confidence': 1, 'probabilities': {}},
                       {'type': 'choice', 'choice': 'yes', 'confidence': 1,
                        'probabilities': {'yes': float('nan'), 'no': 0}}):
            with self.assertRaises(RouterError):
                validate_response({'answers': {'q': answer}}, questions)

    def test_extra_unrequested_answer_is_not_rendered(self):
        fake = FakeJev()
        def call(request):
            reply = fake(request)
            reply['answers']['untrusted_extra'] = {'text': 'not a rubric'}
            return reply
        result = route({'body': 'Task'}, call=call)
        self.assertNotIn('untrusted_extra', result['assessment'])


if __name__ == '__main__':
    unittest.main()
