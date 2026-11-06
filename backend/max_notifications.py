"""Explicit MAX subscriptions and a transactional queue for school notifications."""

from contextlib import closing
import hashlib
import hmac
from urllib.parse import parse_qsl
import json
import secrets
import sqlite3
import time
import uuid

from access_control import BackendError


def install(c):
    statements = [
        '''CREATE TABLE IF NOT EXISTS max_links (
            user_id TEXT PRIMARY KEY REFERENCES users(id), binding_id TEXT NOT NULL UNIQUE,
            max_user_id INTEGER NOT NULL UNIQUE, chat_id INTEGER NOT NULL UNIQUE,
            linked_at INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS max_pairings (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            expires_at INTEGER NOT NULL, consumed_binding TEXT)''',
        '''CREATE TABLE IF NOT EXISTS max_outbox (
            id TEXT PRIMARY KEY, notification_id TEXT NOT NULL UNIQUE REFERENCES notifications(id),
            user_id TEXT NOT NULL REFERENCES users(id), binding_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            due_at INTEGER NOT NULL, lease TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
            sent_at INTEGER, error TEXT)''',
        'CREATE INDEX IF NOT EXISTS max_outbox_due ON max_outbox(state,due_at)',
        '''CREATE TRIGGER IF NOT EXISTS max_notification_enqueue AFTER INSERT ON notifications
            BEGIN
              INSERT OR IGNORE INTO max_outbox(id,notification_id,user_id,binding_id,due_at)
              SELECT NEW.id,NEW.id,NEW.user_id,binding_id,CAST(strftime('%s','now') AS INTEGER)
              FROM max_links WHERE user_id=NEW.user_id;
            END''',
    ]
    for statement in statements:
        c.execute(statement)
    if 'expected_max_user' not in {row[1] for row in c.execute('PRAGMA table_info(max_pairings)')}:
        c.execute('ALTER TABLE max_pairings ADD COLUMN expected_max_user INTEGER')


def launch_identity(raw, config, now=None):
    """Authenticate messenger identity; never grant school access from launch data."""
    if not raw:
        return None
    try:
        if not isinstance(raw, str) or len(raw) > 16384:
            raise ValueError()
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError()
        signature = data.pop('hash')
        key = hmac.new(b'WebAppData', config['token'].encode(), hashlib.sha256).digest()
        expected = hmac.new(key, '\n'.join(k + '=' + v for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        age = (int(time.time()) if now is None else now) - int(data['auth_date'])
        user_id = json.loads(data['user'])['id']
        if age < -60 or age > 28800 or type(user_id) is not int or user_id <= 0:
            raise ValueError()
        return user_id
    except (ValueError, KeyError, TypeError):
        raise BackendError('Не удалось подтвердить аккаунт MAX. Закройте мини-приложение и откройте его заново.', 403) from None


def settings(repository, token, max_user_id=None):
    with repository.connection() as c:
        actor = repository.actor(c, token)
        if actor['role'] not in ('student', 'teacher'):
            return {'available': False, 'connected': False, 'failed': 0}
        linked = c.execute('SELECT linked_at,max_user_id FROM max_links WHERE user_id=?', (actor['id'],)).fetchone()
        failed = c.execute("SELECT COUNT(*) FROM max_outbox WHERE user_id=? AND state='failed'",
                           (actor['id'],)).fetchone()[0]
    try:
        from max_bot import load_config
        load_config()
        available = True
    except Exception:
        available = False
    return {'available': available, 'connected': bool(linked) and (max_user_id is None or linked['max_user_id'] == max_user_id),
            'differentAccount': bool(linked) and max_user_id is not None and linked['max_user_id'] != max_user_id, 'failed': failed}


def begin_pairing(repository, token, config, max_user_id=None):
    raw = secrets.token_urlsafe(32)
    now = int(time.time())
    with repository.connection() as c:
        actor = repository.actor(c, token)
        if actor['role'] not in ('student', 'teacher'):
            raise BackendError('Подключение доступно учителям и ученикам.', 403)
        linked = c.execute('SELECT max_user_id FROM max_links WHERE user_id=?', (actor['id'],)).fetchone()
        if linked and (max_user_id is None or linked['max_user_id'] == max_user_id):
            raise BackendError('Уведомления уже подключены. Сначала отключите прежнюю привязку.')
        c.execute('DELETE FROM max_pairings WHERE user_id=? OR expires_at<?', (actor['id'], now))
        c.execute('INSERT INTO max_pairings(token_hash,user_id,expires_at,consumed_binding,expected_max_user) VALUES(?,?,?,NULL,?)',
                  (hashlib.sha256(raw.encode()).hexdigest(), actor['id'], now + 300, max_user_id))
    return {'url': 'https://max.ru/' + config['username'] + '?start=notify_' + raw,
            'command': '/start notify_' + raw, 'expiresIn': 300}


def finish_pairing(database, payload, max_user_id, chat_id, now=None):
    now = int(time.time()) if now is None else now
    if (not isinstance(payload, str) or not payload.startswith('notify_')
            or len(payload) != 50 or type(max_user_id) is not int or max_user_id <= 0
            or type(chat_id) is not int):
        return 'Ссылка подключения недействительна. Создайте новую в профиле платформы.'
    digest = hashlib.sha256(payload[7:].encode()).hexdigest()
    with closing(sqlite3.connect(database, timeout=12)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM max_pairings WHERE token_hash=?', (digest,)).fetchone()
        if not row or row['expires_at'] < now:
            return 'Срок ссылки истёк. Откройте профиль платформы и подключите уведомления заново.'
        if not c.execute('SELECT 1 FROM account_access WHERE user_id=? AND active=1', (row['user_id'],)).fetchone():
            return 'Школьная учётная запись недоступна. Обратитесь к ответственному в школе.'
        if row['expected_max_user'] is not None and row['expected_max_user'] != max_user_id:
            return 'Откройте ссылку в том аккаунте MAX, из которого подключали уведомления.'
        if row['consumed_binding']:
            same = c.execute('SELECT 1 FROM max_links WHERE binding_id=? AND max_user_id=? AND chat_id=?',
                             (row['consumed_binding'], max_user_id, chat_id)).fetchone()
            return ('Уведомления MAX подключены. Можно вернуться в платформу.' if same else
                    'Эта ссылка уже использована. Создайте новую в своём профиле платформы.')
        exists = c.execute('SELECT 1 FROM max_links WHERE (max_user_id=? OR chat_id=?) AND user_id<>?',
                           (max_user_id, chat_id, row['user_id'])).fetchone()
        previous = c.execute('SELECT 1 FROM max_links WHERE user_id=?', (row['user_id'],)).fetchone()
        if previous and row['expected_max_user'] is None:
            exists = True
        if exists:
            return 'Этот MAX или школьный профиль уже связан с другой учётной записью. Сначала отключите прежнюю привязку в профиле платформы.'
        if previous:
            c.execute('DELETE FROM max_links WHERE user_id=?', (row['user_id'],))
            c.execute("UPDATE max_outbox SET state='cancelled',lease=NULL WHERE user_id=? AND state IN ('pending','sending','failed')", (row['user_id'],))
        binding = str(uuid.uuid4())
        c.execute('INSERT INTO max_links VALUES(?,?,?,?,?)',
                  (row['user_id'], binding, max_user_id, chat_id, now))
        c.execute('UPDATE max_pairings SET consumed_binding=? WHERE token_hash=?', (binding, digest))
    return 'Уведомления MAX подключены. Сюда будут приходить новые задания, результаты проверки и решения по обмену баллов. Отключить их можно в профиле платформы или командой /stop.'


def disconnect_in(c, user_id):
    c.execute('DELETE FROM max_links WHERE user_id=?', (user_id,))
    c.execute('DELETE FROM max_pairings WHERE user_id=?', (user_id,))
    c.execute("UPDATE max_outbox SET state='cancelled',lease=NULL WHERE user_id=? AND state IN ('pending','sending','failed')", (user_id,))


def disconnect(repository, token):
    with repository.connection() as c:
        actor = repository.actor(c, token)
        disconnect_in(c, actor['id'])
    return {'connected': False}


def stop_from_bot(database, max_user_id, chat_id):
    with closing(sqlite3.connect(database, timeout=12)) as c, c:
        row = c.execute('SELECT user_id FROM max_links WHERE max_user_id=? AND chat_id=?',
                        (max_user_id, chat_id)).fetchone()
        if row:
            disconnect_in(c, row[0])


def test_delivery(repository, token, max_user_id=None):
    with repository.connection() as c:
        actor = repository.actor(c, token)
        linked = c.execute('SELECT max_user_id FROM max_links WHERE user_id=?', (actor['id'],)).fetchone()
        if not linked:
            raise BackendError('Сначала подключите уведомления MAX.')
        if max_user_id is not None and linked['max_user_id'] != max_user_id:
            raise BackendError('Уведомления связаны с другим аккаунтом MAX. Подключите текущий аккаунт в профиле.', 409)
        if c.execute("SELECT 1 FROM notifications WHERE user_id=? AND type='max-test' AND created_at>?",
                     (actor['id'], int(time.time() * 1000) - 60000)).fetchone():
            raise BackendError('Проверка уже отправлена. Повторить можно через минуту.', 429)
        repository.notice(c, actor['id'], 'max-test', 'Уведомления MAX работают',
                          'Проверочное сообщение школьной платформы. Подключение выполнено успешно.',
                          'profile', 'max-test:' + str(uuid.uuid4()))
        repository.bump(c)
    return {'queued': True}


def message(c, row, config):
    title = row['title'][:200]
    detail = row['text'][:700]
    parts = row['event_id'].split(':')
    context = None
    if len(parts) > 1:
        if parts[0] == 'task':
            context = c.execute('SELECT subject,title FROM tasks WHERE id=?', (parts[1],)).fetchone()
        elif parts[0] in ('approved', 'revision', 'pending', 'submission'):
            context = c.execute('SELECT t.subject,t.title FROM tasks t JOIN submissions s ON s.task_id=t.id WHERE s.id=?', (parts[1],)).fetchone()
    text = title + ('\n' + ' · '.join(context) if context else '') + ('\n\n' + detail if detail else '')
    button = {'type': 'link', 'text': 'Открыть платформу', 'url': config['site_url']}
    if config.get('webapp_registered') is True:
        button = {'type': 'open_app', 'text': 'Открыть платформу', 'web_app': config['username']}
    return {'text': text, 'notify': True,
            'attachments': [{'type': 'inline_keyboard', 'payload': {'buttons': [[button]]}}]}


def deliver(database, config, sender, limit=20, clock=time.time, pause=time.sleep):
    """Run as a short scheduled task; a failed MAX request never rolls back school work."""
    sent = 0
    for _ in range(limit):
        now = int(clock())
        lease = secrets.token_hex(16)
        with closing(sqlite3.connect(database, timeout=12)) as c, c:
            c.row_factory = sqlite3.Row
            c.execute('BEGIN IMMEDIATE')
            c.execute("UPDATE max_outbox SET state='pending',lease=NULL WHERE state='sending' AND lease_until<?", (now,))
            c.execute("UPDATE max_outbox SET state='cancelled' WHERE state='pending' AND NOT EXISTS (SELECT 1 FROM max_links l WHERE l.user_id=max_outbox.user_id AND l.binding_id=max_outbox.binding_id)")
            row = c.execute("SELECT o.id,o.binding_id,o.user_id,n.title,n.text,n.event_id,l.chat_id FROM max_outbox o JOIN max_links l ON l.user_id=o.user_id AND l.binding_id=o.binding_id JOIN account_access a ON a.user_id=o.user_id AND a.active=1 JOIN notifications n ON n.id=o.notification_id WHERE o.state='pending' AND o.due_at<=? ORDER BY o.due_at,o.id LIMIT 1", (now,)).fetchone()
            if not row:
                break
            body = message(c, row, config)
            c.execute("UPDATE max_outbox SET state='sending',lease=?,lease_until=?,attempts=attempts+1 WHERE id=?", (lease, now + 90, row['id']))
        try:
            # Recheck opt-out immediately before sending an already claimed job.
            with closing(sqlite3.connect(database, timeout=12)) as c:
                active = c.execute('SELECT 1 FROM max_links WHERE user_id=? AND binding_id=?',
                                   (row['user_id'], row['binding_id'])).fetchone()
            if not active:
                continue
            sender(config, 'POST', '/messages?chat_id=' + str(row['chat_id']), body)
        except Exception:
            with closing(sqlite3.connect(database, timeout=12)) as c, c:
                c.execute("UPDATE max_outbox SET state=CASE WHEN attempts>=6 THEN 'failed' ELSE 'pending' END,due_at=?,lease=NULL,error='MAX delivery failed' WHERE id=? AND lease=? AND state='sending'",
                          (now + 60 * 2 ** min(5, c.execute('SELECT attempts FROM max_outbox WHERE id=?', (row['id'],)).fetchone()[0]), row['id'], lease))
            break
        else:
            with closing(sqlite3.connect(database, timeout=12)) as c, c:
                c.execute("UPDATE max_outbox SET state='sent',sent_at=?,lease=NULL,error=NULL WHERE id=? AND lease=? AND state='sending'", (int(clock()), row['id'], lease))
            sent += 1
            pause(0.6)
    return sent
