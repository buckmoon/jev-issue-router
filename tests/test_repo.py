import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from issue_router import cli
from issue_router.core import CONTEXT_HINTS, REPOSITORY_GUARD, RouterError, render, route
from issue_router.repo import related_paths, snapshot
from test_router import FakeJev
from unittest.mock import patch


def make_repo(root):
    env = {**os.environ, 'GIT_AUTHOR_NAME': 'T', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
           'GIT_COMMITTER_NAME': 'T', 'GIT_COMMITTER_EMAIL': 't@example.invalid',
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull}
    files = {'pyproject.toml': '', 'app/billing/webhook.py': 'SECRET_CONTENT = 1\n',
             'tests/test_webhook.py': '', '.github/workflows/ci.yml': '', 'db/migrations/001.sql': ''}
    for name, content in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for args in (['init', '-q', '-b', 'main'], ['add', '.'], ['commit', '-q', '-m', 'Add billing webhook']):
        subprocess.run(['git', '-C', root, *args], check=True, env=env, capture_output=True)
    (Path(root) / 'untracked.txt').write_text('x')


class SnapshotTests(unittest.TestCase):
    def test_metadata_only(self):
        with tempfile.TemporaryDirectory() as root:
            make_repo(root)
            data = snapshot(root, 'Webhook retries double-charge customers in billing')
        self.assertEqual(data['tracked_files'], 5)
        self.assertEqual(data['branch'], 'main')
        self.assertEqual(data['manifests'], ['pyproject.toml'])
        self.assertEqual(data['test_files'], 1)
        self.assertTrue(data['has_ci'])
        self.assertTrue(data['has_migrations'])
        self.assertEqual(data['uncommitted_changes'], 1)
        self.assertEqual(data['commits_last_90_days'], 1)
        self.assertIn('Add billing webhook', data['recent_commit_subjects'][0])
        self.assertEqual(data['paths_matching_issue_terms'][0], 'app/billing/webhook.py')
        self.assertEqual(data['files_by_directory']['app/billing/'], 1)
        self.assertNotIn('SECRET_CONTENT', json.dumps(data))

    def test_rejects_non_repository(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {'GIT_CEILING_DIRECTORIES': str(Path(root).resolve().parent)}):
                with self.assertRaises(RouterError):
                    snapshot(root)
            with self.assertRaises(RouterError):
                snapshot(str(Path(root) / 'missing'))

    def test_related_paths_ignore_generic_words(self):
        self.assertEqual(related_paths(['src/index.ts', 'tests/test_a.py'], 'update the tests in src index'), [])


class RoutingTests(unittest.TestCase):
    def test_repository_reaches_both_calls_with_guard(self):
        jev = FakeJev()
        issue = {'title': 'Task', 'body': 'Scoped edit'}
        result = route(issue, call=jev, repository={'name': 'demo', 'tracked_files': 3})
        for request in jev.requests:
            self.assertEqual(request['state']['repository']['name'], 'demo')
            self.assertTrue(all(REPOSITORY_GUARD in q['instructions'] for q in request['questions'].values()))
        self.assertEqual(result['repository']['name'], 'demo')
        self.assertNotEqual(result['input_sha256'], route(issue, call=FakeJev())['input_sha256'])

    def test_without_repository_requests_are_unchanged(self):
        jev = FakeJev()
        result = route({'title': 'Task', 'body': 'Scoped edit'}, call=jev)
        self.assertNotIn('repository', jev.requests[0]['state'])
        self.assertNotIn('repository', result)
        self.assertFalse(any(REPOSITORY_GUARD in q['instructions'] for q in jev.requests[0]['questions'].values()))

    def test_abstention_names_the_missing_context(self):
        class Vague(FakeJev):
            def __call__(self, request):
                response = super().__call__(request)
                for key in ('context_goal', 'context_completion'):
                    answer = response['answers'][key]
                    answer['choice'] = 'missing'
                    answer['probabilities'] = {'stated': 0.0, 'missing': 1.0}
                return response

        jev = Vague(insufficient=True)
        result = route({'body': 'なんとなく遅いので直したい'}, call=jev, repository={'name': 'demo'})
        self.assertEqual(len(jev.requests), 1)
        self.assertEqual(result['missing_context'], ['goal', 'completion'])
        self.assertNotIn('context_goal', result['assessment'])
        text = render(result)
        self.assertIn(CONTEXT_HINTS['goal'], text)
        self.assertIn(CONTEXT_HINTS['completion'], text)
        self.assertNotIn(CONTEXT_HINTS['target'], text)
        self.assertIn('英字の語', text)

    def test_missing_refinements_do_not_block_a_provisional_selection(self):
        class FeatureRequest(FakeJev):
            def __call__(self, request):
                response = super().__call__(request)
                if 'context_completion' in response['answers']:
                    answer = response['answers']['context_completion']
                    answer['choice'] = 'missing'
                    answer['probabilities'] = {'stated': 0.0, 'missing': 1.0}
                return response

        jev = FeatureRequest(insufficient=True)
        result = route({'body': 'お知らせ機能が欲しい。管理画面から設定したい'}, call=jev)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(jev.requests[1]['state']['missing_context'], ['completion'])
        text = render(result)
        self.assertIn('暫定の選定です', text)
        self.assertIn(CONTEXT_HINTS['completion'], text)

    def test_oversized_or_invalid_snapshot_is_rejected(self):
        for repository in ({}, 'text', {'paths': ['x' * 61000]}):
            with self.assertRaises(RouterError):
                route({'body': 'Scoped edit'}, call=FakeJev(), repository=repository)

    @patch('issue_router.cli.route')
    @patch('issue_router.cli.snapshot', return_value={'name': 'demo'})
    def test_cli_repo_flag(self, inspect, select):
        select.return_value = route({'body': 'Scoped edit'}, call=FakeJev())
        with patch('builtins.print'):
            self.assertEqual(cli.main(['--text', 'Scoped edit', '--repo', '/tmp/demo']), 0)
        self.assertEqual(inspect.call_args.args[0], '/tmp/demo')
        self.assertEqual(select.call_args.kwargs['repository'], {'name': 'demo'})


if __name__ == '__main__':
    unittest.main()
