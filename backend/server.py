"""Локальная HTTP-оболочка. Python 3.11+. Дополнительные пакеты не нужны.
SQLite подключена. Запуск предназначен только для локального тестирования.
"""
import argparse
import json
import os
import secrets
import hmac
import threading
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from repository import BackendError, repository

FRONTEND = Path(__file__).resolve().parent.parent / 'frontend'
CONTROL = repository.path.parent / 'server-control.json'
CONTROL_TOKEN = secrets.token_urlsafe(32)
PUBLIC_ICONS = {'/assets/' + path.name for path in (FRONTEND / 'assets').glob('*.png')}
PUBLIC_ORIGIN = os.environ.get('MAKS_PUBLIC_ORIGIN', '').rstrip('/')
if PUBLIC_ORIGIN and (urlsplit(PUBLIC_ORIGIN).scheme != 'https' or
                      PUBLIC_ORIGIN != 'https://' + urlsplit(PUBLIC_ORIGIN).netloc or
                      urlsplit(PUBLIC_ORIGIN).username):
    raise ValueError('MAKS_PUBLIC_ORIGIN must be an exact HTTPS origin')


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def log_message(self, *args):
        pass  # Не записываем имена и коды в журнал.

    def end_headers(self):
        path = urlsplit(self.path).path
        if not path.startswith('/api/') and path != '/site-config.js':
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    @property
    def site(self):
        return getattr(self.server, 'site', 'school')

    @property
    def cookie_name(self):
        name = 'maks_ministry_session' if self.site == 'ministry' else 'maks_session'
        default_port = 8767 if self.site == 'ministry' else 8765
        return name if self.server.server_port == default_port else f'{name}_{self.server.server_port}'

    def token(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie[self.cookie_name].value if self.cookie_name in cookie else ''
        except Exception:
            return ''

    def check_site_session(self):
        with repository.connection() as c:
            actor = repository.actor(c, self.token())
        if (actor['role'] == 'ministry') != (self.site == 'ministry'):
            raise BackendError('Войдите в аккаунт на соответствующем сайте', 401)

    def translate_path(self, path):
        if self.site == 'ministry' and urlsplit(path).path in ('/', '/index.html'):
            return str(FRONTEND / 'ministry.html')
        return super().translate_path(path)

    def reply(self, status, payload, cookie=None):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_head(self):
        path = urlsplit(self.path).path
        if path not in ('/', '/index.html', '/style.css', '/server-design.css', '/refinements.css', '/responsive.css', '/access.css', '/ministry-site.css', '/presentation.css', '/favicon.svg', '/app.js', '/director.js', '/ministry.js') and path not in PUBLIC_ICONS:
            self.send_error(404)
            return None
        return super().send_head()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/health':
            self.reply(200, {'app': 'maks-local-sqlite', 'site': self.site})
        elif path == '/site-config.js':
            data = ('window.MAKS_SITE=' + json.dumps(self.site) + ';').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/api/state':
            try:
                self.check_site_session()
                self.reply(200, repository.get_snapshot(self.token()))
            except BackendError as error:
                self.reply(error.status, {'error': str(error)})
            except Exception:
                self.reply(500, {'error': 'Ошибка сервера'})
        elif path.startswith('/api/'):
            self.reply(404, {'error': 'Маршрут не найден'})
        else:
            super().do_GET()

    def do_POST(self):
        try:
            host = self.headers.get('Host')
            public = bool(PUBLIC_ORIGIN and host == urlsplit(PUBLIC_ORIGIN).netloc)
            if not public and host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                raise BackendError('Недопустимый адрес сервера', 403)
            origin = self.headers.get('Origin')
            if (public and origin != PUBLIC_ORIGIN or
                    not public and origin and origin not in (f'http://{host}', f'https://{host}')):
                raise BackendError('Недопустимый источник запроса', 403)
            if self.headers.get('X-Maks-Request') != '1':
                raise BackendError('Недопустимый запрос', 403)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 12_000_000:
                raise BackendError('Неверный размер запроса', 413)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise BackendError('Ожидается JSON-объект')
            path = urlsplit(self.path).path
            if public and path == '/api/shutdown':
                raise BackendError('Остановка доступна только локально', 403)
            if self.site != 'ministry' and (path.startswith('/api/ministry/') or path == '/api/packages/send'):
                raise BackendError('Эта функция доступна на сайте министерства', 404)
            if self.site == 'ministry' and (path.startswith('/api/director/') or path in ('/api/commit', '/api/packages/distribute')):
                raise BackendError('Эта функция доступна на школьном сайте', 404)
            if path not in ('/api/login', '/api/logout', '/api/shutdown'):
                self.check_site_session()
            if path == '/api/login':
                if (body.get('role') == 'ministry') != (self.site == 'ministry'):
                    raise BackendError('Используйте отдельный сайт министерства' if self.site == 'school' else 'Здесь доступен только вход министерства', 403)
                snapshot, token = repository.login(body, client=self.client_address[0])
                secure = '; Secure' if public or os.environ.get('MAKS_SECURE_COOKIE') == '1' else ''
                max_age = 28800 if body.get('role') in ('director', 'ministry') else 604800
                self.reply(200, snapshot, f'{self.cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}' + secure)
            elif path == '/api/director/accounts':
                self.reply(200, repository.director_create_account(self.token(), body))
            elif path == '/api/director/reissue-code':
                self.reply(200, repository.director_reissue_code(self.token(), body))
            elif path in ('/api/ministry/preview', '/api/ministry/import'):
                self.reply(200, repository.ministry_import(self.token(), body, preview=path.endswith('/preview')))
            elif path == '/api/ministry/reissue':
                self.reply(200, repository.ministry_reissue(self.token(), body))
            elif path in ('/api/packages/open', '/api/packages/send', '/api/packages/distribute'):
                self.reply(200, repository.package_action(self.token(), body, path.rsplit('/', 1)[1]))
            elif path == '/api/commit':
                self.reply(200, repository.apply_changes(self.token(), body.get('revision'), body.get('changes')))
            elif path == '/api/logout':
                repository.logout(self.token())
                self.reply(200, {}, f'{self.cookie_name}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            elif path == '/api/shutdown':
                if not hmac.compare_digest(str(body.get('controlToken', '')), CONTROL_TOKEN):
                    raise BackendError('Недопустимый запрос остановки', 403)
                self.reply(200, {})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.reply(404, {'error': 'Маршрут не найден'})
        except BackendError as error:
            self.reply(error.status, {'error': str(error)})
        except (ValueError, TypeError):
            self.reply(400, {'error': 'Некорректный запрос'})
        except Exception:
            self.reply(500, {'error': 'Ошибка сервера'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--site', choices=('school', 'ministry'), default='school')
    args = parser.parse_args()
    print(f'Откройте http://127.0.0.1:{args.port}')
    print('Локальная SQLite подключена. Для остановки нажмите Ctrl+C.')
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.site = args.site
    if args.site == 'ministry':
        CONTROL = repository.path.parent / 'ministry-server-control.json'
    CONTROL.parent.mkdir(parents=True, exist_ok=True)
    CONTROL.write_text(json.dumps({'port': args.port, 'token': CONTROL_TOKEN, 'pid': os.getpid()}), encoding='utf-8')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
