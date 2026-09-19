import copy
import threading
import unittest
from unittest.mock import patch

from issue_router.core import RouterError, load_catalog, normalize_issue, route, render
from issue_router.github import fetch_issue, parse_url
from issue_router.slack import handle_command


class FakeJev:
    def __init__(self, insufficient=False, corrupt=False):
        self.requests = []
        self.insufficient = insufficient
        self.corrupt = corrupt

    def __call__(self, request):
        self.requests.append(request)
        answers = {}
        for key, question in request['questions'].items():
            choices = list(question['criteria'])
            choice = choices[0]
            if key == 'readiness' and self.insufficient:
                choice = 'insufficient'
            if key in ('openai', 'claude', 'grok'):
                choice = choices[1]
            answers[key] = {'type': 'choice', 'choice': choice, 'confidence': 0.9,
                            'probabilities': {c: float(c == choice) for c in choices}}
        if self.corrupt:
            answers[next(iter(answers))]['choice'] = 'fabricated-model'
        return {'model': 'test-jev', 'answers': answers, 'usage': {'input_tokens': 10, 'output_tokens': 5}}


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.issue = {'title': 'Change button label', 'body': 'Save to Save changes; update UI test'}

    def test_two_stage_selection_and_valid_parameters(self):
        fake = FakeJev()
        result = route(self.issue, call=fake)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(set(result['recommendations']), {'openai', 'claude', 'grok'})
        self.assertEqual(len(result['jev_calls']), 2)
        self.assertIn('assessment', fake.requests[1]['state'])
        self.assertIn('confidence', render(result))
        catalog = {m['id']: m for m in load_catalog()['models']}
        for rec in result['recommendations'].values():
            self.assertIn(rec['effort'], catalog[rec['model']]['efforts'])
        self.assertEqual(result['recommendations']['claude']['api_parameters']['thinking'], {'type': 'adaptive'})

    def test_insufficient_context_stops_second_call(self):
        fake = FakeJev(insufficient=True)
        result = route(self.issue, call=fake)
        self.assertEqual(result['status'], 'needs_context')
        self.assertEqual(len(fake.requests), 1)
        self.assertFalse(result['recommendations'])

    def test_invalid_choice_fails_closed(self):
        with self.assertRaises(RouterError):
            route(self.issue, call=FakeJev(corrupt=True))

    def test_missing_probability_fails_closed(self):
        fake = FakeJev()
        def corrupt(request):
            response = fake(request)
            response['answers']['readiness']['probabilities'].pop('insufficient')
            return response
        with self.assertRaises(RouterError):
            route(self.issue, call=corrupt)

    def test_no_candidates_returns_provider_abstention(self):
        catalog = copy.deepcopy(load_catalog())
        for model in catalog['models']:
            if model['provider'] == 'grok':
                model['enabled'] = False
        fake = FakeJev()
        def reply(request):
            if 'grok' not in request['questions']:
                return fake(request)
            subset = copy.deepcopy(request)
            del subset['questions']['grok']
            response = fake(subset)
            response['answers']['grok'] = {'type': 'choice', 'choice': 'needs_context',
                'confidence': 1, 'probabilities': {'needs_context': 1}}
            return response
        result = route(self.issue, catalog=catalog, call=reply)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['recommendations']['grok']['status'], 'needs_context')

    def test_input_limits_and_fields(self):
        for issue in ({}, {'body': 'x' * 60001}, {'body': ['invalid']}):
            with self.assertRaises(RouterError):
                normalize_issue(issue)
        self.assertNotIn('secret', normalize_issue({**self.issue, 'secret': 'not sent'}))

    def test_github_url_validation(self):
        self.assertEqual(parse_url('https://github.com/a/b/issues/123'), ('a/b', 123))
        for url in ('https://evil.test/a/b/issues/1', 'https://github.com/a/b/issues/1?x=y',
                    'https://github.com/a/b/pull/1', 'https://github.com/a/b/issues/1;echo'):
            with self.assertRaises(RouterError):
                parse_url(url)

    @patch('issue_router.github.gh')
    def test_repo_allowlist_precedes_fetch(self, gh):
        with self.assertRaises(RouterError):
            fetch_issue('https://github.com/a/b/issues/1', allowed_repos={'a/c'})
        gh.assert_not_called()

    @patch('issue_router.github.gh', return_value={'pull_request': {}})
    def test_pr_rejected(self, gh):
        with self.assertRaises(RouterError):
            fetch_issue('https://github.com/a/b/issues/1')

    def test_slack_ack_before_io_and_ephemeral_result(self):
        events, responses = [], []
        def fetch(url, allowed_repos):
            self.assertEqual(events, ['ack'])
            self.assertEqual(allowed_repos, {'a/b'})
            return self.issue
        handle_command(lambda: events.append('ack'), lambda **kw: responses.append(kw),
            {'user_id': 'U1', 'text': 'https://github.com/a/b/issues/1'},
            allowed_users={'U1'}, allowed_repos={'a/b'}, gate=threading.BoundedSemaphore(1),
            fetch=fetch, select=lambda issue: route(issue, call=FakeJev()))
        self.assertEqual(responses[0]['response_type'], 'ephemeral')

    def test_unauthorized_slack_user_cannot_read_github(self):
        def fetch(*args, **kwargs):
            self.fail('Unauthorized fetch')
        responses = []
        handle_command(lambda: None, lambda **kw: responses.append(kw), {'user_id': 'U2'},
            allowed_users={'U1'}, allowed_repos={'a/b'}, gate=threading.BoundedSemaphore(1), fetch=fetch)
        self.assertEqual(len(responses), 1)

    def test_api_error_produces_no_fallback(self):
        def unavailable(request):
            raise RouterError('Jev unavailable')
        with self.assertRaisesRegex(RouterError, 'unavailable'):
            route(self.issue, call=unavailable)


if __name__ == '__main__':
    unittest.main()
