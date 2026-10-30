import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import io

spec = importlib.util.spec_from_file_location('build_netlify', Path(__file__).with_name('build_netlify.py'))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_wrong_portal_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            response = io.BytesIO(json.dumps({'app': 'maks-local-sqlite', 'site': 'ministry'}).encode())
            with patch.object(build, 'ROOT', root), patch.dict(os.environ, {'MAKS_API_ORIGIN': 'https://api.example', 'MAKS_SITE': 'school'}), patch.object(build.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    build.main()
            self.assertFalse((root / 'netlify-dist').exists())

    def test_bad_api_addresses(self):
        for value in ('', 'http://example.org', 'https://user:password@example.org', 'https://example.org/path', 'https://example.org?q=1', 'https://localhost'):
            with self.assertRaises(ValueError):
                build.api_origin(value)

    def test_publish_contains_only_frontend(self):
        for site in ('school', 'ministry'):
            with self.subTest(site=site), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                (root / 'frontend/assets').mkdir(parents=True)
                for name, text in [('index.html', 'school-page'), ('ministry.html', 'ministry-page'), ('app.js', 'script'), ('secret.md', 'do-not-publish')]:
                    (root / 'frontend' / name).write_text(text)
                (root / 'frontend/assets/icon.png').write_bytes(b'fixture')
                (root / 'frontend/assets/secret.key').write_text('do-not-publish')
                (root / 'backend').mkdir()
                (root / 'backend/secret.key').write_text('do-not-publish')
                response = io.BytesIO(json.dumps({'app': 'maks-local-sqlite', 'site': site}).encode())
                with patch.object(build, 'ROOT', root), patch.dict(os.environ, {'MAKS_API_ORIGIN': 'https://api.example', 'MAKS_SITE': site}), patch.object(build.urllib.request, 'urlopen', return_value=response):
                    build.main()
                output = root / 'netlify-dist'
                self.assertEqual((output / 'index.html').read_text(), site + '-page')
                self.assertFalse((output / 'backend').exists())
                self.assertFalse((output / 'secret.md').exists())
                self.assertFalse((output / 'ministry.html').exists())
                self.assertFalse((output / 'assets/secret.key').exists())
                self.assertEqual((output / 'site-config.js').read_text(), 'window.MAKS_SITE=' + json.dumps(site) + ';')


if __name__ == '__main__':
    unittest.main()
