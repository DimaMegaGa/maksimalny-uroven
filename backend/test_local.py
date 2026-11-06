"""Integration tests use a temporary database, never the user's test profiles."""

import concurrent.futures
import copy
import importlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import hashlib
import secrets
import uuid
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path

TMP = tempfile.TemporaryDirectory()
os.environ['MAKS_DB_PATH'] = str(Path(TMP.name) / 'test.sqlite3')
from repository import Repository, BackendError, repository
from server import Handler, ThreadingHTTPServer


class LocalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.ministry_server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.ministry_server.site = 'ministry'
        cls.ministry_thread = threading.Thread(
            target=cls.ministry_server.serve_forever, daemon=True
        )
        cls.ministry_thread.start()
        cls.ministry_url = 'http://127.0.0.1:' + str(cls.ministry_server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.ministry_server.shutdown()
        cls.ministry_server.server_close()

    def request(self, route, body=None, token='', site=None):
        if site is None:
            site = (
                'ministry'
                if route.startswith('/api/ministry/')
                or route == '/api/login'
                and body
                and body.get('role') == 'ministry'
                else 'school'
            )
            if token:
                try:
                    with repository.connection() as c:
                        if repository.actor(c, token)['role'] == 'ministry':
                            site = 'ministry'
                except BackendError:
                    pass
        cookie = 'maks_ministry_session' if site == 'ministry' else 'maks_session'
        port = self.ministry_server.server_port if site == 'ministry' else self.server.server_port
        if port != (8767 if site == 'ministry' else 8765):
            cookie += '_' + str(port)
        headers = {
            'X-Maks-Request': '1',
            'Content-Type': 'application/json',
            'Cookie': cookie + '=' + token,
        }
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            (self.ministry_url if site == 'ministry' else self.url) + route,
            data=data,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def make_account(self, role, name, school, class_name=''):
        if not hasattr(self, 'test_directors'):
            self.test_directors = {}
        if school not in self.test_directors:
            _, code = repository.bootstrap_director([school])
            state, token = repository.login({'role': 'director', 'code': code})
            self.test_directors[school] = (token, state['admin']['organizations'][0]['id'])
        dt, oid = self.test_directors[school]
        if not hasattr(self, 'ministry_token'):
            _, mc = repository.bootstrap_ministry()
            _, self.ministry_token = repository.login(dict(role='ministry', code=mc))
        state = repository.get_snapshot(dt)
        fields = dict(
            directorId=state['userId'],
            organizationId=oid,
            title='Тестовый пакет',
            csv='ФИО;Роль;Класс\n' + name + ';' + role + ';' + class_name + '\n',
        )
        packet = repository.ministry_import(self.ministry_token, fields)
        identity = packet['packageId']
        issued = repository.package_action(self.ministry_token, dict(packageId=identity), 'open')[
            'rows'
        ][0]
        repository.package_action(self.ministry_token, dict(packageId=identity), 'send')
        fields = dict(role=role, name=name, code=issued['code'])
        state, token = repository.login(fields)
        return fields, state, token

    def test_avatar_persistence_and_validation(self):
        _, state, token = self.make_account('student', 'Ученик Фото', 'Школа фото', '8А')
        actor = next(u for u in state['db']['users'] if u['id'] == state['userId'])
        photo = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
        status, raw, _ = self.request(
            '/api/commit',
            {'revision': state['revision'], 'changes': {'users': [{**actor, 'avatar': photo}]}},
            token,
        )
        self.assertEqual(status, 200, raw)
        saved = Repository(repository.path).get_snapshot(token)
        current = next(u for u in saved['db']['users'] if u['id'] == actor['id'])
        self.assertEqual(current['avatar'], photo)
        status, _, _ = self.request(
            '/api/commit',
            {
                'revision': saved['revision'],
                'changes': {
                    'users': [{**current, 'avatar': 'data:image/png;base64,bm90LWFuLWltYWdl'}]
                },
            },
            token,
        )
        self.assertEqual(status, 400)
        saved = repository.get_snapshot(token)
        self.assertEqual(
            next(u for u in saved['db']['users'] if u['id'] == actor['id'])['avatar'], photo
        )
        status, raw, _ = self.request(
            '/api/commit',
            {'revision': saved['revision'], 'changes': {'users': [{**current, 'avatar': ''}]}},
            token,
        )
        self.assertEqual(status, 200, raw)
        self.assertEqual(
            next(
                u for u in repository.get_snapshot(token)['db']['users'] if u['id'] == actor['id']
            )['avatar'],
            '',
        )

    def test_end_to_end(self):
        status, _, _ = self.request('/api/state')
        self.assertEqual(status, 401)
        teacher_fields, _, _ = self.make_account('teacher', 'Тест Учитель', 'Тест Школа')
        status, raw, headers = self.request('/api/login', teacher_fields)
        self.assertEqual(status, 200, raw)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        teacher = json.loads(raw)['userId']
        teacher_token = headers['Set-Cookie'].split(';')[0].split('=', 1)[1]
        state = repository.get_snapshot(teacher_token)
        teacher_user = next(u for u in state['db']['users'] if u['id'] == teacher)
        repository.apply_changes(
            teacher_token,
            state['revision'],
            {'users': [{**teacher_user, 'subjects': ['Математика']}]},
        )
        student_fields, state, token = self.make_account(
            'student', 'Тест Ученик', 'Тест Школа', '8А'
        )
        student = state['userId']
        _, outsider, outsider_token = self.make_account(
            'student', 'Тест Ученик', 'Другая школа', '8А'
        )
        self.assertEqual(
            repository.get_snapshot(outsider_token)['db']['users'][0]['id'], outsider['userId']
        )
        self.assertEqual(self.request('/api/login', {**student_fields, 'register': True})[0], 403)
        self.assertEqual(
            self.request(
                '/api/login', {**student_fields, 'register': False, 'code': 'wrong-secret'}
            )[0],
            401,
        )
        self.assertEqual(self.request('/api/login', {**student_fields, 'role': 'teacher'})[0], 401)
        state2, _ = Repository(repository.path).login({**student_fields, 'register': False})
        self.assertEqual(state2['userId'], student)
        self.assertEqual(len(state2['db']['ledger']), 0)
        with sqlite3.connect(repository.path) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertFalse(
                c.execute(
                    'SELECT 1 FROM credentials WHERE code_hash=?', (student_fields['code'],)
                ).fetchone()
            )
            self.assertFalse(
                c.execute('SELECT 1 FROM sessions WHERE token_hash=?', (token,)).fetchone()
            )
        c.close()

        task = dict(
            id='test-task',
            title='Тестовое задание',
            description='Описание',
            instructions='',
            subject='Математика',
            points=60,
            deadline=(date.today() + timedelta(days=1)).isoformat(),
            targetType='class',
            target='8А',
        )

        def commit(actor, changes):
            state = repository.get_snapshot(actor)
            return repository.apply_changes(actor, state['revision'], changes)

        with self.assertRaises(BackendError):
            commit(token, {'tasks': [task]})
        state = commit(teacher_token, {'tasks': [task], 'ledger': [dict(id='forged', amount=9999)]})
        self.assertEqual(state['db']['ledger'], [])
        self.assertEqual(repository.get_snapshot(outsider_token)['db']['tasks'], [])
        submission = dict(
            id='test-sub',
            taskId=task['id'],
            userId=student,
            review='Сделал',
            photos=[],
            status='pending',
        )
        state = commit(token, {'submissions': [submission]})
        self.assertEqual(repository.get_snapshot(outsider_token)['db']['submissions'], [])
        with self.assertRaises(BackendError):
            commit(token, {'submissions': [{**submission, 'status': 'approved'}]})
        state = repository.get_snapshot(teacher_token)
        revision = state['revision']
        changes = {'submissions': [{**submission, 'status': 'approved'}]}

        def concurrent_approval(_):
            try:
                repository.apply_changes(teacher_token, revision, changes)
                return 200
            except BackendError as error:
                return error.status

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(concurrent_approval, range(2))), [200, 409])
        state = repository.get_snapshot(token)
        self.assertEqual(sum(r['amount'] for r in state['db']['ledger']), 60)
        self.assertEqual(
            next(u for u in state['db']['users'] if u['id'] == student)['completedCount'], 1
        )
        self.assertEqual(
            next(
                u
                for u in repository.get_snapshot(teacher_token)['db']['users']
                if u['id'] == student
            )['completedCount'],
            1,
        )
        self.assertTrue(
            any(
                a['id'] == 'level-active'
                for u in state['db']['users']
                if u['id'] == student
                for a in u['achievements']
            )
        )
        self.assertTrue(any(n['type'] == 'level' for n in state['db']['notifications']))
        self.assertEqual({e['status'] for e in state['db']['activities']}, {'pending', 'approved'})
        self.assertTrue(
            all(
                a['description'] != a['title']
                for u in state['db']['users']
                for a in u['achievements']
            )
        )
        with self.assertRaises(BackendError):
            commit(teacher_token, changes)
        state = commit(
            token,
            {
                'exchanges': [
                    dict(
                        id='test-exchange',
                        userId=student,
                        teacherId=teacher,
                        subject='Математика',
                        cost=1,
                        status='pending',
                    )
                ]
            },
        )
        self.assertEqual(state['db']['exchanges'][0]['cost'], 30)
        commit(teacher_token, {'exchanges': [dict(id='test-exchange', status='approved')]})
        state = repository.get_snapshot(token)
        self.assertEqual(sum(r['amount'] for r in state['db']['ledger']), 30)
        self.assertEqual(sum(max(0, r['amount']) for r in state['db']['ledger']), 60)
        user = next(u for u in state['db']['users'] if u['id'] == student)
        with self.assertRaises(BackendError):
            commit(token, {'users': [{**user, 'role': 'teacher'}]})
        self.assertEqual(self.request('/backend/data/maks.sqlite3')[0], 404)
        self.assertEqual(self.request('/../backend/data/maks.sqlite3')[0], 404)
        for path in ('/', '/app.js', '/style.css', '/server-design.css'):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.request('/api/logout', {}, token)[0], 200)
        self.assertEqual(self.request('/api/state', token=token)[0], 401)
        final, _ = Repository(repository.path).login({**student_fields, 'register': False})
        self.assertEqual(final['userId'], student)
        self.assertEqual(sum(r['amount'] for r in final['db']['ledger']), 30)

    def test_feedback_subjects_and_migration(self):
        _, teacher, tt = self.make_account('teacher', 'Учитель Комментарий', 'Обратная связь')
        _, student, st = self.make_account('student', 'Ученик Комментарий', 'Обратная связь', '7А')

        def commit(token, changes):
            return repository.apply_changes(
                token, repository.get_snapshot(token)['revision'], changes
            )

        tu = next(u for u in teacher['db']['users'] if u['id'] == teacher['userId'])
        state = commit(tt, {'users': [{**tu, 'subjects': ['История', 'Математика']}]})
        self.assertEqual(
            next(u for u in state['db']['users'] if u['id'] == tu['id'])['subjects'],
            ['История', 'Математика'],
        )
        task = dict(
            id='feedback-task',
            title='Историческое исследование',
            description='Описание исследования',
            instructions='Прочитай\nСравни',
            subject='История',
            points=25,
            deadline=(date.today() + timedelta(days=1)).isoformat(),
            targetType='class',
            target='7А',
        )
        commit(tt, {'tasks': [task]})
        sub = dict(
            id='feedback-sub',
            taskId=task['id'],
            userId=student['userId'],
            review='Первый результат',
            photos=[],
            status='pending',
        )
        commit(st, {'submissions': [sub]})
        commit(
            tt,
            {
                'submissions': [
                    {
                        **sub,
                        'status': 'rejected',
                        'reviewOutcome': 'revision',
                        'teacherComment': 'Добавь источники и даты.',
                    }
                ]
            },
        )
        state = repository.get_snapshot(st)
        self.assertEqual(
            state['db']['submissions'][0]['teacherComment'], 'Добавь источники и даты.'
        )
        commit(st, {'submissions': [{**sub, 'review': 'Исправленный результат'}]})
        state = repository.get_snapshot(st)
        self.assertEqual(state['db']['submissions'][0]['teacherComment'], '')
        self.assertTrue(
            any(
                e['teacherComment'] == 'Добавь источники и даты.' for e in state['db']['activities']
            )
        )
        commit(
            tt,
            {
                'submissions': [
                    {
                        **sub,
                        'status': 'rejected',
                        'reviewOutcome': 'rejected',
                        'teacherComment': 'Работа не соответствует условиям.',
                    }
                ]
            },
        )
        with self.assertRaises(BackendError):
            commit(st, {'submissions': [sub]})
        reloaded = Repository(repository.path).get_snapshot(st)
        self.assertEqual(len(reloaded['db']['activities']), 4)
        self.assertEqual(reloaded['db']['submissions'][0]['reviewOutcome'], 'rejected')
        self.assertEqual(reloaded['db']['ledger'], [])
        su = next(u for u in reloaded['db']['users'] if u['id'] == student['userId'])
        with self.assertRaises(BackendError):
            commit(st, {'users': [{**su, 'subjects': ['История']}]})
        with self.assertRaises(BackendError):
            commit(st, {'users': [{**tu, 'subjects': ['Физика']}]})
        unchanged = repository.get_snapshot(tt)
        self.assertEqual(
            next(u for u in unchanged['db']['users'] if u['id'] == tu['id'])['subjects'],
            ['История', 'Математика'],
        )

    def test_ministry_delivery_security_and_legacy(self):
        mid, mc = repository.bootstrap_ministry()
        _, mt = repository.login(dict(role='ministry', code=mc))
        did, dc = repository.bootstrap_director(['Школа централизованной выдачи'])
        ds, dt = repository.login(dict(role='director', code=dc))
        oid = ds['admin']['organizations'][0]['id']
        _, oc = repository.bootstrap_director(['Посторонняя школа'])
        _, ot = repository.login(dict(role='director', code=oc))
        fields = dict(
            directorId=did,
            organizationId=oid,
            title='Первый пакет',
            instructions='Проверить лично.',
            csv='ФИО;Роль;Класс\nИван Петров;учитель;\nМария Иванова;ученик;8А\n',
        )
        status, raw, _ = self.request('/api/ministry/preview', fields, mt)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['count'], 2)
        self.assertEqual(
            repository.ministry_import(
                mt, dict(fields, csv=fields['csv'] + 'Иван Петров;учитель;\n'), True
            )['errors'][0]['line'],
            4,
        )
        self.assertTrue(
            repository.ministry_import(
                mt, dict(fields, csv='ФИО;Роль;Класс\nОшибка;директор;8А'), True
            )['errors']
        )
        for token in [dt, ot, '']:
            self.assertIn(self.request('/api/ministry/import', fields, token)[0], (401, 403))
        self.assertEqual(self.request('/api/director/accounts', dict(role='teacher'), dt)[0], 403)
        self.assertEqual(self.request('/api/director/reissue-code', dict(userId='x'), dt)[0], 403)
        bad = dict(fields, directorId=repository.get_snapshot(ot)['userId'])
        with self.assertRaises(BackendError):
            repository.ministry_import(mt, bad)
        package = repository.ministry_import(mt, fields)
        pid = package['packageId']
        self.assertEqual(repository.get_snapshot(dt)['admin']['packages'], [])
        self.assertEqual(repository.get_snapshot(dt)['admin']['accounts'], [])
        self.assertNotIn('STD-', json.dumps(package))
        for token in [dt, ot, '']:
            self.assertIn(
                self.request('/api/packages/open', dict(packageId=pid), token)[0], (401, 403)
            )
        opened = repository.package_action(mt, dict(packageId=pid), 'open')
        teacher, student = opened['rows']
        credentials = dict(role='teacher', name=teacher['name'], code=teacher['code'])
        with self.assertRaises(BackendError):
            repository.login(credentials)
        with repository.connection() as c:
            cipher = c.execute(
                'SELECT sealed_rows FROM delivery_packages WHERE id=?', (pid,)
            ).fetchone()[0]
            self.assertNotIn(teacher['code'], cipher)
            self.assertEqual(
                c.execute(
                    'SELECT COUNT(*) FROM users WHERE school=?',
                    (fields.get('school', 'Школа централизованной выдачи'),),
                ).fetchone()[0],
                2,
            )
        repository.package_action(mt, dict(packageId=pid), 'send')
        repository.package_action(mt, dict(packageId=pid), 'send')
        teacher_state, tt = repository.login(credentials)
        uid = teacher_state['userId']
        self.assertEqual(repository.get_snapshot(dt)['admin']['packages'][0]['status'], 'sent')
        self.assertFalse(repository.get_snapshot(dt)['admin']['packages'][0]['openedAt'])
        self.assertEqual(self.request('/api/packages/open', dict(packageId=pid), ot)[0], 403)
        self.assertEqual(self.request('/api/packages/open', dict(packageId=pid), tt)[0], 403)
        self.assertEqual(self.request('/api/packages/distribute', dict(packageId=pid), dt)[0], 400)
        recipient_packet = repository.package_action(dt, dict(packageId=pid), 'open')
        self.assertIn('Проверить лично.', recipient_packet['instructions'])
        self.assertIn('Порядок выдачи', recipient_packet['instructions'])
        repository.package_action(dt, dict(packageId=pid), 'distribute')
        self.assertEqual(
            repository.get_snapshot(dt)['admin']['packages'][0]['status'], 'distributed'
        )
        with self.assertRaises(BackendError):
            repository.ministry_import(mt, fields)
        replacement = repository.ministry_reissue(
            mt, dict(directorId=did, organizationId=oid, userId=uid)
        )
        conflicting = repository.ministry_reissue(
            mt, dict(directorId=did, organizationId=oid, userId=uid)
        )
        rid = replacement['packageId']
        repository.login(credentials)
        repository.get_snapshot(tt)
        new = repository.package_action(mt, dict(packageId=rid), 'open')['rows'][0]
        repository.package_action(mt, dict(packageId=rid), 'send')
        with self.assertRaises(BackendError):
            repository.package_action(mt, dict(packageId=conflicting['packageId']), 'send')
        with self.assertRaises(BackendError):
            repository.get_snapshot(tt)
        with self.assertRaises(BackendError):
            repository.login(credentials)
        repository.login(dict(credentials, code=new['code']))
        self.assertFalse(
            repository.package_action(dt, dict(packageId=pid), 'open')['rows'][0]['current']
        )
        legacy_id = str(uuid.uuid4())
        with repository.connection() as c:
            c.execute(
                'INSERT INTO users(id,role,name,school,class_name,created_at) VALUES(?,?,?,?,?,?)',
                (legacy_id, 'student', 'Старый Ученик', 'Школа централизованной выдачи', '8А', 1),
            )
            c.execute(
                'INSERT INTO ledger VALUES(?,?,?,?,?,?)',
                (str(uuid.uuid4()), 'legacy:' + legacy_id, legacy_id, 17, 'Сохранённая награда', 1),
            )
        legacy = repository.ministry_import(
            mt, dict(fields, csv='ФИО;Роль;Класс\nСтарый Ученик;ученик;8А\n')
        )
        lid = legacy['packageId']
        lc = repository.package_action(mt, dict(packageId=lid), 'open')['rows'][0]['code']
        repository.package_action(mt, dict(packageId=lid), 'send')
        restored, _ = repository.login(dict(role='student', name='Старый Ученик', code=lc))
        self.assertEqual(restored['userId'], legacy_id)
        self.assertEqual(
            sum(r['amount'] for r in restored['db']['ledger'] if r['userId'] == legacy_id), 17
        )
        self.assertEqual(self.request('/api/commit', dict(revision=0, changes={}), mt)[0], 404)
        dc2 = repository.rotate_director(did)
        with self.assertRaises(BackendError):
            repository.get_snapshot(dt)
        repository.login(dict(role='director', code=dc2))
        mc2 = repository.rotate_ministry(mid)
        with self.assertRaises(BackendError):
            repository.get_snapshot(mt)
        _, mt2 = repository.login(dict(role='ministry', code=mc2))
        for _ in range(10):
            self.assertEqual(
                self.request('/api/login', dict(role='ministry', code=mc2 + 'bad'))[0], 401
            )
        self.assertEqual(
            self.request('/api/login', dict(role='ministry', code=mc2 + 'bad'))[0], 429
        )
        self.assertEqual(self.request('/api/logout', {}, mt2)[0], 200)
        self.assertEqual(self.request('/api/state', token=mt2)[0], 401)
        with repository.connection() as c:
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())

    def test_separate_sites_and_sessions(self):
        _, mc = repository.bootstrap_ministry()
        _, mt = repository.login(dict(role='ministry', code=mc))
        teacher_fields, _, tt = self.make_account(
            'teacher', 'Учитель Раздельных Сайтов', 'Школа раздельных сайтов'
        )
        self.assertEqual(
            self.request('/api/login', dict(role='ministry', code=mc), site='school')[0], 403
        )
        self.assertEqual(self.request('/api/login', teacher_fields, site='ministry')[0], 403)
        status, _, headers = self.request(
            '/api/login', dict(role='ministry', code=mc), site='ministry'
        )
        self.assertEqual(status, 200)
        self.assertTrue(
            headers['Set-Cookie'].startswith(
                f'maks_ministry_session_{self.ministry_server.server_port}='
            )
        )
        self.assertEqual(self.request('/api/state', token=mt, site='school')[0], 401)
        self.assertEqual(self.request('/api/state', token=tt, site='ministry')[0], 401)
        self.assertEqual(self.request('/api/state', token=mt, site='ministry')[0], 200)
        self.assertEqual(self.request('/api/state', token=tt, site='school')[0], 200)
        self.assertEqual(self.request('/api/ministry/preview', {}, mt, site='school')[0], 404)
        self.assertEqual(self.request('/api/packages/send', {}, mt, site='school')[0], 404)
        self.assertEqual(self.request('/api/packages/distribute', {}, mt, site='ministry')[0], 404)
        self.assertEqual(self.request('/api/logout', {}, mt, site='ministry')[0], 200)
        self.assertEqual(self.request('/api/state', token=tt, site='school')[0], 200)
        for url, expected in [(self.url, 'school'), (self.ministry_url, 'ministry')]:
            with urllib.request.urlopen(url + '/api/health') as response:
                self.assertEqual(json.load(response)['site'], expected)
            with urllib.request.urlopen(url + '/site-config.js') as response:
                self.assertIn(expected, response.read().decode())
        with urllib.request.urlopen(self.ministry_url + '/') as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-cache')
            self.assertIn('ministry-site.css', response.read().decode())
        with urllib.request.urlopen(self.url + '/') as response:
            self.assertNotIn('ministry-site.css', response.read().decode())


if __name__ == '__main__':
    unittest.main(verbosity=2)
