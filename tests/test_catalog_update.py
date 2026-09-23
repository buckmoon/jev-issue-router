import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from issue_router import catalog_update as cu
from issue_router.core import RouterError, load_catalog, route, validate_catalog
from test_router import FakeJev

WATCH = json.loads(cu.WATCH.read_text(encoding='utf-8'))
LATER = 1893456000  # 2030-01-01, after any catalog verification date
EARLIER = 1577836800  # 2020-01-01


def listing():
    """Synthetic provider lists: every catalog ID plus new, legacy, snapshot and non-text models."""
    catalog = load_catalog()
    lists = {p: [{'id': m['id'], 'created': EARLIER} for m in catalog['models'] if m['provider'] == p]
             for p in ('openai', 'claude', 'grok')}
    lists['openai'] += [{'id': 'gpt-7-nova', 'created': LATER}, {'id': 'gpt-7-nova-2030-01-01', 'created': LATER},
                        {'id': 'gpt-7-realtime', 'created': LATER}, {'id': 'gpt-4o', 'created': EARLIER},
                        {'id': 'text-embedding-9', 'created': LATER}]
    lists['claude'] = [{'id': m['id'] + '-20260101', 'created_at': '2026-01-01T00:00:00Z'} for m in
                       catalog['models'] if m['provider'] == 'claude']
    lists['claude'].append({'id': 'claude-opus-6', 'created_at': '2030-01-02T00:00:00Z'})
    return lists


class FakeProviders:
    def __init__(self, lists, fail=()):
        self.lists, self.fail, self.calls = lists, set(fail), []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        provider = next(p for p, (u, _) in cu.ENDPOINTS.items() if url.startswith(u.split('?')[0]))
        if provider in self.fail:
            raise RouterError('HTTP 401; response body omitted')
        return {'data': self.lists[provider], 'has_more': False}


KEYS = {'OPENAI_API_KEY': 'sk-test', 'ANTHROPIC_API_KEY': 'ak-test', 'XAI_API_KEY': 'xk-test'}


class CompareTests(unittest.TestCase):
    def test_only_new_text_models_after_verification_are_proposed(self):
        report = cu.compare(load_catalog(), WATCH, listing())
        self.assertEqual([n['id'] for n in report['openai']['new']], ['gpt-7-nova'])
        self.assertEqual([n['id'] for n in report['claude']['new']], ['claude-opus-6'])
        self.assertEqual(report['grok']['new'], [])
        # Dated Anthropic snapshots count as their alias being listed.
        self.assertEqual(report['claude']['missing'], [])

    def test_missing_models_are_reported_not_removed(self):
        lists = listing()
        lists['grok'] = []
        report = cu.compare(load_catalog(), WATCH, lists)
        self.assertEqual(report['grok']['missing'], ['grok-4.6'])
        updated = cu.apply(load_catalog(), WATCH, report, '2030-01-03')
        self.assertTrue(next(m for m in updated['models'] if m['id'] == 'grok-4.6')['enabled'])

    def test_ignored_ids_are_not_proposed(self):
        watch = dict(WATCH, ignored=['gpt-7-nova'])
        self.assertEqual(cu.compare(load_catalog(), watch, listing())['openai']['new'], [])

    def test_apply_adds_disabled_placeholders_that_routing_never_offers(self):
        catalog = load_catalog()
        updated = cu.apply(catalog, WATCH, cu.compare(catalog, WATCH, listing()), '2030-01-03')
        added = [m for m in updated['models'] if m['id'] in ('gpt-7-nova', 'claude-opus-6')]
        self.assertEqual(len(added), 2)
        self.assertTrue(all(not m['enabled'] and m['selection_guidance'].startswith(cu.UNREVIEWED) for m in added))
        self.assertEqual(updated['version'], '2030-01-03.1')
        self.assertEqual(updated['verified_at'], catalog['verified_at'])
        fake = FakeJev()
        route({'body': 'Scoped edit'}, catalog=updated, call=fake)
        offered = ' '.join(fake.requests[1]['questions']['openai']['criteria'])
        self.assertNotIn('gpt-7-nova', offered)
        self.assertIsNone(cu.apply(catalog, WATCH, {'openai': {'new': [], 'missing': []}}, '2030-01-03'))

    def test_unreviewed_entry_cannot_be_enabled(self):
        catalog = load_catalog()
        updated = cu.apply(catalog, WATCH, cu.compare(catalog, WATCH, listing()), '2030-01-03')
        next(m for m in updated['models'] if m['id'] == 'gpt-7-nova')['enabled'] = True
        with self.assertRaises(RouterError):
            validate_catalog(updated)

    def test_anthropic_pagination(self):
        pages = [{'data': [{'id': 'claude-a'}], 'has_more': True, 'last_id': 'claude-a'},
                 {'data': [{'id': 'claude-b'}], 'has_more': False}]
        urls = []

        def fetch(url, headers):
            urls.append(url)
            self.assertEqual(headers['x-api-key'], 'k')
            return pages[len(urls) - 1]
        self.assertEqual([m['id'] for m in cu.list_models('claude', 'k', fetch)], ['claude-a', 'claude-b'])
        self.assertIn('after_id=claude-a', urls[1])


class MainTests(unittest.TestCase):
    def test_default_paths_are_the_checkout_not_the_installed_package(self):
        repo = Path(__file__).resolve().parent.parent
        self.assertEqual(cu.CATALOG, repo / 'issue_router' / 'catalog.json')
        self.assertEqual(cu.IOS_CATALOG, repo / 'ios' / 'JevIssueRouter' / 'Resources' / 'catalog.json')

    def run_main(self, argv, fetch, environ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, ios = root / 'catalog.json', root / 'ios' / 'catalog.json'
            ios.parent.mkdir()
            original = cu.CATALOG.read_text(encoding='utf-8')
            catalog.write_text(original, encoding='utf-8')
            ios.write_text(original, encoding='utf-8')
            summary = root / 'summary.md'
            with patch.object(cu, 'CATALOG', catalog), patch.object(cu, 'IOS_CATALOG', ios), \
                    patch('builtins.print') as printed:
                code = cu.main([*argv, '--summary', str(summary)], fetch=fetch, environ=environ, today='2030-01-03')
            return code, json.loads(catalog.read_text()), json.loads(ios.read_text()), \
                summary.read_text() if summary.exists() else '', printed

    def test_write_updates_engine_and_ios_catalogs_identically(self):
        code, engine, ios, summary, _ = self.run_main(['--write'], FakeProviders(listing()), KEYS)
        self.assertEqual(code, 0)
        self.assertEqual(engine, ios)
        self.assertIn('gpt-7-nova', {m['id'] for m in engine['models']})
        self.assertIn('無効', summary)

    def test_check_without_write_changes_nothing(self):
        _, engine, _, summary, _ = self.run_main([], FakeProviders(listing()), KEYS)
        self.assertEqual(engine, load_catalog())
        self.assertIn('gpt-7-nova', summary)

    def test_failed_or_unconfigured_provider_is_skipped_without_secrets(self):
        fetch = FakeProviders(listing(), fail={'claude'})
        code, engine, _, summary, printed = self.run_main(
            ['--write'], fetch, {'OPENAI_API_KEY': 'sk-test', 'ANTHROPIC_API_KEY': 'ak-test'})
        self.assertEqual(code, 0)
        self.assertIn('XAI_API_KEY 未設定', summary)
        self.assertIn('HTTP 401', summary)
        self.assertNotIn('claude-opus-6', {m['id'] for m in engine['models']})
        output = summary + ' '.join(str(c) for c in printed.call_args_list)
        for key in ('sk-test', 'ak-test'):
            self.assertNotIn(key, output)

    def test_no_keys_is_an_error(self):
        code, *_ = self.run_main(['--write'], FakeProviders(listing()), {})
        self.assertEqual(code, 1)


if __name__ == '__main__':
    unittest.main()
