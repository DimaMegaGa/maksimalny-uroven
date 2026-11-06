"""Experimental WSGI entry point for an isolated hosting-lab copy only."""

import argparse
import io
import json
import os
from pathlib import Path
from email.message import Message
from types import SimpleNamespace
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

database = Path(os.environ['MAKS_DB_PATH']).resolve()
key = Path(os.environ['MAKS_VAULT_KEY_FILE']).resolve()
database.parent.mkdir(parents=True, exist_ok=True)
key.parent.mkdir(parents=True, exist_ok=True)
try:
    descriptor = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    Fernet(key.read_bytes().strip())
else:
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(Fernet.generate_key())

from server import Handler, FRONTEND


class WSGIHandler(Handler):
    def __init__(self, environ, site, path, body):
        self.server = SimpleNamespace(site=site, server_port=int(environ.get('SERVER_PORT', '443')))
        self.client_address = (environ.get('REMOTE_ADDR', '127.0.0.1'), 0)
        self.directory = str(FRONTEND)
        self.command = environ['REQUEST_METHOD']
        self.path = path + ('?' + environ['QUERY_STRING'] if environ.get('QUERY_STRING') else '')
        self.request_version = 'HTTP/1.1'
        self.requestline = self.command + ' ' + self.path + ' HTTP/1.1'
        self.close_connection = True
        self.headers = Message()
        for name, value in environ.items():
            if name.startswith('HTTP_'):
                self.headers[name[5:].replace('_', '-')] = value
        if environ.get('CONTENT_TYPE'):
            self.headers['Content-Type'] = environ['CONTENT_TYPE']
        self.headers['Content-Length'] = str(len(body))
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        if self.command == 'GET':
            self.do_GET()
        elif self.command == 'HEAD':
            self.do_HEAD()
        elif self.command == 'POST':
            self.do_POST()
        else:
            self.send_error(405)


def application(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    if path == '/ministry':
        start_response('302 Found', [('Location', '/ministry/'), ('Content-Length', '0')])
        return [b'']
    ministry = path.startswith('/ministry/')
    prefix = '/ministry' if ministry else ''
    path = path[len(prefix) :] if prefix else path
    if path == '/api/shutdown':
        start_response('403 Forbidden', [('Content-Type', 'application/json')])
        return [b'{"error":"Unavailable in WSGI"}']
    try:
        size = int(environ.get('CONTENT_LENGTH') or '0')
    except ValueError:
        size = -1
    if not 0 <= size <= 12_000_000:
        start_response('413 Content Too Large', [('Content-Type', 'application/json')])
        return [b'{"error":"Request too large"}']
    body = environ['wsgi.input'].read(size)
    handler = WSGIHandler(environ, 'ministry' if ministry else 'school', path, body)
    raw = handler.wfile.getvalue()
    header, payload = raw.split(b'\r\n\r\n', 1)
    lines = header.decode('iso-8859-1').split('\r\n')
    status = lines[0].split(' ', 1)[1]
    headers = [tuple(line.split(': ', 1)) for line in lines[1:]]
    if ministry and path == '/site-config.js':
        payload += b"\nwindow.MAKS_API_BASE='/ministry/api/';\n"
    if ministry:
        headers = [
            (
                name,
                (
                    value.replace('Path=/', 'Path=/ministry/')
                    if name.lower() == 'set-cookie'
                    else value
                ),
            )
            for name, value in headers
        ]
    headers = [
        (name, value)
        for name, value in headers
        if name.lower() not in ('content-length', 'connection', 'transfer-encoding')
    ]
    headers.append(('Content-Length', str(len(payload))))
    start_response(status, headers)
    return [payload]


if __name__ == '__main__':
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    make_server('127.0.0.1', args.port, application, handler_class=Quiet).serve_forever()
