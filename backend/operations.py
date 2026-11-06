import hashlib
import json
import re
from access_control import BackendError, require, timestamp


class Operations:
    def init_operations(self, c):
        c.execute(
            'CREATE TABLE IF NOT EXISTS operation_receipts(actor_id TEXT NOT NULL,request_id TEXT NOT NULL,action TEXT NOT NULL,fingerprint TEXT NOT NULL,result_json TEXT NOT NULL,created_at BIGINT NOT NULL,PRIMARY KEY(actor_id,request_id))'
        )
        c.execute('CREATE INDEX IF NOT EXISTS receipts_created ON operation_receipts(created_at)')

    def replay_operation(self, c, actor, action, request_id, fields):
        if not request_id:
            return None
        require(
            isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id),
            'Некорректный идентификатор операции',
            400,
        )
        fingerprint = hashlib.sha256(
            json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        ).hexdigest()
        row = c.execute(
            'SELECT * FROM operation_receipts WHERE actor_id=? AND request_id=?',
            (actor['id'], request_id),
        ).fetchone()
        if row:
            require(
                row['action'] == action and row['fingerprint'] == fingerprint,
                'Идентификатор уже использован для другого действия',
                409,
            )
            return json.loads(row['result_json'])
        return None

    def remember_operation(self, c, actor, action, request_id, fields, result=None):
        if not request_id:
            return
        fingerprint = hashlib.sha256(
            json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
        ).hexdigest()
        c.execute(
            'INSERT INTO operation_receipts VALUES(?,?,?,?,?,?)',
            (actor['id'], request_id, action, fingerprint, json.dumps(result or {}), timestamp()),
        )
        c.execute(
            'DELETE FROM operation_receipts WHERE created_at<?', (timestamp() - 7 * 86400000,)
        )

    def get_revision(self, token):
        with self.connection() as c:
            self.actor(c, token)
            return {'revision': self.revision(c)}

    def get_media(self, token, kind, identity, index=0):
        with self.connection() as c:
            actor = self.actor(c, token)
            require(actor['role'] in ('student', 'teacher'), 'Файл недоступен', 403)
            if kind == 'avatar':
                row = c.execute(
                    'SELECT u.avatar,u.school FROM users u LEFT JOIN account_access a ON a.user_id=u.id WHERE u.id=? AND COALESCE(a.active,1)=1',
                    (identity,),
                ).fetchone()
                from repository import key

                require(row and key(row['school']) == key(actor['school']), 'Файл недоступен', 404)
                return row['avatar']
            row = c.execute(
                'SELECT s.photos_json,s.user_id,t.teacher_id FROM submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=?',
                (identity,),
            ).fetchone()
            require(
                row and actor['id'] in (row['user_id'], row['teacher_id']), 'Файл недоступен', 404
            )
            photos = json.loads(row['photos_json'])
            require(type(index) is int and 0 <= index < len(photos), 'Файл не найден', 404)
            return photos[index]

    @staticmethod
    def media_reference(kind, identity, value, index=None):
        suffix = '' if index is None else '/' + str(index)
        return (
            '/api/media/'
            + kind
            + '/'
            + identity
            + suffix
            + '?v='
            + hashlib.sha256(value.encode()).hexdigest()[:16]
        )

    def compact_snapshot(self, payload):
        if 'db' not in payload:
            return payload
        for user in payload['db'].get('users', []):
            if user.get('avatar', '').startswith('data:'):
                user['avatar'] = self.media_reference('avatar', user['id'], user['avatar'])
        for row in payload['db'].get('submissions', []):
            row['photos'] = [
                self.media_reference('submission', row['id'], value, i)
                for i, value in enumerate(row.get('photos', []))
            ]
        return payload

    def task_update(self, token, fields):
        from repository import text

        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            actor = self.actor(c, token)
            require(actor['role'] == 'teacher')
            task = c.execute(
                'SELECT * FROM tasks WHERE id=? AND teacher_id=?',
                (fields.get('taskId'), actor['id']),
            ).fetchone()
            require(task, 'Задание недоступно', 404)
            replay = self.replay_operation(c, actor, 'task-update', fields.get('requestId'), fields)
            if replay is not None:
                return self.snapshot(c, actor)
            if 'archived' in fields:
                require(type(fields['archived']) is bool, 'Неверный статус', 400)
                c.execute(
                    'UPDATE tasks SET archived=? WHERE id=?', (int(fields['archived']), task['id'])
                )
            else:
                require(
                    not c.execute(
                        'SELECT 1 FROM submissions WHERE task_id=?', (task['id'],)
                    ).fetchone(),
                    'Уже есть ответы. Условия сохраняются в истории; создайте новое задание.',
                    409,
                )
                c.execute(
                    'UPDATE tasks SET title=?,description=?,instructions=? WHERE id=?',
                    (
                        text(fields.get('title'), 120),
                        text(fields.get('description'), 3000),
                        text(fields.get('instructions', ''), 2000, False),
                        task['id'],
                    ),
                )
            self.bump(c)
            self.remember_operation(c, actor, 'task-update', fields.get('requestId'), fields)
            return self.snapshot(c, actor)
