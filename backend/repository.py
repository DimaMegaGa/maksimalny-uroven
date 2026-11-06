"""SQLite storage for the local test installation. Standard library only."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from access_control import AccessControl, BackendError
from ministry import Ministry
from operations import Operations


def now():
    return int(time.time() * 1000)


def key(value):
    return ' '.join(str(value).split()).casefold()


def class_key(value):
    return re.sub(r'''[\s«»"'\-]''', '', key(value))


def grade(value):
    match = re.match(r'^\s*(\d{1,2})', str(value))
    return match[1] if match else ''


def require(condition, message='Действие недоступно', status=403):
    if not condition:
        raise BackendError(message, status)


def text(value, maximum, required=True):
    require(isinstance(value, str), 'Ожидается строка', 400)
    value = value.strip()
    require(len(value) <= maximum and (value or not required), 'Проверьте заполнение полей', 400)
    return value


def image(value):
    if value == '':
        return value
    require(isinstance(value, str) and len(value) < 2_000_000, 'Слишком большое фото', 400)
    match = re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)', value)
    require(match, 'Неверный формат фото', 400)
    try:
        raw = base64.b64decode(match[2], validate=True)
    except ValueError:
        raise BackendError('Неверный формат фото')
    valid = (
        match[1] == 'jpeg'
        and raw.startswith(b'\xff\xd8\xff')
        and raw.endswith(b'\xff\xd9')
        or match[1] == 'png'
        and raw.startswith(b'\x89PNG\r\n\x1a\n')
        or match[1] == 'webp'
        and raw.startswith(b'RIFF')
        and raw[8:12] == b'WEBP'
    )
    require(valid, 'Содержимое фото не соответствует формату', 400)
    return value


SUBJECTS = {
    name: 20
    for name in [
        'Русский язык',
        'География',
        'Алгебра',
        'Геометрия',
        'Вероятность и статистика',
        'Информатика',
        'Биология',
        'Физика',
        'Химия',
        'Литература',
        'Иностранный язык',
        'Обществознание',
        'Основы духовно-нравственной культуры народов России',
        'Труд (технология)',
        'Музыка',
        'Изобразительное искусство',
        'Физическая культура',
        'Основы безопасности и защиты Родины',
        'Второй иностранный язык',
        'Родный язык',
        'Родная литература',
    ]
}
SUBJECTS.update({'Математика': 30, 'История': 25})
TABLES = ('users', 'tasks', 'submissions', 'notifications', 'exchanges', 'ledger')
JSON_FIELDS = {
    'achievements_json': 'achievements',
    'photos_json': 'photos',
    'subjects_json': 'subjects',
}


def public(row):
    result = {}
    for name, value in dict(row).items():
        if name == 'extra_json':
            result.update(json.loads(value))
        elif name in JSON_FIELDS:
            result[JSON_FIELDS[name]] = json.loads(value)
        elif name in ('is_read', 'celebrated'):
            result['read' if name == 'is_read' else name] = bool(value)
        else:
            result[re.sub(r'_([a-z])', lambda m: m[1].upper(), name)] = value
    return result


class Repository(AccessControl, Ministry, Operations):
    def __init__(self, path=None):
        self.path = Path(
            path
            or os.environ.get('MAKS_DB_PATH')
            or Path(__file__).parent / 'data' / 'maks.sqlite3'
        ).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
                connection.executescript(
                    Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
                )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS login_attempts (identity TEXT PRIMARY KEY, failures INTEGER NOT NULL, reset_at INTEGER NOT NULL)'
            )
            connection.execute('PRAGMA user_version=1')
            from max_notifications import install
            install(connection)
            for table, column, definition in [
                ('tasks', 'archived', 'INTEGER NOT NULL DEFAULT 0'),
                ('users', 'subjects_json', "TEXT NOT NULL DEFAULT '[]'"),
                ('submissions', 'teacher_comment', "TEXT NOT NULL DEFAULT ''"),
                ('submissions', 'review_outcome', "TEXT NOT NULL DEFAULT ''"),
            ]:
                if column not in {
                    r[1] for r in connection.execute('PRAGMA table_info(' + table + ')')
                }:
                    connection.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            connection.execute(
                'CREATE TABLE IF NOT EXISTS submission_events (id TEXT PRIMARY KEY, submission_id TEXT NOT NULL REFERENCES submissions(id), user_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL, teacher_comment TEXT NOT NULL DEFAULT \'\', created_at BIGINT NOT NULL)'
            )
            connection.execute(
                'CREATE INDEX IF NOT EXISTS submission_events_user ON submission_events(user_id,created_at)'
            )
            connection.execute(
                "INSERT INTO submission_events SELECT 'legacy:' || id,id,user_id,CASE WHEN status='rejected' THEN 'revision' ELSE status END,teacher_comment,COALESCE(checked_at,created_at) FROM submissions WHERE NOT EXISTS (SELECT 1 FROM submission_events e WHERE e.submission_id=submissions.id)"
            )
            descriptions = {
                'first-task': 'Первое задание подтверждено учителем.',
                'five-tasks': 'Выполнено 5 заданий.',
                'ten-tasks': 'Выполнено 10 заданий.',
                'level-active': 'Набрано 60 баллов опыта — открыт уровень «Активный».',
                'level-leader': 'Набрано 120 баллов опыта — открыт уровень «Лидер».',
            }
            for row in connection.execute('SELECT id,achievements_json FROM users').fetchall():
                awards = json.loads(row['achievements_json'])
                for award in awards:
                    if award['id'] in descriptions:
                        award['description'] = descriptions[award['id']]
                connection.execute(
                    'UPDATE users SET achievements_json=? WHERE id=?',
                    (json.dumps(awards, ensure_ascii=False), row['id']),
                )
            connection.execute('PRAGMA user_version=2')
            self.init_access(connection)
            self.init_ministry(connection)
            self.init_operations(connection)

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.create_function('school_key', 1, key)
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def actor(self, c, token):
        return self.access_actor(c, token)

    def revision(self, c):
        return c.execute('SELECT revision FROM workspace_revision WHERE id=1').fetchone()[0]

    def bump(self, c):
        c.execute('UPDATE workspace_revision SET revision=revision+1 WHERE id=1')

    def visible(self, task, user):
        if user['role'] != 'student' or key(task['school']) != key(user['school']):
            return False
        return (
            task['target'] == user['id']
            if task['targetType'] == 'student'
            else (
                class_key(task['target']) == class_key(user['className'])
                if task['targetType'] == 'class'
                else bool(grade(task['target']))
                and grade(task['target']) == grade(user['className'])
            )
        )

    def snapshot(self, c, user):
        if user['role'] == 'director':
            return self.director_snapshot(c, user)
        if user['role'] == 'ministry':
            return self.ministry_snapshot(c, user)

        def fetch(sql, args=()):
            return [public(row) for row in c.execute(sql, args)]

        school = key(user['school'])
        people = fetch(
            'SELECT u.* FROM users u LEFT JOIN account_access a ON a.user_id=u.id WHERE school_key(u.school)=? AND COALESCE(a.active,1)=1',
            (school,),
        )
        candidates = fetch('SELECT * FROM tasks WHERE school_key(school)=?', (school,))
        tasks = [t for t in candidates if t['teacherId'] == user['id'] or self.visible(t, user)]
        ids = [t['id'] for t in tasks]
        placeholders = ','.join('?' for _ in ids) or 'NULL'
        submissions = fetch(
            'SELECT * FROM submissions WHERE user_id=?'
            + (' OR task_id IN (' + placeholders + ')' if user['role'] == 'teacher' else ''),
            (user['id'], *ids) if user['role'] == 'teacher' else (user['id'],),
        )
        completed = dict(
            c.execute(
                "SELECT s.user_id,COUNT(*) FROM submissions s JOIN users u ON u.id=s.user_id WHERE s.status='approved' AND school_key(u.school)=? GROUP BY s.user_id",
                (school,),
            )
        )
        for person in people:
            person['completedCount'] = completed.get(person['id'], 0)
        own = fetch('SELECT * FROM ledger WHERE user_id=?', (user['id'],))
        for identity, earned, spent in c.execute(
            'SELECT l.user_id,SUM(CASE WHEN amount>0 THEN amount ELSE 0 END),SUM(CASE WHEN amount<0 THEN amount ELSE 0 END) FROM ledger l JOIN users u ON u.id=l.user_id WHERE school_key(u.school)=? AND u.id!=? GROUP BY l.user_id',
            (school, user['id']),
        ):
            for suffix, total in [('earned', earned), ('spent', spent)]:
                if total:
                    own.append(
                        dict(
                            id='public:' + identity + suffix,
                            eventId='public:' + identity + suffix,
                            userId=identity,
                            amount=total,
                            text='Сумма баллов',
                            createdAt=0,
                        )
                    )
        db = dict(
            users=people,
            tasks=tasks,
            submissions=submissions,
            ledger=own,
            notifications=fetch('SELECT * FROM notifications WHERE user_id=?', (user['id'],)),
            exchanges=fetch(
                'SELECT * FROM exchanges WHERE user_id=? OR teacher_id=?', (user['id'], user['id'])
            ),
            activities=fetch(
                'SELECT * FROM submission_events WHERE user_id=? ORDER BY created_at DESC',
                (user['id'],),
            ),
        )
        return dict(userId=user['id'], revision=self.revision(c), db=db)

    def login(self, fields, client='local'):
        return self.access_login(fields, client)

    def get_snapshot(self, token):
        with self.connection() as c:
            c.execute('BEGIN')
            return self.snapshot(c, self.actor(c, token))

    def logout(self, token):
        with self.connection() as c:
            c.execute(
                'DELETE FROM sessions WHERE token_hash=?',
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
            c.execute(
                'DELETE FROM director_sessions WHERE token_hash=?',
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
            c.execute(
                'DELETE FROM ministry_sessions WHERE token_hash=?',
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def put(self, c, table, row):
        fields = {}
        for name, value in row.items():
            if name in ('achievements', 'photos', 'subjects'):
                name = name + '_json'
                value = json.dumps(value, ensure_ascii=False)
            elif name in ('read', 'celebrated'):
                name = 'is_read' if name == 'read' else name
                value = int(value)
            else:
                name = re.sub(r'[A-Z]', lambda m: '_' + m[0].lower(), name)
            fields[name] = value
        cols = ','.join(fields)
        updates = ','.join(n + '=excluded.' + n for n in fields if n != 'id')
        c.execute(
            f'INSERT INTO {table} ({cols}) VALUES ({",".join("?" for _ in fields)}) ON CONFLICT(id) DO UPDATE SET {updates}',
            tuple(fields.values()),
        )

    def notice(self, c, user_id, kind, title, message, target, event, **extra):
        c.execute(
            'INSERT OR IGNORE INTO notifications(id,user_id,event_id,type,title,text,target,extra_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (
                str(uuid.uuid4()),
                user_id,
                event,
                kind,
                title,
                message,
                target,
                json.dumps(extra, ensure_ascii=False),
                now(),
            ),
        )

    def total(self, c, user_id):
        return c.execute(
            'SELECT COALESCE(SUM(amount),0) FROM ledger WHERE user_id=?', (user_id,)
        ).fetchone()[0]

    def award(self, c, student_id, submission_id):
        earned = c.execute(
            'SELECT COALESCE(SUM(amount),0) FROM ledger WHERE user_id=? AND amount>0', (student_id,)
        ).fetchone()[0]
        count = c.execute(
            "SELECT COUNT(*) FROM submissions WHERE user_id=? AND status='approved'", (student_id,)
        ).fetchone()[0]
        user = public(c.execute('SELECT * FROM users WHERE id=?', (student_id,)).fetchone())
        awards = user['achievements']
        for aid, kind, threshold, title, icon in [
            ('first-task', 'tasks', 1, 'Первый шаг', '🌱'),
            ('five-tasks', 'tasks', 5, 'В ритме школы', '✦'),
            ('ten-tasks', 'tasks', 10, 'Десятка достижений', '🎯'),
            ('level-active', 'level', 60, 'Активный', '⚡'),
            ('level-leader', 'level', 120, 'Лидер', '🏆'),
        ]:
            if (earned if kind == 'level' else count) >= threshold and not any(
                a['id'] == aid for a in awards
            ):
                description = (
                    f'Выполнено {threshold} заданий.'
                    if kind == 'tasks'
                    else f'Набрано {threshold} баллов опыта — открыт уровень «{title}».'
                )
                if aid == 'first-task':
                    description = 'Первое задание подтверждено учителем.'
                awards.append(
                    dict(
                        id=aid,
                        kind=kind,
                        threshold=threshold,
                        title=title,
                        description=description,
                        icon=icon,
                        earnedAt=now(),
                    )
                )
                if kind == 'level':
                    self.notice(
                        c,
                        student_id,
                        'level',
                        'Новый уровень!',
                        title,
                        'profile',
                        f'level:{student_id}:{aid}',
                        levelTitle=title,
                        levelThreshold=threshold,
                        submissionId=submission_id,
                    )
        c.execute(
            'UPDATE users SET achievements_json=? WHERE id=?',
            (json.dumps(awards, ensure_ascii=False), student_id),
        )

    def apply_changes(self, token, revision, changes, request_id=None):
        require(
            isinstance(changes, dict) and set(changes) <= set(TABLES),
            'Неверный набор изменений',
            400,
        )
        require(
            all(
                isinstance(rows, list)
                and len(rows) <= 500
                and all(isinstance(r, dict) for r in rows)
                for rows in changes.values()
            ),
            'Неверные записи',
            400,
        )
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            user = self.actor(c, token)
            require(user['role'] in ('student', 'teacher'), 'Используйте кабинет директора', 403)
            request_fields = dict(revision=revision, changes=changes)
            if self.replay_operation(c, user, 'commit', request_id, request_fields) is not None:
                return self.snapshot(c, user)
            require(
                type(revision) is int and revision == self.revision(c),
                'Данные обновились. Повторите действие.',
                409,
            )
            for table in TABLES:
                for row in changes.get(table, []):
                    if table == 'ledger':
                        continue  # Always calculate financial effects on the server.
                    rid = text(row.get('id'), 100)
                    stored = c.execute('SELECT * FROM ' + table + ' WHERE id=?', (rid,)).fetchone()
                    old = public(stored) if stored else None
                    if table == 'users':
                        # Legacy UI also sends derived achievements. They are ignored; protected identity fields must match.
                        require(
                            old
                            and rid == user['id']
                            or old
                            and all(
                                row.get(k) == old[k]
                                for k in ('role', 'name', 'school', 'className', 'createdAt')
                            )
                            and row.get('avatar')
                            in (
                                old['avatar'],
                                (
                                    self.media_reference('avatar', rid, old['avatar'])
                                    if old['avatar']
                                    else ''
                                ),
                            )
                        )
                        require(
                            old
                            and all(
                                row.get(k) == old[k]
                                for k in ('role', 'name', 'school', 'className', 'createdAt')
                            )
                        )
                        require(
                            rid == user['id']
                            or row.get('subjects', old['subjects']) == old['subjects']
                        )
                        if rid == user['id']:
                            avatar = row.get('avatar', '')
                            if old['avatar'] and avatar == self.media_reference(
                                'avatar', rid, old['avatar']
                            ):
                                avatar = old['avatar']
                            c.execute('UPDATE users SET avatar=? WHERE id=?', (image(avatar), rid))
                            subjects = row.get('subjects', old['subjects'])
                            require(
                                isinstance(subjects, list)
                                and all(isinstance(s, str) and s in SUBJECTS for s in subjects),
                                'Выберите предметы из списка',
                                400,
                            )
                            require(user['role'] == 'teacher' or subjects == old['subjects'])
                            c.execute(
                                'UPDATE users SET subjects_json=? WHERE id=?',
                                (
                                    json.dumps(list(dict.fromkeys(subjects)), ensure_ascii=False),
                                    rid,
                                ),
                            )
                    elif table == 'notifications':
                        if old:
                            require(old['userId'] == user['id'])
                            require(
                                type(row.get('read')) is bool
                                and type(row.get('celebrated')) is bool,
                                'Неверные отметки',
                                400,
                            )
                            c.execute(
                                'UPDATE notifications SET is_read=?,celebrated=? WHERE id=?',
                                (int(row['read']), int(row['celebrated']), rid),
                            )
                        # New notices proposed by legacy UI are ignored; server creates its own.
                    elif table == 'tasks':
                        require(user['role'] == 'teacher' and not old)
                        points = row.get('points')
                        require(
                            type(points) is int and 1 <= points <= 100, 'Баллы от 1 до 100', 400
                        )
                        subject = text(row.get('subject'), 100)
                        require(
                            subject in SUBJECTS or subject == 'Внеурочная деятельность',
                            'Неизвестный предмет',
                            400,
                        )
                        require(
                            subject == 'Внеурочная деятельность' or subject in user['subjects'],
                            'Сначала укажите этот предмет в своём профиле',
                            400,
                        )
                        try:
                            deadline = date.fromisoformat(row.get('deadline', ''))
                        except (ValueError, TypeError):
                            raise BackendError('Неверный срок')
                        require(deadline >= date.today(), 'Срок уже прошёл', 400)
                        target_type, target = row.get('targetType'), text(row.get('target'), 100)
                        require(
                            target_type in ('student', 'class', 'parallel'), 'Неверный адресат', 400
                        )
                        people = [public(r) for r in c.execute('SELECT * FROM users')]
                        if target_type == 'student':
                            require(
                                any(
                                    p['id'] == target
                                    and p['role'] == 'student'
                                    and key(p['school']) == key(user['school'])
                                    for p in people
                                )
                            )
                        else:
                            require(
                                grade(target) and 1 <= int(grade(target)) <= 11,
                                'Неверный класс',
                                400,
                            )
                        task = dict(
                            id=rid,
                            teacherId=user['id'],
                            school=user['school'],
                            title=text(row.get('title'), 120),
                            description=text(row.get('description'), 3000),
                            instructions=text(row.get('instructions', ''), 2000, False),
                            subject=subject,
                            points=points,
                            deadline=deadline.isoformat(),
                            targetType=target_type,
                            target=target,
                            createdAt=now(),
                        )
                        self.put(c, table, task)
                        for person in people:
                            if self.visible(task, person):
                                self.notice(
                                    c,
                                    person['id'],
                                    'task',
                                    'Новое задание',
                                    task['title'],
                                    'tasks',
                                    'task:' + rid,
                                )
                    elif table == 'submissions':
                        task_row = c.execute(
                            'SELECT * FROM tasks WHERE id=?', (row.get('taskId'),)
                        ).fetchone()
                        require(task_row)
                        task = public(task_row)
                        if user['role'] == 'student':
                            require(not task.get('archived'), 'Задание находится в архиве', 409)
                            require(self.visible(task, user) and row.get('userId') == user['id'])
                            require(
                                not old
                                or old['userId'] == user['id']
                                and old['taskId'] == task['id']
                                and old['status'] == 'rejected'
                                and old['reviewOutcome'] != 'rejected'
                            )
                            require(row.get('status') == 'pending')
                            require(
                                not c.execute(
                                    'SELECT 1 FROM submissions WHERE task_id=? AND user_id=? AND id<>?',
                                    (task['id'], user['id'], rid),
                                ).fetchone(),
                                'Работа уже отправлена',
                                409,
                            )
                            photos = row.get('photos', [])
                            require(
                                isinstance(photos, list) and len(photos) <= 3,
                                'Не более трёх фото',
                                400,
                            )
                            previous_photos = old['photos'] if old else []
                            references = {
                                self.media_reference('submission', rid, value, i): value
                                for i, value in enumerate(previous_photos)
                            }
                            photos = [references.get(value, value) for value in photos]
                            self.put(
                                c,
                                table,
                                dict(
                                    id=rid,
                                    taskId=task['id'],
                                    userId=user['id'],
                                    review=text(row.get('review'), 5000),
                                    photos=[image(p) for p in photos],
                                    status='pending',
                                    createdAt=now(),
                                    checkedAt=None,
                                    teacherComment='',
                                    reviewOutcome='',
                                ),
                            )
                            c.execute(
                                'INSERT INTO submission_events VALUES(?,?,?,?,?,?)',
                                (str(uuid.uuid4()), rid, user['id'], 'pending', '', now()),
                            )
                            self.notice(
                                c,
                                task['teacherId'],
                                'review',
                                'Работа на проверке',
                                user['name'] + ': ' + task['title'],
                                'tasks',
                                'submission:' + rid + ':' + str(now()),
                            )
                        else:
                            require(
                                old
                                and task['teacherId'] == user['id']
                                and old['taskId'] == task['id']
                                and row.get('userId') == old['userId']
                            )
                            require(
                                old['status'] == 'pending'
                                and row.get('status') in ('approved', 'rejected'),
                                'Работа уже проверена',
                                409,
                            )
                            outcome = (
                                'approved'
                                if row['status'] == 'approved'
                                else row.get('reviewOutcome', 'revision')
                            )
                            require(
                                outcome in ('approved', 'revision', 'rejected'),
                                'Неверное решение',
                                400,
                            )
                            comment = text(row.get('teacherComment', ''), 2000, False)
                            old.update(
                                status=row['status'],
                                checkedAt=now(),
                                teacherComment=comment,
                                reviewOutcome=outcome,
                            )
                            self.put(c, table, old)
                            c.execute(
                                'INSERT INTO submission_events VALUES(?,?,?,?,?,?)',
                                (str(uuid.uuid4()), rid, old['userId'], outcome, comment, now()),
                            )
                            if old['status'] == 'approved':
                                previous = self.total(c, old['userId'])
                                c.execute(
                                    'INSERT OR IGNORE INTO ledger VALUES(?,?,?,?,?,?)',
                                    (
                                        str(uuid.uuid4()),
                                        'approved:' + rid,
                                        old['userId'],
                                        task['points'],
                                        task['title'],
                                        now(),
                                    ),
                                )
                                self.award(c, old['userId'], rid)
                                self.notice(
                                    c,
                                    old['userId'],
                                    'reward',
                                    'Задание выполнено!',
                                    '+' + str(task['points']) + ' баллов',
                                    'tasks',
                                    'approved:' + rid,
                                )
                                if any(
                                    previous < cost <= self.total(c, old['userId'])
                                    for cost in SUBJECTS.values()
                                ):
                                    self.notice(
                                        c,
                                        old['userId'],
                                        'exchange',
                                        'Баллов достаточно для обмена',
                                        'Можно запросить оценку',
                                        'exchange',
                                        'exchange-ready:' + rid,
                                    )
                            else:
                                self.notice(
                                    c,
                                    old['userId'],
                                    'revision',
                                    (
                                        'Работа отклонена'
                                        if outcome == 'rejected'
                                        else 'Нужна доработка'
                                    ),
                                    task['title'],
                                    'tasks',
                                    'revision:' + rid + ':' + str(now()),
                                )
                    elif table == 'exchanges':
                        if not old:
                            require(
                                user['role'] == 'student'
                                and row.get('userId') == user['id']
                                and row.get('status') == 'pending'
                            )
                            subject = row.get('subject')
                            require(subject in SUBJECTS, 'Неизвестный предмет', 400)
                            teacher = c.execute(
                                'SELECT * FROM users WHERE id=?', (row.get('teacherId'),)
                            ).fetchone()
                            require(
                                teacher
                                and teacher['role'] == 'teacher'
                                and key(teacher['school']) == key(user['school'])
                            )
                            require(
                                subject in json.loads(teacher['subjects_json']),
                                'Этот учитель не указал выбранный предмет',
                                400,
                            )
                            cost = SUBJECTS[subject]
                            require(self.total(c, user['id']) >= cost, 'Недостаточно баллов', 400)
                            require(
                                not c.execute(
                                    "SELECT 1 FROM exchanges WHERE user_id=? AND subject=? AND status='pending'",
                                    (user['id'], subject),
                                ).fetchone(),
                                'Запрос уже отправлен',
                                409,
                            )
                            self.put(
                                c,
                                table,
                                dict(
                                    id=rid,
                                    userId=user['id'],
                                    teacherId=teacher['id'],
                                    subject=subject,
                                    cost=cost,
                                    status='pending',
                                    createdAt=now(),
                                ),
                            )
                            self.notice(
                                c,
                                teacher['id'],
                                'exchange-request',
                                'Запрос на оценку',
                                subject,
                                'home',
                                'exchange:' + rid,
                            )
                        else:
                            require(user['role'] == 'teacher' and old['teacherId'] == user['id'])
                            require(
                                old['status'] == 'pending'
                                and row.get('status') in ('approved', 'rejected'),
                                'Запрос уже обработан',
                                409,
                            )
                            if row['status'] == 'approved':
                                require(
                                    self.total(c, old['userId']) >= old['cost'],
                                    'Недостаточно баллов',
                                    400,
                                )
                                c.execute(
                                    'INSERT INTO ledger VALUES(?,?,?,?,?,?)',
                                    (
                                        str(uuid.uuid4()),
                                        'exchange:' + rid,
                                        old['userId'],
                                        -old['cost'],
                                        'Обмен: ' + old['subject'],
                                        now(),
                                    ),
                                )
                            old['status'] = row['status']
                            self.put(c, table, old)
                            self.notice(
                                c,
                                old['userId'],
                                'exchange-result',
                                (
                                    'Обмен одобрен'
                                    if old['status'] == 'approved'
                                    else 'Запрос отклонён'
                                ),
                                old['subject'],
                                'exchange',
                                'exchange-result:' + rid,
                            )
            self.bump(c)
            self.remember_operation(c, user, 'commit', request_id, request_fields)
            return self.snapshot(c, self.actor(c, token))


repository = Repository()
