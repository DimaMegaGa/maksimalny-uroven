"""Check tunnel request boundaries without real credentials or database access."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

TEMP = tempfile.TemporaryDirectory()
os.environ.setdefault('MAKS_DB_PATH', str(Path(TEMP.name) / 'test.sqlite3'))
import server


class PublicOriginTests(unittest.TestCase):
    def test_public_origin_and_cookies(self):
        with patch.object(server, 'PUBLIC_ORIGIN', 'https://showcase.example'), patch.object(
                server.repository, 'login', return_value=({'userId': 'fictional'}, 'fake-session')):
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            def post(origin, host='showcase.example', path='/api/login'):
                headers = {'Host': host, 'X-Maks-Request': '1', 'Content-Type': 'application/json'}
                if origin is not None:
                    headers['Origin'] = origin
                request = urllib.request.Request(f'http://127.0.0.1:{http.server_port}'+path,
                    data=json.dumps({'role': 'student'}).encode(), headers=headers)
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
                self.assertEqual(post('https://attacker.example')[0], 403)
                self.assertEqual(post('https://showcase.example.attacker.example')[0], 403)
                self.assertEqual(post(None)[0], 403)
                self.assertEqual(post('https://showcase.example', host='attacker.example')[0], 403)
                self.assertEqual(post('https://showcase.example', path='/api/shutdown')[0], 403)
                self.assertEqual(post('https://showcase.example', host=f'127.0.0.1:{http.server_port}')[0], 403)
            finally:
                http.shutdown()
                http.server_close()


if __name__ == '__main__':
    unittest.main()
