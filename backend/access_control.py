import hashlib
import hmac
import json
import secrets
import time
import uuid
import re


class BackendError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def require(condition, message='Действие недоступно', status=403):
    if not condition:
        raise BackendError(message, status)


def timestamp():
    return int(time.time() * 1000)


def normalize(value):
    return ' '.join(str(value).split()).casefold()


def field(value, limit):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, 'Проверьте заполнение полей', 400)
    return ' '.join(value.split())


def issue_code(prefix):
    lookup = secrets.token_hex(5).upper()
    code = prefix + '-' + lookup + '-' + secrets.token_urlsafe(18)
    salt = secrets.token_hex(16)
    return code, lookup, salt, code_hash(code, salt)


def code_hash(code, salt):
    return hashlib.pbkdf2_hmac('sha256', code.encode(), bytes.fromhex(salt), 600_000).hex()


class AccessControl:
    def init_access(self, c):
        c.executescript('''
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS directors (
                id TEXT PRIMARY KEY, label TEXT NOT NULL, lookup_id TEXT NOT NULL UNIQUE,
                code_hash TEXT NOT NULL, salt TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                created_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS director_organizations (
                director_id TEXT NOT NULL REFERENCES directors(id),
                organization_id TEXT NOT NULL REFERENCES organizations(id),
                PRIMARY KEY(director_id,organization_id)
            );
            CREATE TABLE IF NOT EXISTS director_sessions (
                token_hash TEXT PRIMARY KEY, director_id TEXT NOT NULL REFERENCES directors(id),
                expires_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_access (
                user_id TEXT PRIMARY KEY REFERENCES users(id),
                director_id TEXT NOT NULL REFERENCES directors(id),
                organization_id TEXT NOT NULL REFERENCES organizations(id),
                lookup_id TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1,
                issued_at BIGINT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS access_audit (
                id TEXT PRIMARY KEY, director_id TEXT NOT NULL REFERENCES directors(id),
                action TEXT NOT NULL, user_id TEXT REFERENCES users(id), created_at BIGINT NOT NULL
            );
        ''')
        c.execute('PRAGMA user_version=3')

    def bootstrap_director(self, schools, label='Директор'):
        require(isinstance(schools, list) and 1 <= len(schools) <= 50, 'Укажите образовательную организацию', 400)
        schools = list(dict.fromkeys(field(s, 100) for s in schools))
        label = field(label, 80)
        director_id = str(uuid.uuid4())
        code, lookup, salt, hashed = issue_code('DIR')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO directors VALUES(?,?,?,?,?,?,?)', (director_id, label, lookup, hashed, salt, 1, timestamp()))
            for school in schools:
                c.execute('INSERT OR IGNORE INTO organizations VALUES(?,?,?)', (str(uuid.uuid4()), school, normalize(school)))
                organization_id = c.execute('SELECT id FROM organizations WHERE name_key=?', (normalize(school),)).fetchone()[0]
                c.execute('INSERT INTO director_organizations VALUES(?,?)', (director_id, organization_id))
            self.bump(c)
        return director_id, code

    def rotate_director(self, director_id):
        code, lookup, salt, hashed = issue_code('DIR')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            require(c.execute('SELECT 1 FROM directors WHERE id=?', (director_id,)).fetchone(), 'Директор не найден', 404)
            c.execute('UPDATE directors SET lookup_id=?,code_hash=?,salt=?,active=1 WHERE id=?', (lookup, hashed, salt, director_id))
            c.execute('DELETE FROM director_sessions WHERE director_id=?', (director_id,))
            self.bump(c)
        return code

    def access_actor(self, c, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        staff = c.execute('''SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
            JOIN account_access ON account_access.user_id=users.id AND account_access.active=1
            WHERE sessions.token_hash=? AND sessions.expires_at>?''', (digest, timestamp())).fetchone()
        if staff:
            from repository import public
            return public(staff)
        director = c.execute('''SELECT d.* FROM director_sessions s JOIN directors d ON d.id=s.director_id
            WHERE s.token_hash=? AND s.expires_at>? AND d.active=1''', (digest, timestamp())).fetchone()
        if not director:
            ministry = c.execute('''SELECT m.* FROM ministry_sessions s JOIN ministries m ON m.id=s.ministry_id
                WHERE s.token_hash=? AND s.expires_at>? AND m.active=1''', (digest, timestamp())).fetchone()
            require(ministry, 'Войдите в аккаунт', 401)
            return dict(id=ministry['id'], role='ministry', name='Оператор министерства' if ministry['label'] == 'Министерство · демонстрация' else ministry['label'], school='Управление образовательными организациями',
                        className='', avatar='', achievements=[], subjects=[], createdAt=ministry['created_at'])
        schools = [r[0] for r in c.execute('''SELECT o.name FROM organizations o JOIN director_organizations x
            ON x.organization_id=o.id WHERE x.director_id=? ORDER BY o.name''', (director['id'],))]
        return dict(id=director['id'], role='director', name=director['label'], school=' · '.join(schools), className='',
                    avatar='', achievements=[], subjects=[], createdAt=director['created_at'])

    def access_login(self, fields, client='local'):
        require(fields.get('register') is not True, 'Самостоятельная регистрация отключена. Обратитесь к директору.', 403)
        role = fields.get('role')
        require(role in ('student', 'teacher', 'director', 'ministry'), 'Выберите способ входа', 400)
        code = fields.get('code')
        require(isinstance(code, str) and 6 <= len(code.strip()) <= 128, 'Введите специальный код', 400)
        code = code.strip()
        name = field(fields.get('name'), 80) if role not in ('director', 'ministry') else ''
        pieces = code.split('-', 2)
        lookup = pieces[1] if len(pieces) == 3 and re.fullmatch(r'[A-F0-9]{10}', pieces[1]) else 'invalid'
        identity = 'access:' + hashlib.sha256((role + ':' + lookup + ':' + (normalize(name) if lookup == 'invalid' else '')).encode()).hexdigest()
        client_identity = 'client:' + hashlib.sha256(str(client).encode()).hexdigest()
        error = None
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM login_attempts WHERE reset_at<=?', (timestamp(),))
            for limiter, limit in [(identity, 10), (client_identity, 40)]:
                attempt = c.execute('SELECT * FROM login_attempts WHERE identity=?', (limiter,)).fetchone()
                require(not attempt or attempt['failures'] < limit, 'Слишком много попыток. Повторите через 15 минут.', 429)
            if role in ('director', 'ministry'):
                table = 'directors' if role == 'director' else 'ministries'
                record = c.execute('SELECT id,code_hash,salt FROM ' + table + ' WHERE lookup_id=? AND active=1', (lookup,)).fetchone()
            else:
                record = c.execute('''SELECT u.id,u.role,u.name,cr.code_hash,cr.salt FROM account_access a
                    JOIN users u ON u.id=a.user_id JOIN credentials cr ON cr.user_id=u.id
                    WHERE a.lookup_id=? AND a.active=1''', (lookup,)).fetchone()
            hashed = code_hash(code, record['salt'] if record else '00' * 16)
            valid = record and hmac.compare_digest(hashed, record['code_hash'])
            if role not in ('director', 'ministry'):
                valid = valid and record['role'] == role and normalize(record['name']) == normalize(name)
            if not valid:
                for limiter in (identity, client_identity):
                    c.execute('''INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(identity)
                        DO UPDATE SET failures=failures+1''', (limiter, timestamp() + 900_000))
                error = BackendError('ФИО или специальный код неверны' if role not in ('director', 'ministry') else 'Специальный код неверен', 401)
            else:
                token = secrets.token_urlsafe(32)
                digest = hashlib.sha256(token.encode()).hexdigest()
                if role in ('director', 'ministry'):
                    session_table = 'director_sessions' if role == 'director' else 'ministry_sessions'
                    c.execute('DELETE FROM ' + session_table + ' WHERE expires_at<=?', (timestamp(),))
                    c.execute('INSERT INTO ' + session_table + ' VALUES(?,?,?)', (digest, record['id'], timestamp() + 28_800_000))
                else:
                    c.execute('DELETE FROM sessions WHERE expires_at<=?', (timestamp(),))
                    c.execute('INSERT INTO sessions VALUES(?,?,?)', (digest, record['id'], timestamp() + 604_800_000))
                c.execute('DELETE FROM login_attempts WHERE identity=?', (identity,))
                result = self.snapshot(c, self.access_actor(c, token))
        if error:
            raise error
        return result, token

    def director_snapshot(self, c, user):
        organizations = [dict(r) for r in c.execute('''SELECT o.id,o.name FROM organizations o JOIN director_organizations x
            ON x.organization_id=o.id WHERE x.director_id=? ORDER BY o.name''', (user['id'],))]
        by_school = {normalize(o['name']): o for o in organizations}
        accounts = []
        for row in c.execute('''SELECT u.id,u.role,u.name,u.school,u.class_name,u.created_at,
                a.organization_id,a.active,a.issued_at FROM users u LEFT JOIN account_access a ON a.user_id=u.id'''):
            organization = by_school.get(normalize(row['school']))
            if organization and row['active'] != 0:
                accounts.append(dict(id=row['id'], role=row['role'], name=row['name'], school=row['school'], className=row['class_name'],
                    organizationId=organization['id'], status='legacy' if row['active'] is None else 'active' if row['active'] else 'disabled',
                    createdAt=row['created_at'], issuedAt=row['issued_at']))
        return dict(userId=user['id'], revision=self.revision(c), db=dict(users=[user],tasks=[],submissions=[],notifications=[],exchanges=[],ledger=[],activities=[]),
                    admin=dict(organizations=organizations, packages=self.package_list(c, user), accounts=sorted(accounts, key=lambda a:(a['name'].casefold(),a['school']))))

    def director_create_account(self, token, fields):
        with self.connection() as c:
            self.actor(c, token)
        require(False, 'Аккаунты создаются только через кабинет министерства', 403)

    def director_reissue_code(self, token, fields):
        with self.connection() as c:
            self.actor(c, token)
        require(False, 'Перевыпуск кодов выполняет министерство', 403)
