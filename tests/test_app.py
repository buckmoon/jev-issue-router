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
from test_router import FakeJev


class HandleRouteTests(unittest.TestCase):
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

        self.assertEqual(app.check_key(ok)['model'], 'jev-test')
        self.assertEqual(requests[0]['state'], {'text': 'ping'})
        cases = {'Jev HTTP 401; response body omitted': '拒否', 'Jev HTTP 429; response body omitted': '利用制限',
                 'Jev network/timeout/JSON error; no recommendation generated': '接続できません',
                 'Set TYPESAFE_API_KEY securely, or register': 'TYPESAFE_API_KEY'}
        for raised, expected in cases.items():
            with self.assertRaises(RouterError) as caught:
                app.check_key(Mock(side_effect=RouterError(raised)))
            self.assertIn(expected, str(caught.exception))
            self.assertTrue(str(caught.exception).startswith('NG'))

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


class ServerTests(unittest.TestCase):
    def setUp(self):
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

    def test_page_never_contains_key_material(self):
        with urllib.request.urlopen(self.base + '/', timeout=5) as response:
            page = response.read().decode()
        self.assertIn('Jev Issue Router', page)
        self.assertNotIn('__TOKEN__', page)


if __name__ == '__main__':
    unittest.main()
