"""Check tunnel request boundaries without real credentials or database access."""

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import urllib.request
import urllib.error

TEMP = tempfile.TemporaryDirectory()
os.environ.setdefault('MAKS_DB_PATH', str(Path(TEMP.name) / 'test.sqlite3'))
import server


class PublicOriginTests(unittest.TestCase):
    def test_local_copy_session_isolation(self):
        handler = object.__new__(server.Handler)
        handler.server = SimpleNamespace(site='school', server_port=8765)
        self.assertEqual(handler.cookie_name, 'maks_session')
        handler.server.server_port = 8885
        self.assertEqual(handler.cookie_name, 'maks_session_8885')
        handler.server = SimpleNamespace(site='ministry', server_port=8767)
        self.assertEqual(handler.cookie_name, 'maks_ministry_session')
        handler.server.server_port = 8887
        self.assertEqual(handler.cookie_name, 'maks_ministry_session_8887')

    def test_embedded_partitioned_session(self):
        handler = object.__new__(server.Handler)
        handler.server = SimpleNamespace(site='school', server_port=443)
        handler.headers = {'X-Maks-Embedded': '1'}
        with patch.object(server, 'PUBLIC_ORIGIN', 'https://showcase.example'):
            cookie = handler.session_cookie('example-session', 604800)
            self.assertTrue(cookie.startswith('__Host-maks_embedded='))
            for attribute in ('HttpOnly', 'SameSite=None', 'Secure', 'Partitioned', 'Path=/'):
                self.assertIn(attribute, cookie)
            self.assertNotIn('Domain=', cookie)
            self.assertIn('Max-Age=0', handler.session_cookie('', 0))
            handler.headers = {'Cookie': '__Host-maks_embedded=example-session'}
            self.assertEqual(handler.token(), 'example-session', 'private images need the partitioned session')
            self.assertIn('SameSite=Strict', handler.session_cookie('ordinary', 604800))
            handler.server.site = 'ministry'
            handler.headers['X-Maks-Embedded'] = '1'
            self.assertIn('SameSite=Strict', handler.session_cookie('ministry', 28800))
            self.assertEqual(handler.token(), '', 'school cookie cannot grant ministry access')
        handler.server.site = 'school'
        handler.server.server_port = 8765
        with patch.object(server, 'PUBLIC_ORIGIN', ''), patch.dict(server.os.environ, {'MAKS_SECURE_COOKIE': '0'}):
            self.assertFalse(handler.embedded_session)
            self.assertIn('SameSite=Strict', handler.session_cookie('local', 604800))

    def test_public_origin_and_cookies(self):
        with (
            patch.object(server, 'PUBLIC_ORIGIN', 'https://showcase.example'),
            patch.object(
                server.repository, 'login', return_value=({'userId': 'fictional'}, 'fake-session')
            ),
        ):
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()

            def post(origin, host='showcase.example', path='/api/login', embedded=False):
                headers = {'Host': host, 'X-Maks-Request': '1', 'Content-Type': 'application/json'}
                if embedded:
                    headers['X-Maks-Embedded'] = '1'
                if origin is not None:
                    headers['Origin'] = origin
                request = urllib.request.Request(
                    f'http://127.0.0.1:{http.server_port}' + path,
                    data=json.dumps({'role': 'student'}).encode(),
                    headers=headers,
                )
                try:
                    with urllib.request.urlopen(request) as response:
                        return response.status, response.headers
                except urllib.error.HTTPError as error:
                    return error.code, error.headers

            try:
                status, headers = post('https://showcase.example')
                self.assertEqual(status, 200)
                self.assertIn('; Secure', headers['Set-Cookie'])
                self.assertIn('; HttpOnly', headers['Set-Cookie'])
                self.assertIn('Partitioned', post('https://showcase.example', embedded=True)[1]['Set-Cookie'])
                self.assertEqual(post('https://attacker.example', embedded=True)[0], 403)
                self.assertEqual(post(None, embedded=True)[0], 403)
                self.assertEqual(post('https://attacker.example')[0], 403)
                self.assertEqual(post('https://showcase.example.attacker.example')[0], 403)
                self.assertEqual(post(None)[0], 403)
                self.assertEqual(post('https://showcase.example', host='attacker.example')[0], 403)
                self.assertEqual(post('https://showcase.example', path='/api/shutdown')[0], 403)
                self.assertEqual(
                    post('https://showcase.example', host=f'127.0.0.1:{http.server_port}')[0], 403
                )
            finally:
                http.shutdown()
                http.server_close()


if __name__ == '__main__':
    unittest.main()
