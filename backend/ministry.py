"""Central account provisioning and school-scoped delivery packages."""
import csv
import hashlib
import io
import json
import re
import uuid
from access_control import require, field, normalize, issue_code, timestamp, code_hash
from package_vault import seal, unseal


INSTRUCTIONS = '''Порядок выдачи персональных кодов
1. Проверьте организацию, ФИО и класс по школьному реестру.
2. Передайте каждому участнику только его строку: ФИО и персональный код. Не отправляйте общую таблицу в классный чат.
3. Ученик или учитель выбирает свою роль на странице входа и вводит ФИО и код. Школа и класс уже заполнены.
4. Храните скачанный список в защищённом месте. При потере или раскрытии кода обратитесь в кабинет министерства для перевыпуска.
5. После выдачи отметьте пакет как распределённый. Это отметка директора, а не подтверждение входа каждого участника.'''


class Ministry:
    def init_ministry(self, c):
        c.executescript('''
        CREATE TABLE IF NOT EXISTS ministries (
            id TEXT PRIMARY KEY, label TEXT NOT NULL, lookup_id TEXT NOT NULL UNIQUE,
            code_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at BIGINT NOT NULL);
        CREATE TABLE IF NOT EXISTS ministry_sessions (
            token_hash TEXT PRIMARY KEY, ministry_id TEXT NOT NULL REFERENCES ministries(id), expires_at BIGINT NOT NULL);
        CREATE TABLE IF NOT EXISTS delivery_packages (
            id TEXT PRIMARY KEY, ministry_id TEXT NOT NULL REFERENCES ministries(id),
            director_id TEXT NOT NULL REFERENCES directors(id), organization_id TEXT NOT NULL REFERENCES organizations(id),
            title TEXT NOT NULL, instructions TEXT NOT NULL, sealed_rows TEXT NOT NULL, row_count INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('draft','sent','distributed')), created_at BIGINT NOT NULL,
            sent_at BIGINT, opened_at BIGINT, distributed_at BIGINT);
        CREATE TABLE IF NOT EXISTS delivery_audit (
            id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL,
            package_id TEXT NOT NULL REFERENCES delivery_packages(id), created_at BIGINT NOT NULL);
        ''')
        c.execute('PRAGMA user_version=4')

    def bootstrap_ministry(self, label='Оператор министерства'):
        identity = str(uuid.uuid4())
        code, lookup, salt, hashed = issue_code('MIN')
        with self.connection() as c:
            c.execute('INSERT INTO ministries VALUES(?,?,?,?,?,1,?)', (identity, field(label, 80), lookup, hashed, salt, timestamp()))
            self.bump(c)
        return identity, code

    def rotate_ministry(self, identity):
        code, lookup, salt, hashed = issue_code('MIN')
        with self.connection() as c:
            require(c.execute('SELECT 1 FROM ministries WHERE id=?', (identity,)).fetchone(), 'Кабинет не найден', 404)
            c.execute('UPDATE ministries SET lookup_id=?,code_hash=?,salt=? WHERE id=?', (lookup, hashed, salt, identity))
            c.execute('DELETE FROM ministry_sessions WHERE ministry_id=?', (identity,))
            self.bump(c)
        return code

    def package_list(self, c, actor):
        condition = 'p.director_id=? AND p.status!=\'draft\'' if actor['role'] == 'director' else 'p.ministry_id=?'
        return [dict(r) for r in c.execute('''SELECT p.id,p.title,p.status,p.row_count AS rowCount,
            p.created_at AS createdAt,p.sent_at AS sentAt,p.opened_at AS openedAt,p.distributed_at AS distributedAt,
            o.name AS school,d.label AS director FROM delivery_packages p
            JOIN organizations o ON o.id=p.organization_id JOIN directors d ON d.id=p.director_id
            WHERE ''' + condition + ' ORDER BY p.created_at DESC,p.id', (actor['id'],))]

    def ministry_snapshot(self, c, actor):
        recipients = [dict(r) for r in c.execute('''SELECT o.id AS organizationId,o.name AS school,
            d.id AS directorId,d.label AS director FROM director_organizations x JOIN directors d ON d.id=x.director_id
            JOIN organizations o ON o.id=x.organization_id WHERE d.active=1 ORDER BY o.name,d.label''')]
        accounts = [dict(r) for r in c.execute('''SELECT u.id,u.role,u.name,u.school,u.class_name AS className,a.active
            FROM users u JOIN account_access a ON a.user_id=u.id ORDER BY u.school,u.name''')]
        return dict(userId=actor['id'], revision=self.revision(c),
            db=dict(users=[actor], tasks=[], submissions=[], notifications=[], exchanges=[], ledger=[], activities=[]),
            admin=dict(recipients=recipients, packages=self.package_list(c, actor), accounts=accounts))

    def ministry_recipient(self, c, fields):
        row = c.execute('''SELECT o.*,d.id AS director_id FROM organizations o JOIN director_organizations x ON x.organization_id=o.id
            JOIN directors d ON d.id=x.director_id WHERE o.id=? AND d.id=? AND d.active=1''',
            (fields.get('organizationId'), fields.get('directorId'))).fetchone()
        require(row, 'Выберите организацию и назначенного ей директора', 400)
        return row

    def parse_roster(self, c, source, org):
        require(isinstance(source, str) and 0 < len(source) <= 300_000, 'CSV должен быть не больше 300 КБ', 400)
        source = source.lstrip('\ufeff')
        first = source.splitlines()[0] if source.splitlines() else ''
        separator = max((';', ',', '\t'), key=first.count)
        reader = csv.DictReader(io.StringIO(source), delimiter=separator, strict=True)
        try:
            headers = reader.fieldnames or []
        except csv.Error:
            require(False, 'Некорректный заголовок CSV', 400)
        require('Персональный код' not in headers, 'Выбран готовый список с кодами. Для создания аккаунтов загрузите исходную таблицу: ФИО, Роль, Класс.', 400)
        require(len(headers) == len(set(headers)) and set(headers) == {'ФИО', 'Роль', 'Класс'},
                'Нужны ровно три заголовка: ФИО;Роль;Класс. Скачайте шаблон.', 400)
        result, errors, seen = [], [], set()
        try:
            for number, row in enumerate(reader, 2):
                require(number <= 201, 'В одном пакете допускается до 200 участников. Разделите список.', 400)
                try:
                    require(None not in row and all(v is not None for v in row.values()), 'Количество столбцов не совпадает с заголовком', 400)
                    name = field(row['ФИО'], 80)
                    require(not re.search(r'[\x00-\x1f\x7f]', row['ФИО']), 'Недопустимые символы в ФИО', 400)
                    role = {'ученик':'student','учитель':'teacher','student':'student','teacher':'teacher'}.get(normalize(row['Роль']))
                    require(role, 'Роль: ученик или учитель', 400)
                    class_name = field(row['Класс'], 15) if role == 'student' else ''
                    require(role != 'teacher' or not row['Класс'].strip(), 'Для учителя оставьте класс пустым', 400)
                    require(role != 'student' or re.fullmatch(r'(?:[1-9]|10|11)\s*[А-Яа-яA-Za-zЁё]?', class_name), 'Класс: от 1 до 11, например 8А', 400)
                    key = (normalize(name), role, re.sub(r'\s', '', normalize(class_name)))
                    require(key not in seen, 'Повтор участника в таблице', 400)
                    seen.add(key)
                    existing = [r for r in c.execute('''SELECT u.*,a.user_id AS access_id FROM users u
                        LEFT JOIN account_access a ON a.user_id=u.id''') if normalize(r['school']) == org['name_key'] and
                        normalize(r['name']) == key[0] and r['role'] == role and re.sub(r'\s', '', normalize(r['class_name'])) == key[2]]
                    require(len(existing) <= 1, 'Несколько старых профилей с одинаковыми данными: требуется ручная сверка', 400)
                    require(not existing or existing[0]['access_id'] is None, 'Аккаунт уже создан или включён в пакет. Для замены кода используйте перевыпуск.', 409)
                    result.append(dict(name=name, role=role, className=class_name, legacyId=existing[0]['id'] if existing else None))
                except Exception as error:
                    from access_control import BackendError
                    if not isinstance(error, BackendError):
                        raise
                    errors.append(dict(line=number, message=str(error)))
        except csv.Error:
            errors.append(dict(line=reader.line_num, message='Некорректный CSV: проверьте кавычки и разделители'))
        require(result or errors, 'В таблице нет участников', 400)
        return result, errors

    def ministry_import(self, token, fields, preview=False):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            actor = self.actor(c, token)
            require(actor['role'] == 'ministry')
            org = self.ministry_recipient(c, fields)
            rows, errors = self.parse_roster(c, fields.get('csv'), org)
            if preview:
                return dict(rows=rows, errors=errors, count=len(rows), school=org['name'])
            require(not errors, 'Исправьте ошибки таблицы перед формированием пакета', 400)
            title = field(fields.get('title'), 120)
            note = fields.get('instructions', '')
            require(isinstance(note, str) and len(note) <= 8000, 'Сообщение должно быть не длиннее 8000 символов', 400)
            instructions = (note.strip() + '\n\n' if note.strip() else '') + INSTRUCTIONS
            payload = []
            for row in rows:
                user_id = row.pop('legacyId') or str(uuid.uuid4())
                c.execute('INSERT OR IGNORE INTO users(id,role,name,school,class_name,created_at) VALUES(?,?,?,?,?,?)',
                    (user_id, row['role'], row['name'], org['name'], row['className'], timestamp()))
                code, lookup, salt, hashed = issue_code('TCH' if row['role'] == 'teacher' else 'STD')
                c.execute('''INSERT INTO credentials VALUES(?,?,?,?) ON CONFLICT(user_id)
                    DO UPDATE SET code_hash=excluded.code_hash,salt=excluded.salt''', (user_id, 'issued:' + user_id, hashed, salt))
                c.execute('INSERT INTO account_access VALUES(?,?,?,?,0,?)', (user_id, org['director_id'], org['id'], lookup, timestamp()))
                c.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
                payload.append(dict(**row, id=user_id, code=code, school=org['name']))
            package_id = self.store_package(c, actor, org, title, instructions, payload)
            self.bump(c)
            result = self.ministry_snapshot(c, actor)
            result['packageId'] = package_id
            return result

    def store_package(self, c, actor, org, title, instructions, payload):
        identity = str(uuid.uuid4())
        c.execute('INSERT INTO delivery_packages VALUES(?,?,?,?,?,?,?,?,\'draft\',?,NULL,NULL,NULL)',
            (identity, actor['id'], org['director_id'], org['id'], title, instructions, seal(payload), len(payload), timestamp()))
        self.delivery_log(c, actor, identity, 'create')
        return identity

    def delivery_log(self, c, actor, package_id, action):
        c.execute('INSERT INTO delivery_audit VALUES(?,?,?,?,?)', (str(uuid.uuid4()), actor['id'], action, package_id, timestamp()))

    def package_authorized(self, c, actor, identity):
        package = c.execute('SELECT * FROM delivery_packages WHERE id=?', (identity,)).fetchone()
        require(package and (actor['role'] == 'ministry' and package['ministry_id'] == actor['id'] or
            actor['role'] == 'director' and package['director_id'] == actor['id'] and package['status'] != 'draft'), 'Пакет недоступен', 403)
        return package

    def package_action(self, token, fields, action):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            actor = self.actor(c, token)
            package = self.package_authorized(c, actor, fields.get('packageId'))
            identity = package['id']
            if action == 'send':
                require(actor['role'] == 'ministry')
                if package['status'] == 'draft':
                    require(c.execute('SELECT 1 FROM directors WHERE id=? AND active=1', (package['director_id'],)).fetchone(), 'Директор отключён', 409)
                    rows = unseal(package['sealed_rows'])
                    for row in rows:
                        if row.get('replacement'):
                            current = c.execute('SELECT lookup_id FROM account_access WHERE user_id=?', (row['id'],)).fetchone()
                            require(current and current['lookup_id'] == row['previousLookup'], 'Код уже изменён другим пакетом. Создайте новый перевыпуск.', 409)
                            salt = __import__('secrets').token_hex(16)
                            c.execute('UPDATE credentials SET code_hash=?,salt=? WHERE user_id=?', (code_hash(row['code'], salt), salt, row['id']))
                            c.execute('UPDATE account_access SET lookup_id=?,director_id=?,issued_at=? WHERE user_id=?',
                                (row['code'].split('-', 2)[1], package['director_id'], timestamp(), row['id']))
                            c.execute('DELETE FROM sessions WHERE user_id=?', (row['id'],))
                        c.execute('UPDATE account_access SET active=1 WHERE user_id=?', (row['id'],))
                    c.execute('UPDATE delivery_packages SET status=\'sent\',sent_at=? WHERE id=?', (timestamp(), identity))
                    self.delivery_log(c, actor, identity, 'send')
                    self.bump(c)
            elif action == 'distribute':
                require(actor['role'] == 'director' and package['opened_at'], 'Сначала откройте пакет', 400)
                if package['status'] != 'distributed':
                    c.execute('UPDATE delivery_packages SET status=\'distributed\',distributed_at=? WHERE id=?', (timestamp(), identity))
                    self.delivery_log(c, actor, identity, 'distribute')
                    self.bump(c)
            elif action == 'open':
                if actor['role'] == 'director' and not package['opened_at']:
                    c.execute('UPDATE delivery_packages SET opened_at=? WHERE id=?', (timestamp(), identity))
                    self.bump(c)
                self.delivery_log(c, actor, identity, 'open')
                rows = unseal(package['sealed_rows'])
                visible = []
                for row in rows:
                    access = c.execute('SELECT lookup_id FROM account_access WHERE user_id=?', (row['id'],)).fetchone()
                    current = package['status'] == 'draft' or access and access['lookup_id'] == row['code'].split('-', 2)[1]
                    visible.append({key: row[key] for key in ('id','name','role','className','school','code')} | {'current': bool(current)})
                return dict(id=identity, title=package['title'], instructions=package['instructions'], rows=visible, status=package['status'])
            else:
                require(False, 'Неизвестное действие', 400)
            return self.snapshot(c, actor)

    def ministry_reissue(self, token, fields):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            actor = self.actor(c, token)
            require(actor['role'] == 'ministry')
            org = self.ministry_recipient(c, fields)
            account = c.execute('''SELECT u.* FROM users u JOIN account_access a ON a.user_id=u.id
                WHERE u.id=? AND a.organization_id=? AND a.active=1''', (fields.get('userId'), org['id'])).fetchone()
            require(account, 'Активный профиль не найден в выбранной организации', 404)
            code, _, _, _ = issue_code('TCH' if account['role'] == 'teacher' else 'STD')
            previous = c.execute('SELECT lookup_id FROM account_access WHERE user_id=?', (account['id'],)).fetchone()[0]
            pending = dict(id=account['id'], name=account['name'], role=account['role'], className=account['class_name'],
                           school=org['name'], code=code, replacement=True, previousLookup=previous)
            # Credentials are rotated only when the replacement package is sent.
            identity = self.store_package(c, actor, org, 'Замена кода: ' + account['name'], INSTRUCTIONS, [pending])
            self.bump(c)
            result = self.ministry_snapshot(c, actor)
            result['packageId'] = identity
            return result
