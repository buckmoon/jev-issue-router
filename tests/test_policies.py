import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from issue_router import action, cli
from issue_router.core import load_catalog, render, route
from issue_router.settings import add_routing_arguments, routing_options
from issue_router.slack import parse_command
from test_router import FakeJev


class EconomicPolicyTests(unittest.TestCase):
    def setUp(self):
        self.issue = {'title': 'Debug intermittent updates', 'body': 'Reproduce stale updates and add a regression test.'}

    def test_distinct_objectives_preserve_assessment_and_two_call_budget(self):
        requests = {}
        scopes = {'value': 'bounded_first_attempt', 'total-cost': 'verified_completion'}
        for policy, scope in scopes.items():
            with self.subTest(policy=policy):
                fake = FakeJev()
                result = route(self.issue, policy=policy, call=fake)
                requests[policy] = fake.requests
                self.assertEqual(len(fake.requests), 2)
                self.assertEqual(len(result['jev_calls']), 2)
                self.assertEqual(fake.requests[1]['state']['policy'], policy)
                for rec in result['recommendations'].values():
                    self.assertEqual(rec['policy_guidance']['recommendation_scope'], scope)
                    self.assertFalse(rec['policy_guidance']['automatic_escalation'])
                    self.assertEqual(rec['policy_guidance']['cost_basis'], 'qualitative_not_measured')
                self.assertIn('定性的', render(result))
        self.assertEqual(requests['value'][0], requests['total-cost'][0])
        self.assertNotEqual(requests['value'][1]['questions'], requests['total-cost'][1]['questions'])

    def test_information_shortage_never_becomes_permission_for_a_cheap_attempt(self):
        for policy in ('value', 'total-cost'):
            fake = FakeJev(insufficient=True)
            result = route(self.issue, policy=policy, call=fake)
            self.assertEqual(result['status'], 'needs_context')
            self.assertEqual(result['recommendations'], {})
            self.assertEqual(len(fake.requests), 1)
            self.assertNotIn('再評価の目安', render(result))

    def test_value_does_not_force_cheapest_when_jev_selects_a_stronger_pair(self):
        fake = FakeJev()
        def choose_stronger(request):
            result = fake(request)
            if 'openai' in request['questions']:
                choice = 'gpt-6-astra__high'
                answer = result['answers']['openai']
                answer['choice'] = choice
                answer['probabilities'] = {k: float(k == choice) for k in answer['probabilities']}
            return result
        result = route(self.issue, policy='value', call=choose_stronger)
        self.assertEqual(result['recommendations']['openai']['model'], 'gpt-6-astra')
        self.assertEqual(result['recommendations']['openai']['effort'], 'high')

    def test_cli_environment_and_slack_accept_both_policies(self):
        for policy in ('value', 'total-cost'):
            with self.subTest(policy=policy), patch.dict(os.environ, {'ISSUE_MODEL_POLICY': policy}):
                parser = argparse.ArgumentParser()
                add_routing_arguments(parser)
                self.assertEqual(routing_options(parser.parse_args([]))['policy'], policy)
                self.assertEqual(parse_command('https://github.com/o/r/issues/1 ' + policy)[1], policy)
                with patch('issue_router.cli.route') as select, contextlib.redirect_stdout(io.StringIO()):
                    select.return_value = route(self.issue, policy=policy, call=FakeJev())
                    self.assertEqual(cli.main(['--text', self.issue['body'], '--policy', policy]), 0)
                    self.assertEqual(select.call_args.kwargs['policy'], policy)

    def test_action_outputs_retain_policy_and_advice_without_posting(self):
        for policy in ('value', 'total-cost'):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                env = {'GITHUB_REPOSITORY': 'o/r', 'ROUTER_ISSUE_NUMBER': '1',
                       'RUNNER_TEMP': directory, 'ISSUE_MODEL_POLICY': policy,
                       'GITHUB_STEP_SUMMARY': directory + '/summary',
                       'GITHUB_OUTPUT': directory + '/output'}
                publish = Mock()
                def select(issue, **options):
                    return route(issue, call=FakeJev(), **options)
                action.run(env, fetch=lambda url: self.issue, select=select, publish=publish)
                publish.assert_not_called()
                outputs = dict(line.split('=', 1) for line in Path(env['GITHUB_OUTPUT']).read_text().splitlines())
                saved = json.loads(Path(outputs['result-path']).read_text())
                self.assertEqual(saved['policy'], policy)
                self.assertIn('policy_guidance', saved['recommendations']['openai'])

    def test_extreme_policies_are_available_everywhere_with_distinct_objectives(self):
        from issue_router.policies import POLICIES, POLICY_DESCRIPTIONS
        self.assertEqual(set(POLICY_DESCRIPTIONS), set(POLICIES))
        questions = {}
        for policy, scope in {'min-cost': 'cheapest_usable_attempt', 'max-quality': 'design_quality'}.items():
            fake = FakeJev()
            result = route(self.issue, policy=policy, call=fake)
            questions[policy] = fake.requests[1]['questions']['claude']['instructions']
            self.assertIn(POLICIES[policy], questions[policy])
            self.assertEqual(result['recommendations']['claude']['policy_guidance']['recommendation_scope'], scope)
            self.assertEqual(parse_command('https://github.com/o/r/issues/1 ' + policy)[1], policy)
        fake = FakeJev()
        result = route(self.issue, policy='max-quality', call=fake)
        offered = {c.split('__')[0] for c in fake.requests[1]['questions']['claude']['criteria'] if '__' in c}
        self.assertEqual(offered, {'claude-fable-5-1'})
        self.assertIn('needs_context', fake.requests[1]['questions']['claude']['criteria'])
        self.assertIn('最上位', render(result))
        fake = FakeJev()
        route(self.issue, policy='min-cost', call=fake)
        criteria = fake.requests[1]['questions']['openai']['criteria']
        openai = [m for m in load_catalog()['models'] if m['provider'] == 'openai' and m.get('enabled', True)]
        self.assertIn(f"model 1 of {len(openai)}", criteria[openai[0]['id'] + '__low'])
        fake = FakeJev()
        route(self.issue, policy='balanced', call=fake)
        self.assertNotIn('Catalog position', fake.requests[1]['questions']['openai']['criteria']['gpt-5.6-luna__low'])
        self.assertIn('定性的', render(route(self.issue, policy='min-cost', call=FakeJev())))
        self.assertNotIn('コストは定性的', render(route(self.issue, policy='max-quality', call=FakeJev())))
        self.assertNotEqual(questions['min-cost'], questions['max-quality'])

    def test_existing_policies_do_not_gain_first_attempt_advice(self):
        for policy in ('balanced', 'quality', 'cost'):
            result = route(self.issue, policy=policy, call=FakeJev())
            self.assertEqual(result['status'], 'selected')
            self.assertNotIn('policy_guidance', result['recommendations']['openai'])


if __name__ == '__main__':
    unittest.main()
