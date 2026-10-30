"""Temporary HTTPS showcase with a separate fictional school database."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'runtime' / 'showcase'
STATE = DATA / 'status.json'
STOP = DATA / 'stop'
BINARY = ROOT / 'tools' / 'cloudflared.exe'


def seed():
    os.environ['MAKS_DB_PATH'] = str(DATA / 'maks.sqlite3')
    sys.path.insert(0, str(ROOT / 'backend'))
    from repository import repository
    access = DATA / 'PRIVATE_ACCESS.md'
    if access.exists():
        return
    with repository.connection() as c:
        if c.execute('SELECT count(*) FROM directors').fetchone()[0]:
            raise RuntimeError('Incomplete showcase initialization; preserve this database and inspect it before retrying.')
    school = 'Школа открытий № 30'
    did, dc = repository.bootstrap_director([school], 'Директор школы открытий')
    ds, dt = repository.login(dict(role='director', code=dc))
    _, mc = repository.bootstrap_ministry('Оператор образовательной платформы')
    _, mt = repository.login(dict(role='ministry', code=mc))
    packet = repository.ministry_import(mt, dict(directorId=did,
        organizationId=ds['admin']['organizations'][0]['id'], title='Доступ участников школы открытий',
        csv='ФИО;Роль;Класс\nИванова Анна Сергеевна;учитель;\nПетров Алексей Дмитриевич;ученик;8А\n'))
    rows = repository.package_action(mt, {'packageId': packet['packageId']}, 'open')['rows']
    repository.package_action(mt, {'packageId': packet['packageId']}, 'send')
    teacher, student = rows
    ts, tt = repository.login(dict(role='teacher', name=teacher['name'], code=teacher['code']))
    _, st = repository.login(dict(role='student', name=student['name'], code=student['code']))
    def commit(token, changes):
        state = repository.get_snapshot(token)
        return repository.apply_changes(token, state['revision'], changes)
    user = next(u for u in ts['db']['users'] if u['id'] == teacher['id'])
    commit(tt, {'users': [dict(user, subjects=['Математика', 'История'])]})
    for i, title in enumerate(['Симметрия в архитектуре города', 'Математическая викторина', 'История нашей школы']):
        task = dict(id=str(uuid.uuid4()), title=title,
            description='Исследуйте тему, приведите примеры и сформулируйте собственные выводы.',
            instructions='Подготовьте работу. Объясните ход рассуждений. Приложите результат.',
            subject='История' if i == 2 else 'Математика', points=25,
            deadline=(date.today()+timedelta(days=30)).isoformat(), targetType='class', target='8А')
        commit(tt, {'tasks': [task]})
        if i < 2:
            answer = dict(id=str(uuid.uuid4()), taskId=task['id'], userId=student['id'],
                review='Подготовил исследование и сформулировал выводы.', photos=[], status='pending')
            commit(st, {'submissions': [answer]})
            commit(tt, {'submissions': [dict(answer, status='approved' if i == 0 else 'rejected',
                reviewOutcome='approved' if i == 0 else 'revision',
                teacherComment='Отличная работа!' if i == 0 else 'Добавьте примеры и поясните выводы.')]})
    text = '# Доступ для показа\n\nТолько вымышленные участники; не использовать реальные персональные данные.\n\n'
    for label, name, code in [('Министерство', '', mc), ('Директор', '', dc),
                               ('Учитель', teacher['name'], teacher['code']), ('Ученик', student['name'], student['code'])]:
        text += f'{label}: {name}\n\nКод: `{code}`\n\n'
    access.write_text(text, encoding='utf-8')


def controller():
    children, streams = [], []
    state = {'status': 'starting'}
    def save():
        temporary = STATE.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        temporary.replace(STATE)
    try:
        seed()
        save()
        for site, port in [('school', 8885), ('ministry', 8887)]:
            log = DATA / f'{site}-tunnel.log'
            log.write_text('', encoding='utf-8')
            stream = (DATA / f'{site}-tunnel-console.log').open('ab')
            streams.append(stream)
            tunnel = subprocess.Popen([str(BINARY), 'tunnel', '--url', f'http://127.0.0.1:{port}',
                '--protocol', 'http2', '--no-autoupdate', '--logfile', str(log)],
                stdout=stream, stderr=stream, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            children.append(tunnel)
            url = None
            for _ in range(90):
                if STOP.exists() or tunnel.poll() is not None:
                    raise RuntimeError('Tunnel stopped before its URL was assigned')
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', log.read_text(encoding='utf-8', errors='replace'))
                if match:
                    url = match[0]
                    break
                time.sleep(1)
            if not url:
                raise RuntimeError('Cloudflare did not return a URL; see tunnel logs')
            environment = os.environ.copy()
            environment['MAKS_PUBLIC_ORIGIN'] = url
            stream = (DATA / f'{site}-server.log').open('ab')
            streams.append(stream)
            children.append(subprocess.Popen([sys.executable, '-u', str(ROOT / 'backend/server.py'),
                '--site', site, '--port', str(port)], env=environment, stdout=stream, stderr=stream,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
            state[site] = url
            save()
        for site, port in [('school', 8885), ('ministry', 8887)]:
            for attempt in range(30):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
                        if json.load(response)['site'] == site:
                            break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError('Showcase server did not start')
        state['status'] = 'checking-https'
        save()
        for attempt in range(24):
            online = []
            for site in ('school', 'ministry'):
                try:
                    with urllib.request.urlopen(state[site] + '/api/health', timeout=4) as response:
                        online.append(json.load(response).get('site') == site)
                except (OSError, ValueError):
                    online.append(False)
            if all(online):
                break
            if STOP.exists() or any(child.poll() is not None for child in children):
                raise RuntimeError('Tunnel connection failed; inspect local logs')
            time.sleep(2)
        else:
            raise RuntimeError('External HTTPS health check failed; URLs are not ready')
        state['status'] = 'ready'
        while not STOP.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A showcase process stopped; inspect local logs')
            state['heartbeat'] = time.time()
            save()
            time.sleep(2)
    except Exception as error:
        state.update(status='error', error=str(error))
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
        for stream in streams:
            stream.close()
        if state['status'] != 'error':
            state['status'] = 'stopped'
        save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if args.stop:
        STOP.touch()
        print('Остановка показа запрошена. Основные локальные сайты не затрагиваются.')
        return
    if args.serve:
        controller()
        return
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf-8'))
        if state.get('status') == 'ready' and time.time()-state.get('heartbeat', 0) < 15:
            print('Школа:', state['school'], '\nМинистерство:', state['ministry'])
            return
    if not BINARY.exists():
        raise SystemExit('Нужен официальный cloudflared: tools/cloudflared.exe. См. SHOWCASE-HTTPS.md.')
    STOP.unlink(missing_ok=True)
    STATE.write_text(json.dumps({'status': 'starting'}), encoding='utf-8')
    with (DATA / 'controller.log').open('ab') as stream:
        child = subprocess.Popen([sys.executable, '-u', str(Path(__file__)), '--serve'], cwd=ROOT,
            stdout=stream, stderr=stream, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(420):
        if STATE.exists():
            state = json.loads(STATE.read_text(encoding='utf-8'))
            if state.get('status') == 'ready':
                print('Школа:', state['school'], '\nМинистерство:', state['ministry'])
                print('Доступы сохранены только локально:', DATA / 'PRIVATE_ACCESS.md')
                return
            if state.get('status') == 'error':
                raise SystemExit(state['error'])
        if child.poll() is not None:
            raise SystemExit('Показ не запустился. См. runtime/showcase/controller.log')
        time.sleep(1)
    raise SystemExit('Запуск продолжается; проверьте runtime/showcase/status.json')


if __name__ == '__main__':
    main()
