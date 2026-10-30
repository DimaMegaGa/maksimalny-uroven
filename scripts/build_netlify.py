"""Publish only frontend files after checking the independently hosted API."""
import json
import os
from pathlib import Path
import shutil
import ssl
import tempfile
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def api_origin(value):
    origin = value.strip().rstrip('/')
    parts = urlsplit(origin)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or
            origin != 'https://' + parts.netloc or parts.hostname in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('MAKS_API_ORIGIN: нужен публичный HTTPS origin без пути, параметров и пароля')
    return origin


def main():
    origin = api_origin(os.environ.get('MAKS_API_ORIGIN', ''))
    site = os.environ.get('MAKS_SITE', 'school')
    if site not in ('school', 'ministry'):
        raise ValueError('MAKS_SITE: school или ministry')
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    request = urllib.request.Request(origin + '/api/health', headers={'serveo-skip-browser-warning': 'true'})
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        health = json.load(response)
    if health.get('app') != 'maks-local-sqlite' or health.get('site') != site:
        raise ValueError('API недоступен или относится к другому порталу')
    destination = (ROOT / 'netlify-dist').resolve()
    if destination.parent != ROOT or destination.is_symlink():
        raise ValueError('Небезопасный каталог сборки')
    with tempfile.TemporaryDirectory(prefix='.netlify-build-', dir=ROOT) as directory:
        staging = Path(directory) / 'site'
        staging.mkdir()
        for source in (ROOT / 'frontend').iterdir():
            if source.is_file() and source.suffix in ('.css', '.js', '.svg'):
                shutil.copy2(source, staging / source.name)
        (staging / 'assets').mkdir()
        for source in (ROOT / 'frontend/assets').glob('*.png'):
            shutil.copy2(source, staging / 'assets' / source.name)
        shutil.copy2(ROOT / 'frontend' / ('ministry.html' if site == 'ministry' else 'index.html'), staging / 'index.html')
        (staging / 'site-config.js').write_text('window.MAKS_SITE=' + json.dumps(site) + ';', encoding='utf-8')
        (staging / '_headers').write_text('/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n  Cache-Control: no-cache\n', encoding='utf-8')
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(staging, destination)
    print('Netlify frontend prepared; API health and site verified:', site)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Netlify build stopped: ' + str(error)) from None
