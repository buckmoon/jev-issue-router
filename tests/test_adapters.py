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

from issue_router import action, cli
from issue_router.core import RouterError, load_catalog, route, validate_response
from issue_router.github import COMMENT_MARKER, publish_comment
from issue_router.slack import RecentRequests, handle_command, parse_command
from test_router import FakeJev


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

    def test_injected_issue_number_rejected_before_network(self):
        fetch = Mock()
        with self.assertRaises(RouterError):
            action.run({'GITHUB_REPOSITORY': 'o/r', 'ROUTER_ISSUE_NUMBER': '1; echo secret'}, fetch=fetch)
        fetch.assert_not_called()


class SlackTests(unittest.TestCase):
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
