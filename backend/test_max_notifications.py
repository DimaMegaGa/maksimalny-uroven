"""Notification delivery tests use only the test runner's disposable school database."""

import concurrent.futures
import json
import secrets
import tempfile
import threading
import time
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from test_local import LocalTests, repository, BackendError
import max_bot
import max_notifications as notifications

CONFIG = {'username': 'test_school_bot', 'site_url': 'https://school.example/',
          'webapp_registered': True}


class NotificationTests(unittest.TestCase):
    setUpClass = classmethod(LocalTests.setUpClass.__func__)
    tearDownClass = classmethod(LocalTests.tearDownClass.__func__)
    request = LocalTests.request
    make_account = LocalTests.make_account

    def setUp(self):
        suffix = uuid.uuid4().hex[:9]
        self.school = 'Школа уведомлений ' + suffix
        _, state, self.token = self.make_account('student', 'Ученик ' + suffix, self.school, '8А')
        self.user = state['userId']
        # These are fictional MAX identities; sender is replaced in every delivery test.
        self.max_user = secrets.randbelow(1_000_000_000) + 10
        self.chat = -self.max_user
        self.sent = []

    def pairing(self):
        return notifications.begin_pairing(repository, self.token, CONFIG)['command'].split(' ', 1)[1]

    def tearDown(self):
        notifications.disconnect(repository, self.token)

    def connect(self):
        result = notifications.finish_pairing(repository.path, self.pairing(), self.max_user, self.chat)
        self.assertIn('подключены', result)

    def notice(self, event=None):
        with repository.connection() as c:
            repository.notice(c, self.user, 'task', 'Новое задание', 'Исследование', 'tasks', event or uuid.uuid4().hex)

    def count(self, state=None):
        with repository.connection() as c:
            sql = 'SELECT COUNT(*) FROM max_outbox WHERE user_id=?'
            params = (self.user,)
            if state:
                sql += ' AND state=?'
                params += (state,)
            return c.execute(sql, params).fetchone()[0]

    def deliver(self, sender=None, **kwargs):
        return notifications.deliver(repository.path, CONFIG,
                                     sender or (lambda *args: self.sent.append(args)),
                                     pause=lambda _: None, **kwargs)

    def test_other_max_cannot_receive_test_or_claim_pairing(self):
        self.connect()
        other = self.max_user + 1
        with self.assertRaises(BackendError):
            notifications.test_delivery(repository, self.token, other)
        self.assertEqual(self.count(), 0)
        status = notifications.settings(repository, self.token, other)
        self.assertFalse(status['connected'])
        self.assertTrue(status['differentAccount'])
        payload = notifications.begin_pairing(repository, self.token, CONFIG, other)['command'].split(' ', 1)[1]
        self.assertIn('том аккаунте', notifications.finish_pairing(repository.path, payload, self.max_user, self.chat))
        self.assertIn('подключены', notifications.finish_pairing(repository.path, payload, other, self.chat - 1))
        notifications.test_delivery(repository, self.token, other)
        self.assertEqual(self.deliver(), 1)
        self.assertEqual(self.sent[0][2], '/messages?chat_id=' + str(self.chat - 1))

    def test_signed_launch_validation(self):
        import hashlib, hmac
        from urllib.parse import urlencode
        now = int(time.time())
        config = {'token': 'fictional-token-for-test'}
        data = {'auth_date': str(now), 'user': json.dumps({'id': self.max_user})}
        key = hmac.new(b'WebAppData', config['token'].encode(), hashlib.sha256).digest()
        signature = hmac.new(key, '\n'.join(k + '=' + v for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        raw = urlencode({**data, 'hash': signature})
        self.assertEqual(notifications.launch_identity(raw, config, now), self.max_user)
        for invalid in [raw + '&user=%7B%7D', raw.replace(signature, '0' * 64), 'broken']:
            with self.assertRaises(BackendError):
                notifications.launch_identity(invalid, config, now)
        with self.assertRaises(BackendError):
            notifications.launch_identity(raw, config, now + 28801)

    def test_opt_in_nonce_replay_expiry_and_wrong_identity(self):
        self.notice()
        self.assertEqual(self.count(), 0)
        old = self.pairing()
        payload = self.pairing()
        self.assertIn('истёк', notifications.finish_pairing(repository.path, old, self.max_user, self.chat))
        self.assertIn('подключены', notifications.finish_pairing(repository.path, payload, self.max_user, self.chat))
        self.assertIn('подключены', notifications.finish_pairing(repository.path, payload, self.max_user, self.chat))
        self.assertIn('использована', notifications.finish_pairing(repository.path, payload, self.max_user + 1, self.chat + 1))
        with repository.connection() as c:
            stored = c.execute('SELECT token_hash FROM max_pairings WHERE user_id=?', (self.user,)).fetchone()[0]
            self.assertNotIn(payload[7:], stored)
        self.notice('one-event')
        self.notice('one-event')
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.deliver(), 1)
        self.assertEqual(self.deliver(), 0)
        body = self.sent[0][3]
        self.assertTrue(body['notify'])
        self.assertEqual(self.sent[0][2], '/messages?chat_id=' + str(self.chat))
        self.assertEqual(body['attachments'][0]['payload']['buttons'][0][0]['type'], 'open_app')

    def test_school_transaction_rollback_and_disconnect(self):
        self.connect()
        with self.assertRaises(RuntimeError), repository.connection() as c:
            repository.notice(c, self.user, 'task', 'Не опубликовано', '', 'tasks', uuid.uuid4().hex)
            raise RuntimeError('School transaction failed')
        self.assertEqual(self.count(), 0)
        self.notice()
        notifications.disconnect(repository, self.token)
        self.assertEqual(self.count('cancelled'), 1)
        self.assertEqual(self.deliver(), 0)
        self.connect()
        self.notice()
        self.assertEqual(self.deliver(), 1)

    def test_failures_retry_without_losing_school_notification(self):
        self.connect()
        self.notice()
        def fail(*args):
            raise max_bot.BotError('No network')
        self.assertEqual(self.deliver(fail), 0)
        self.assertEqual(self.count('pending'), 1)
        self.assertEqual(self.deliver(), 0)
        self.assertEqual(self.deliver(clock=lambda: time.time() + 3600), 1)
        self.assertEqual(self.count('sent'), 1)

    def test_parallel_workers_claim_only_once(self):
        self.connect()
        self.notice()
        started, finish = threading.Event(), threading.Event()
        def slow(*args):
            self.sent.append(args)
            started.set()
            self.assertTrue(finish.wait(5))
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.deliver, slow, limit=1)
            self.assertTrue(started.wait(5))
            self.assertEqual(pool.submit(self.deliver, limit=1).result(), 0)
            finish.set()
            self.assertEqual(first.result(), 1)
        self.assertEqual(len(self.sent), 1)

    def test_account_identity_and_webhook_stop(self):
        self.connect()
        _, state, other = self.make_account('student', 'Другой ученик', self.school, '8А')
        payload = notifications.begin_pairing(repository, other, CONFIG)['command'].split(' ', 1)[1]
        self.assertIn('уже связан', notifications.finish_pairing(repository.path, payload, self.max_user, self.chat))
        with tempfile.TemporaryDirectory() as tmp:
            update = {'update_type': 'message_created', 'timestamp': int(time.time() * 1000),
                      'message': {'sender': {'user_id': self.max_user, 'is_bot': False},
                                  'recipient': {'chat_type': 'dialog', 'chat_id': self.chat},
                                  'body': {'text': '/stop', 'mid': uuid.uuid4().hex}}}
            max_bot.process_update(CONFIG, update, sender=lambda *args: self.sent.append(args),
                                   receipts=Path(tmp) / 'receipts.sqlite3', database=repository.path)
        with repository.connection() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM max_links WHERE user_id=?', (self.user,)).fetchone())

    def test_real_http_authentication_and_test_delivery_rate_limit(self):
        self.assertEqual(self.request('/api/max/settings', {})[0], 401)
        with patch.object(max_bot, 'load_config', return_value=CONFIG):
            status, raw, _ = self.request('/api/max/connect', {}, self.token)
            self.assertEqual(status, 200, raw)
            payload = json.loads(raw)['command'].split(' ', 1)[1]
            notifications.finish_pairing(repository.path, payload, self.max_user, self.chat)
            status, raw, _ = self.request('/api/max/settings', {}, self.token)
            self.assertTrue(json.loads(raw)['connected'])
            self.assertEqual(self.request('/api/max/test', {}, self.token)[0], 200)
            self.assertEqual(self.request('/api/max/test', {}, self.token)[0], 429)
            self.assertEqual(self.request('/api/max/disconnect', {}, self.token)[0], 200)
        self.assertEqual(self.count('cancelled'), 1)

    def test_teacher_publishes_task_queues_only_addressed_students(self):
        self.connect()
        _, teacher, teacher_token = self.make_account('teacher', 'Учитель уведомлений', self.school)
        person = next(u for u in teacher['db']['users'] if u['id'] == teacher['userId'])
        repository.apply_changes(teacher_token, teacher['revision'],
                                 {'users': [{**person, 'subjects': ['Математика']}]})
        task_id = uuid.uuid4().hex
        repository.apply_changes(teacher_token, repository.get_revision(teacher_token)['revision'],
                                 {'tasks': [{'id': task_id, 'title': 'Проверяем площадь',
                                             'description': 'Вычисли площадь', 'instructions': 'Запиши ответ',
                                             'subject': 'Математика', 'points': 20,
                                             'deadline': (date.today() + timedelta(days=1)).isoformat(),
                                             'targetType': 'class', 'target': '8А'}]})
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.deliver(), 1)
        self.assertIn('Математика · Проверяем площадь', self.sent[0][3]['text'])
