import base64
import copy
import io
import json
import unittest
import uuid
import concurrent.futures
import time
from datetime import date, timedelta
from zipfile import ZipFile
from test_local import LocalTests, repository, BackendError
from roster_files import normalized_csv, inspect

PHOTO = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='


class QualityTests(unittest.TestCase):
    setUpClass = classmethod(LocalTests.setUpClass.__func__)
    tearDownClass = classmethod(LocalTests.tearDownClass.__func__)
    request = LocalTests.request
    make_account = LocalTests.make_account

    def commit(self, token, changes, key=None):
        return repository.apply_changes(
            token, repository.get_snapshot(token)['revision'], changes, key
        )

    def test_task_lifecycle_idempotency_media_and_exchange(self):
        _, ts, tt = self.make_account('teacher', 'Учитель качества', 'Школа качества')
        _, ss, st = self.make_account('student', 'Ученик качества', 'Школа качества', '8А')
        _, _, outsider = self.make_account(
            'student', 'Другой участник', 'Другая школа качества', '8А'
        )
        teacher = next(u for u in ts['db']['users'] if u['id'] == ts['userId'])
        self.commit(tt, {'users': [{**teacher, 'subjects': ['Математика']}]})
        task = dict(
            id='quality-task',
            title='Исследование',
            description='Описание',
            instructions='Выводы',
            subject='Математика',
            points=60,
            deadline=(date.today() + timedelta(days=1)).isoformat(),
            targetType='class',
            target='8А',
        )
        self.commit(tt, {'tasks': [task]})
        update = dict(
            taskId=task['id'],
            title='Новые условия',
            description='Полное описание',
            instructions='Шаги',
            requestId=uuid.uuid4().hex,
        )
        before = repository.task_update(tt, update)['revision']
        self.assertEqual(repository.task_update(tt, update)['revision'], before)
        self.assertRaises(BackendError, repository.task_update, st, update)
        sub = dict(
            id='quality-answer',
            taskId=task['id'],
            userId=ss['userId'],
            review='Мой ответ',
            photos=[PHOTO, PHOTO],
            status='pending',
        )
        revision = repository.get_snapshot(st)['revision']
        key = uuid.uuid4().hex
        result = repository.apply_changes(st, revision, {'submissions': [sub]}, key)
        self.assertEqual(
            repository.apply_changes(st, revision, {'submissions': [sub]}, key)['revision'],
            result['revision'],
        )
        self.assertRaises(
            BackendError,
            repository.apply_changes,
            st,
            revision,
            {'submissions': [{**sub, 'review': 'Иное'}]},
            key,
        )
        self.assertRaises(
            BackendError, repository.task_update, tt, {**update, 'requestId': uuid.uuid4().hex}
        )
        self.assertRaises(BackendError, repository.get_media, outsider, 'submission', sub['id'], 0)
        self.assertEqual(repository.get_media(tt, 'submission', sub['id'], 0), PHOTO)
        compact = repository.compact_snapshot(copy.deepcopy(result))
        self.assertTrue(compact['db']['submissions'][0]['photos'][0].startswith('/api/media/'))
        self.commit(
            tt,
            {
                'submissions': [
                    {
                        **sub,
                        'status': 'rejected',
                        'reviewOutcome': 'revision',
                        'teacherComment': 'Добавить примеры',
                    }
                ]
            },
        )
        reference = compact['db']['submissions'][0]['photos'][1]
        self.commit(st, {'submissions': [{**sub, 'photos': [reference], 'review': 'Исправлено'}]})
        self.assertEqual(len(repository.get_snapshot(st)['db']['submissions'][0]['photos']), 1)
        revision = repository.get_snapshot(tt)['revision']
        key = uuid.uuid4().hex
        approve = {'submissions': [{**sub, 'status': 'approved'}]}
        repository.apply_changes(tt, revision, approve, key)
        repository.apply_changes(tt, revision, approve, key)
        self.assertEqual(sum(r['amount'] for r in repository.get_snapshot(st)['db']['ledger']), 60)
        exchange = dict(
            id='quality-exchange',
            userId=ss['userId'],
            teacherId=ts['userId'],
            subject='Математика',
            status='pending',
        )
        self.commit(st, {'exchanges': [exchange]})
        revision = repository.get_snapshot(tt)['revision']
        key = uuid.uuid4().hex
        decision = {'exchanges': [dict(id=exchange['id'], status='approved')]}
        repository.apply_changes(tt, revision, decision, key)
        repository.apply_changes(tt, revision, decision, key)
        self.assertEqual(sum(r['amount'] for r in repository.get_snapshot(st)['db']['ledger']), 30)
        repository.task_update(tt, dict(taskId=task['id'], archived=True))
        self.assertTrue(repository.get_snapshot(st)['db']['tasks'][0]['archived'])
        self.assertEqual(len(repository.get_snapshot(st)['db']['activities']), 4)
        status, raw, _ = self.request('/api/revision', token=st)
        self.assertEqual(status, 200)
        self.assertEqual(list(json.loads(raw)), ['revision'])
        user = next(
            u for u in repository.get_snapshot(st)['db']['users'] if u['id'] == ss['userId']
        )
        self.commit(st, {'users': [{**user, 'avatar': PHOTO}]})
        status, raw, _ = self.request('/api/state', token=st)
        payload = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertIn('subjects', payload['config'])
        avatar = next(u['avatar'] for u in payload['db']['users'] if u['id'] == ss['userId'])
        status, raw, headers = self.request(avatar, token=st)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(raw, base64.b64decode(PHOTO.split(',')[1]))
        self.assertEqual(self.request(avatar, token=outsider)[0], 404)
        self.assertEqual(self.request(avatar)[0], 401)

    def test_spreadsheet_mapping_and_repeated_delivery(self):
        _, mc = repository.bootstrap_ministry()
        _, mt = repository.login(dict(role='ministry', code=mc))
        did, dc = repository.bootstrap_director(['Школа таблиц'])
        ds, dt = repository.login(dict(role='director', code=dc))
        csv = 'Номер;Имя участника;Категория;Учебный класс\n1;Табличный Ученик;ученик;7Б\n'
        fields = dict(
            csv=csv,
            mapping={'ФИО': 'Имя участника', 'Роль': 'Категория', 'Класс': 'Учебный класс'},
            directorId=did,
            organizationId=ds['admin']['organizations'][0]['id'],
            title='Список',
            requestId=uuid.uuid4().hex,
        )
        self.assertEqual(repository.ministry_inspect(mt, fields)['count'], 1)
        first = repository.ministry_import(mt, fields)
        second = repository.ministry_import(mt, fields)
        self.assertEqual(first['packageId'], second['packageId'])
        send = dict(packageId=first['packageId'], requestId=uuid.uuid4().hex)
        repository.package_action(mt, send, 'send')
        repository.package_action(mt, send, 'send')
        self.assertEqual(len(repository.get_snapshot(dt)['admin']['packages']), 1)
        self.assertRaises(BackendError, repository.ministry_inspect, dt, fields)
        self.assertRaises(
            BackendError,
            normalized_csv,
            {**fields, 'mapping': {'ФИО': 'Номер', 'Роль': 'Номер', 'Класс': 'Номер'}},
        )

    def test_xlsx_and_formula_rejection(self):
        def xlsx(formula=False):
            stream = io.BytesIO()
            with ZipFile(stream, 'w') as z:
                z.writestr(
                    'xl/workbook.xml',
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Данные" sheetId="1" r:id="r1"/></sheets></workbook>',
                )
                z.writestr(
                    'xl/_rels/workbook.xml.rels',
                    '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
                )
                rows = [['ФИО', 'Роль', 'Класс'], ['Ученик Excel', 'ученик', '8А']]
                body = ''.join(
                    '<row>'
                    + ''.join(
                        f'<c r="{chr(65+i)}{n}" t="inlineStr"><is><t>{value}</t></is>'
                        + ('<f>1+1</f>' if formula else '')
                        + '</c>'
                        for i, value in enumerate(row)
                    )
                    + '</row>'
                    for n, row in enumerate(rows, 1)
                )
                z.writestr(
                    'xl/worksheets/sheet1.xml',
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                    + body
                    + '</sheetData></worksheet>',
                )
            return dict(xlsx=base64.b64encode(stream.getvalue()).decode())

        self.assertEqual(inspect(xlsx())['columns'], ['ФИО', 'Роль', 'Класс'])
        self.assertIn('Ученик Excel;ученик;8А', normalized_csv(xlsx()))
        self.assertRaises(BackendError, inspect, xlsx(True))
        self.assertRaises(BackendError, inspect, {'xlsx': 'not-base64'})

    def test_concurrent_read_consistency(self):
        _, state, token = self.make_account(
            'student', 'Ученик параллельных запросов', 'Школа нагрузки', '9А'
        )
        start = time.perf_counter()

        def read(_):
            status, body, _ = self.request('/api/state', token=token)
            result = json.loads(body)
            return status, result.get('userId'), result.get('revision')

        with concurrent.futures.ThreadPoolExecutor(20) as pool:
            results = list(pool.map(read, range(40)))
        self.assertTrue(
            all(
                r[0] == 200 and r[1] == state['userId'] and r[2] == state['revision']
                for r in results
            )
        )
        print(
            f'40 authenticated state reads / 20 workers: {time.perf_counter()-start:.2f}s, no errors'
        )
