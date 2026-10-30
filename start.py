"""Double-click start.cmd on Windows. No packages required."""
import json
import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765'


def running(port=8765, site='school'):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
            health = json.load(response)
            return health.get('app') == 'maks-local-sqlite' and health.get('site') == site
    except (OSError, ValueError):
        return False


def ensure_server(site, port):
    if not running(port, site):
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise SystemExit(f'Port {port} is busy or running an old version. Run stop.cmd before restarting.')
        logs = ROOT / 'logs'
        logs.mkdir(exist_ok=True)
        log = logs / (site + '-server.log')
        with log.open('ab') as stream:
            proc = subprocess.Popen([sys.executable, '-u', str(ROOT / 'backend' / 'server.py'), '--site', site, '--port', str(port)], cwd=ROOT,
                                    stdout=stream, stderr=stream, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(50):
            if running(port, site):
                (ROOT / ('server.pid' if site == 'school' else 'ministry-server.pid')).write_text(str(proc.pid), encoding='ascii')
                break
            if proc.poll() is not None:
                raise SystemExit(f'Server failed. See {log}')
            time.sleep(.1)
        else:
            raise SystemExit(f'Server did not respond. See {log}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--site', choices=('all','school','ministry'), default='all')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    for site, port in [('school',8765),('ministry',8767)]:
        if args.site not in ('all', site):
            continue
        ensure_server(site, port)
        url = f'http://127.0.0.1:{port}'
        print(site + ': ' + url)
        if not args.no_browser:
            webbrowser.open(url)
