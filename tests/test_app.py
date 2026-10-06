import json
import os
from pathlib import Path
import plistlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from issue_router import app
from issue_router.core import RouterError, route
from issue_router.evaluators import make_evaluator
from test_router import FakeJev

ACCOUNT = '0123456789abcdef0123456789abcdef'  # obviously fake
TOKEN = 'cf_example_not_a_real_token'


class PrivateSettings:
    """Point the settings file at a temporary directory so tests never read the user's own."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings_file = Path(directory.name) / 'settings.json'
        patcher = patch('issue_router.app.settings_path', return_value=self.settings_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()


class HandleRouteTests(PrivateSettings, unittest.TestCase):
    def test_text_with_context(self):
        seen = {}

        def fake_route(issue, **options):
            seen.update(issue=issue, options=options)
            return route(issue, call=FakeJev())

        output = app.handle_route({'body': 'Scoped edit', 'context': 'One file', 'policy': 'value'}, fake_route)
        self.assertEqual(output['result']['status'], 'selected')
        self.assertEqual(seen['issue']['context'], 'One file')
        self.assertEqual(seen['options']['policy'], 'value')
        self.assertIn(output['result']['status'], json.dumps(output['result']))

    def test_repository_snapshot_is_passed_to_the_engine(self):
        seen = {}

        def fake_route(issue, **options):
            seen.update(options)
            return route(issue, call=FakeJev(), repository=options['repository'])

        def inspect(path, text):
            return {'name': 'demo', 'path_seen': path, 'text_seen': 'Scoped edit' in text}

        output = app.handle_route({'body': 'Scoped edit', 'repo': ' /tmp/demo '}, fake_route, inspect=inspect)
        self.assertEqual(seen['repository'], {'name': 'demo', 'path_seen': '/tmp/demo', 'text_seen': True})
        self.assertIn('リポジトリ: demo', output['text'])
        app.handle_route({'body': 'Scoped edit'}, fake_route, inspect=lambda *a: self.fail('must not inspect'))
        self.assertIsNone(seen['repository'])

    def test_requires_exactly_one_source(self):
        for data in ({}, {'url': 'https://github.com/o/r/issues/1', 'body': 'x'}):
            with self.assertRaises(RouterError):
                app.handle_route(data, lambda *a, **k: self.fail('must not route'))

    def test_rejects_malformed_key_before_keychain(self):
        with patch('issue_router.app.sys.platform', 'darwin'), patch('issue_router.app.subprocess.run') as run:
            for key in ('', 'short', 'has space inside', 'quote"inside-key'):
                with self.assertRaises(RouterError):
                    app.save_key(key)
            run.assert_not_called()

    def test_saved_state_reads_attributes_only(self):
        output = 'keychain: "login"\n    "mdat"<timedate>=0x32  "20260920011500Z\\000"\n    "svce"<blob>="x"\n'
        with patch('issue_router.app.sys.platform', 'darwin'), patch('issue_router.app.subprocess.run') as run:
            run.return_value = Mock(returncode=0, stdout=output)
            exists, saved_at = app.keychain_entry()
            self.assertNotIn('-w', run.call_args.args[0])
            run.return_value = Mock(returncode=44, stdout='')
            self.assertEqual(app.keychain_entry(), (False, None))
        self.assertTrue(exists)
        self.assertRegex(saved_at, r'^2026-09-(19|20|21) \d\d:\d\d$')

    def test_connectivity_check_sends_no_user_input_and_explains_failures(self):
        requests = []

        def ok(request):
            requests.append(request)
            return {'model': 'jev-test', 'answers': {'ok': {}}}

        self.assertEqual(app.check_connection(make_evaluator(), ok)['models'], ['jev-test'])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['state'], {'text': 'ping'})
        cases = {'Jev HTTP 401; response body omitted': '拒否', 'Jev HTTP 429; response body omitted': '利用制限',
                 'Jev network/timeout/JSON error; no recommendation generated': '接続できません',
                 'Set TYPESAFE_API_KEY securely, or register': 'TYPESAFE_API_KEY'}
        for raised, expected in cases.items():
            with self.assertRaises(RouterError) as caught:
                app.check_connection(make_evaluator(), Mock(side_effect=RouterError(raised)))
            self.assertIn(expected, str(caught.exception))
            self.assertTrue(str(caught.exception).startswith('NG'))

    def test_connectivity_check_sends_once_per_distinct_clef_model(self):
        for assess, expected in ((None, ['clef']), ('clef-flash', ['clef-flash', 'clef'])):
            requests = []

            def ok(request):
                requests.append(request)
                return {'model': request['model'], 'answers': {'ok': {}}}

            evaluator = make_evaluator('clef', account_id=ACCOUNT, clef_assess_model=assess, environ={})
            with self.subTest(assess=assess):
                self.assertEqual(app.check_connection(evaluator, ok)['models'], expected)
                self.assertEqual([r['model'] for r in requests], expected)
                self.assertTrue(all(r['state'] == {'text': 'ping'} for r in requests))

    def test_connectivity_check_names_clef(self):
        workers = make_evaluator('clef', account_id=ACCOUNT, environ={})
        local = make_evaluator('clef', clef_host='local', environ={})
        cases = [(workers, 'Clef HTTP 403; response body omitted', ['拒否', 'Clef HTTP 403', 'Workers AI']),
                 (workers, 'Clef HTTP 429; response body omitted', ['Clef HTTP 429']),
                 (workers, 'Clef HTTP 500; response body omitted', ['Clef APIがエラー']),
                 (workers, 'Clef request failed (Cloudflare error codes [5006]); response body omitted', ['5006']),
                 (workers, 'Clef network/timeout/JSON error; no recommendation generated', ['Clef APIに接続できません']),
                 (local, 'Clef network/timeout/JSON error; no recommendation generated', ['Clefサーバー', 'ollama pull'])]
        for evaluator, raised, expected in cases:
            with self.subTest(raised=raised, host=evaluator.host), self.assertRaises(RouterError) as caught:
                app.check_connection(evaluator, Mock(side_effect=RouterError(raised)))
            message = str(caught.exception)
            self.assertTrue(message.startswith('NG'))
            self.assertNotIn('Jev', message)
            for text in expected:
                self.assertIn(text, message)
        with self.assertRaisesRegex(RouterError, 'Clef APIの応答形式'):
            app.check_connection(workers, lambda request: {'model': 'clef'})

    def test_route_uses_saved_evaluator_settings(self):
        seen = {}

        def fake_route(issue, **options):
            seen.update(options)
            return route(issue, call=FakeJev(), evaluator=options['evaluator'])

        app.save_settings({'evaluator': 'clef', 'cloudflare_account_id': ACCOUNT,
                           'clef_model': 'clef', 'clef_assess_model': 'clef-flash'})
        output = app.handle_route({'body': 'Scoped edit'}, fake_route)
        self.assertEqual(seen['evaluator'].models, {'assess': 'clef-flash', 'select': 'clef'})
        self.assertIn('評価モデル: Clef (workers-ai / clef-flash → clef)', output['text'])

    def test_invalid_saved_settings_fail_before_github(self):
        self.settings_file.write_text(json.dumps({'evaluator': 'clef', 'cloudflare_account_id': 'bad'}))
        with self.assertRaisesRegex(RouterError, 'CLOUDFLARE_ACCOUNT_ID'):
            app.handle_route({'url': 'https://github.com/o/r/issues/1'}, lambda *a, **k: self.fail('must not route'),
                             fetch=lambda url: self.fail('must not fetch'))

    def test_settings_round_trip_is_private_and_holds_no_token(self):
        self.assertEqual(app.load_settings(), app.SETTINGS_DEFAULTS)
        saved = app.save_settings({'evaluator': 'clef', 'clef_host': 'local', 'clef_model': ' clef:27b-q8_0 ',
                                   'clef_assess_model': 'clef-flash', 'clef_url': 'https://gpu.example.test/v1/systemone',
                                   'cloudflare_api_token': TOKEN, 'key': TOKEN})
        self.assertEqual(saved['clef_model'], 'clef:27b-q8_0')
        self.assertEqual(app.load_settings(), saved)
        self.assertEqual(set(saved), set(app.SETTINGS_DEFAULTS))
        self.assertEqual(self.settings_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(TOKEN, self.settings_file.read_text(encoding='utf-8'))
        app.save_draft({'body': ''}, self.settings_file.with_name('draft.json'))  # clearing the draft keeps settings
        self.assertEqual(app.load_settings(), saved)

    def test_invalid_settings_are_rejected_and_not_saved(self):
        app.save_settings({'evaluator': 'jev'})
        before = self.settings_file.read_text(encoding='utf-8')
        for data in ({'evaluator': 'bogus'}, {'evaluator': 'clef', 'cloudflare_account_id': 'short'},
                     {'evaluator': 'clef', 'cloudflare_account_id': ACCOUNT, 'clef_model': 'clef-mega'},
                     {'evaluator': 'clef', 'clef_host': 'local', 'clef_url': 'http://10.0.0.5:11434/v1/systemone'},
                     {'evaluator': 'clef', 'clef_host': 'mars'}, {'evaluator': 5}, ['jev']):
            with self.subTest(data=data), self.assertRaises(RouterError):
                app.save_settings(data)
        self.assertEqual(self.settings_file.read_text(encoding='utf-8'), before)
        self.settings_file.write_text('not json', encoding='utf-8')
        self.assertEqual(app.load_settings(), app.SETTINGS_DEFAULTS)

    def test_clef_token_goes_to_its_own_keychain_service(self):
        with patch('issue_router.app.sys.platform', 'darwin'), \
                patch('issue_router.app.keychain_has_key', return_value=True) as has, \
                patch('issue_router.app.subprocess.run') as run:
            run.return_value.returncode = 0
            app.save_key(TOKEN, 'clef')
        self.assertIn('-s local.clef.cloudflare ', run.call_args.kwargs['input'])
        self.assertNotIn(TOKEN, ' '.join(run.call_args.args[0]))
        has.assert_called_with('clef')
        with self.assertRaises(RouterError):
            app.save_key(TOKEN, 'other')
        with patch('issue_router.app.sys.platform', 'linux'), self.assertRaisesRegex(RouterError, 'CLOUDFLARE_API_TOKEN'):
            app.save_key(TOKEN, 'clef')

    def test_keychain_status_per_service(self):
        with patch('issue_router.app.sys.platform', 'darwin'), patch('issue_router.app.subprocess.run') as run, \
                patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN': TOKEN}):
            run.return_value = Mock(returncode=44, stdout='')
            status = app.key_status('clef')
            self.assertIn('local.clef.cloudflare', run.call_args.args[0])
        self.assertEqual(status, {'env': True, 'keychain': False, 'saved_at': None})

    def test_draft_round_trip_is_private_and_excludes_everything_else(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state' / 'draft.json'
            app.save_draft({'body': 'お知らせ機能', 'repo': '/tmp/demo', 'policy': 'value',
                            'key': 'ts_example_not_a_real_key', 'url': 5}, path)
            self.assertEqual(app.load_draft(path), {'body': 'お知らせ機能', 'repo': '/tmp/demo', 'policy': 'value'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('ts_example', path.read_text(encoding='utf-8'))
            app.save_draft({'body': '  ', 'policy': 'value'}, path)
            self.assertFalse(path.exists())
            self.assertEqual(app.load_draft(path), {})
            path.write_text('not json', encoding='utf-8')
            self.assertEqual(app.load_draft(path), {})

    def test_key_goes_to_stdin_not_argv(self):
        with patch('issue_router.app.sys.platform', 'darwin'), \
                patch('issue_router.app.keychain_has_key', return_value=True), \
                patch('issue_router.app.subprocess.run') as run:
            run.return_value.returncode = 0
            app.save_key('ts_example_not_a_real_key')
        self.assertNotIn('ts_example_not_a_real_key', ' '.join(run.call_args.args[0]))
        self.assertIn('ts_example_not_a_real_key', run.call_args.kwargs['input'])


class InstallTests(unittest.TestCase):
    def test_refuses_to_replace_a_foreign_bundle(self):
        with tempfile.TemporaryDirectory() as directory, patch('issue_router.app.sys.platform', 'darwin'), \
                patch('issue_router.app.subprocess.run') as run:
            (Path(directory) / f'{app.APP_NAME}.app').mkdir()
            run.return_value.returncode = 1
            with self.assertRaises(RouterError):
                app.install_mac_app(directory)
            self.assertTrue((Path(directory) / f'{app.APP_NAME}.app').exists())

    def test_launcher_is_a_compiled_applet_with_its_own_window(self):
        sources = []

        def fake_run(command, **kwargs):
            if command[0] == '/usr/bin/osacompile':
                sources.append(Path(command[-1]).read_text(encoding='utf-8'))
                contents = Path(command[command.index('-o') + 1]) / 'Contents'
                contents.mkdir(parents=True)
                (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'applet'}))
            return Mock(returncode=0)

        with tempfile.TemporaryDirectory() as directory, patch('issue_router.app.sys.platform', 'darwin'), \
                patch('issue_router.app.subprocess.run', side_effect=fake_run) as run:
            bundle = app.install_mac_app(directory)
            info = plistlib.loads((bundle / 'Contents' / 'Info.plist').read_bytes())
        self.assertEqual([call.args[0][0] for call in run.call_args_list],
                         ['/usr/bin/osacompile', '/usr/bin/codesign'])
        self.assertIn('WKWebView', sources[0])
        self.assertIn('-m issue_router.app', sources[0])
        self.assertNotIn('__COMMAND__', sources[0])
        self.assertEqual(info['CFBundleIdentifier'], app.BUNDLE_ID)
        self.assertTrue(info['NSAppTransportSecurity']['NSAllowsLocalNetworking'])

    def test_window_mode_never_idles_out(self):
        with patch('issue_router.app.process_alive', return_value=True):
            self.assertTrue(app.keep_running(0, 123, now=app.IDLE_SECONDS * 100))
        with patch('issue_router.app.process_alive', return_value=False):
            self.assertFalse(app.keep_running(0, 123, now=1))
        self.assertTrue(app.keep_running(0, None, now=app.IDLE_SECONDS - 1))
        self.assertFalse(app.keep_running(0, None, now=app.IDLE_SECONDS + 1))

    def test_server_follows_the_window_process(self):
        self.assertTrue(app.process_alive(None))
        self.assertTrue(app.process_alive(os.getpid()))
        with patch('issue_router.app.os.kill', side_effect=ProcessLookupError):
            self.assertFalse(app.process_alive(12345))


class ServerTests(PrivateSettings, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.make_handler('tok', {'seen': 0}))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, path, headers):
        request = urllib.request.Request(self.base + path, data=b'{}', headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_token_and_host_are_required(self):
        self.assertEqual(self.post('/api/ping', {'X-App-Token': 'tok'}), 200)
        self.assertEqual(self.post('/api/ping', {}), 403)
        self.assertEqual(self.post('/api/ping', {'X-App-Token': 'tok', 'Host': 'evil.example'}), 403)

    def call(self, path, data=None, token='tok', method='POST'):
        body = None if method == 'GET' else json.dumps(data or {}).encode()
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers={'X-App-Token': token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code, None

    def test_settings_api_round_trip(self):
        self.assertEqual(self.call('/api/settings', method='GET'), (200, {'settings': app.SETTINGS_DEFAULTS}))
        self.assertEqual(self.call('/api/settings', method='GET', token='nope')[0], 403)
        status, body = self.call('/api/settings', {'settings': {'evaluator': 'clef', 'cloudflare_account_id': ACCOUNT,
                                                                'clef_model': 'clef-flash', 'token': TOKEN}})
        self.assertEqual((status, body['settings']['clef_model']), (200, 'clef-flash'))
        self.assertEqual(self.call('/api/settings', method='GET')[1], body)
        self.assertNotIn(TOKEN, self.settings_file.read_text(encoding='utf-8'))
        status, body = self.call('/api/settings', {'settings': {'evaluator': 'clef', 'cloudflare_account_id': 'x'}})
        self.assertIn('CLOUDFLARE_ACCOUNT_ID', body['error'])
        self.assertEqual(self.call('/api/settings')[1]['settings']['clef_model'], 'clef-flash')

    def test_status_reports_both_services_and_settings(self):
        with patch('issue_router.app.keychain_entry', return_value=(False, None)) as entry:
            status, body = self.call('/api/status')
        self.assertEqual(set(body), {'jev', 'clef', 'settings'})
        self.assertEqual({c.args[0] for c in entry.call_args_list}, {'jev', 'clef'})

    def test_check_uses_saved_evaluator(self):
        app.save_settings({'evaluator': 'clef', 'clef_host': 'local', 'clef_model': 'clef', 'clef_assess_model': 'clef-flash'})
        sent = []

        def fake_call(evaluator, request):
            sent.append((evaluator.host, request['model']))
            return {'model': request['model'], 'answers': {}}

        with patch('issue_router.evaluators.Evaluator.call', fake_call):
            status, body = self.call('/api/check')
        self.assertEqual(body['models'], ['clef-flash', 'clef'])
        self.assertEqual(sent, [('local', 'clef-flash'), ('local', 'clef')])

    def test_key_api_routes_service(self):
        with patch('issue_router.app.save_key') as save:
            self.call('/api/key', {'service': 'clef', 'key': TOKEN})
            self.call('/api/key', {'key': TOKEN})
        self.assertEqual([c.args[1] for c in save.call_args_list], ['clef', 'jev'])

    def test_page_shows_each_destination_notice(self):
        with urllib.request.urlopen(self.base + '/', timeout=5) as response:
            page = response.read().decode()
        for notice in app.NOTICES.values():
            self.assertIn(notice, page)
        self.assertIn('Clef（Cloudflare Workers AI）', page)
        self.assertIn('Clef（このMac内のサーバー）', page)
        self.assertNotIn('__NOTICES__', page)

    def test_page_never_contains_key_material(self):
        with urllib.request.urlopen(self.base + '/', timeout=5) as response:
            page = response.read().decode()
        self.assertIn('Jev Issue Router', page)
        self.assertNotIn('__TOKEN__', page)


if __name__ == '__main__':
    unittest.main()
