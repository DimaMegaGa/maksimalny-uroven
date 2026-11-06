"""MAX webhook. School accounts and sessions remain independent of messenger data."""

import hashlib
from contextlib import closing
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import time
import urllib.error
import urllib.request

API = 'https://platform-api2.max.ru'
CA_FINGERPRINT = 'd26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31'
RUNTIME = Path(os.environ.get('MAKS_DB_PATH', str(
    Path(__file__).resolve().parents[1] / 'runtime/maks.sqlite3'
))).resolve().parent
CONFIG = RUNTIME / 'max-bot.json'
CA_FILE = Path(__file__).with_name('russian_trusted_root_ca.pem')


class BotError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BotError('MAX API redirect refused')


def load_config():
    try:
        config = json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise BotError('MAX is not configured') from None
    if not isinstance(config, dict):
        raise BotError('Invalid MAX configuration')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', config.get('secret', '')):
        raise BotError('Invalid webhook secret')
    if not re.fullmatch(r'[!-~]{8,4096}', config.get('token', '')):
        raise BotError('Invalid bot token')
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+/', config.get('site_url', '')):
        raise BotError('Invalid platform URL')
    if not re.fullmatch(r'[A-Za-z0-9_]+', config.get('username', '')):
        raise BotError('Invalid bot username')
    return config


def api_request(config, method, path, body=None):
    if path not in ('/me', '/subscriptions', '/me/commands') and not re.fullmatch(
        r'/messages\?chat_id=-?\d+', path
    ):
        raise BotError('Unsupported MAX endpoint')
    try:
        pem = CA_FILE.read_text(encoding='ascii')
        der = ssl.PEM_cert_to_DER_cert(pem)
        if hashlib.sha256(der).hexdigest() != CA_FINGERPRINT:
            raise BotError('Unexpected MAX trust certificate')
        context = ssl.create_default_context()
        context.load_verify_locations(cadata=pem)
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
        request = urllib.request.Request(
            API + path,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            headers={'Authorization': config['token'], 'Content-Type': 'application/json'},
            method=method,
        )
        with opener.open(request, timeout=10) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise BotError('MAX response too large')
        result = json.loads(data)
        if not isinstance(result, dict) or result.get('success') is False:
            raise BotError('MAX rejected request')
        return result
    except (OSError, ValueError, urllib.error.URLError):
        # urllib errors may contain request context. Never return it to a client/log.
        raise BotError('MAX API unavailable') from None


COMMANDS = [
    {'name': 'start', 'description': 'Главное меню и вход в платформу'},
    {'name': 'help', 'description': 'Как войти, выполнить задание и подключить уведомления'},
    {'name': 'status', 'description': 'Проверить подключение уведомлений этого аккаунта MAX'},
    {'name': 'about', 'description': 'О платформе «МАКСимальный Уровень»'},
    {'name': 'stop', 'description': 'Отключить уведомления для этого аккаунта MAX'},
]


def reply_body(config, command='/start'):
    button = {'type': 'link', 'text': 'Открыть платформу', 'url': config['site_url']}
    if config.get('webapp_registered') is True:
        button = {'type': 'open_app', 'text': 'Открыть платформу', 'web_app': config['username']}
    texts = {
        '/start': 'МАКСимальный Уровень\nТвои усилия. Твои достижения.\n\n'
                  'Выполняй задания, участвуй в школьной жизни и получай баллы за подтверждённые результаты. '
                  'Здесь бот сообщит о новых заданиях и ответах учителя.\n\n'
                  'Как начать\n1. Открой платформу по кнопке.\n2. Выбери свою роль.\n'
                  '3. Введи ФИО и персональный код, полученный в школе.\n\n'
                  'Чтобы получать сообщения, открой «Профиль → Уведомления MAX → Подключить MAX» '
                  'и подтверди подключение в этом чате.\n\nКод входа в чат не отправляй.',
        '/help': 'Как пользоваться платформой\n\n'
                 'Вход: ученик и учитель вводят ФИО и персональный код. Код выдаёт директор или ответственный в школе. '
                 'Директор входит по своему коду. Если доступ не подходит, уточни данные в школе.\n\n'
                 'Задания: открой условия, напиши ответ и при необходимости добавь фото. '
                 'Баллы начисляются после подтверждения учителем. Если работа возвращена, прочитай комментарий и отправь исправление.\n\n'
                 'Обмен: выбери предмет и отправь запрос. Баллы списываются после одобрения; оценку выставляет учитель отдельно.\n\n'
                 'Уведомления: в своём профиле нажми «Подключить MAX», открой выданную ссылку в нужном аккаунте и подтверди запуск бота. '
                 'Проверить доставку можно там же. Обычно сообщение приходит в течение минуты. '
                 'Звук и показ на экране зависят от настроек MAX и телефона.\n\n'
                 '/status — проверить подключение\n/stop — отключить уведомления\n\n'
                 'Не отправляй сюда коды входа, пароли и ответы на задания: работы принимает учитель в мини-приложении.',
        '/about': 'МАКСимальный Уровень\nШкольная платформа достижений\n\n'
                  'Мы хотим, чтобы вклад ученика был заметен: дополнительное задание, участие в мероприятии и помощь школе '
                  'могут стать частью личного прогресса.\n\n'
                  'Учитель проверяет результат, ученик получает баллы и достижения. '
                  'Доступные поощрения и решения по обмену остаются под контролем школы.\n\n'
                  'В боте — уведомления и подсказки. Задания, история и достижения — в мини-приложении.',
        '/unknown': 'Я помогаю открыть школьную платформу и получить уведомления.\n\n'
                    'Задания, ответы учителю и обмен баллов находятся в мини-приложении. '
                    'Нажми «Открыть платформу» или «Помощь».\n\n'
                    'Коды входа и пароли в этот чат отправлять не нужно.',
    }
    return {
        'text': texts.get(command, texts['/start']),
        'notify': False,
        'attachments': [{'type': 'inline_keyboard', 'payload': {'buttons': [
            [button],
            [{'type': 'message', 'text': 'Помощь'}, {'type': 'message', 'text': 'Подключение'}],
            [{'type': 'message', 'text': 'О проекте'}],
        ]}}],
    }


def subscription_status(database, max_user_id, chat_id):
    # Only the verified webhook sender's own private chat may inspect this binding.
    if type(max_user_id) is not int or max_user_id <= 0:
        return 'Не удалось определить аккаунт MAX. Открой бота заново и отправь /status.'
    with closing(sqlite3.connect(database, timeout=12)) as c:
        row = c.execute(
            'SELECT u.name,u.role,a.active FROM max_links l JOIN users u ON u.id=l.user_id '
            'JOIN account_access a ON a.user_id=u.id WHERE l.max_user_id=? AND l.chat_id=?',
            (max_user_id, chat_id),
        ).fetchone()
    if not row:
        return ('Уведомления пока не подключены к этому аккаунту MAX.\n\n'
                'Открой платформу, войди в свою школьную учётку и выбери '
                '«Профиль → Уведомления MAX → Подключить MAX». Подтверди запуск в этом чате.\n\n'
                'Если меняешь аккаунт MAX, подключение нужно подтвердить заново.')
    if not row[2]:
        return 'Школьная учётная запись недоступна. Обратись к ответственному в школе.'
    role = {'student': 'Ученик', 'teacher': 'Учитель'}.get(row[1], 'Пользователь')
    return ('Уведомления подключены\n\n' + role + ': ' + row[0] + '\n'
            'Получатель — этот аккаунт MAX.\n\n'
            'Сюда приходят новые задания, результаты проверки и решения по обмену. '
            'Проверку доставки запусти в профиле платформы; обычно она занимает до минуты.\n\n'
            'Если сообщения есть в чате, но телефон молчит, проверь уведомления MAX и настройки устройства. '
            'Отключить доставку: /stop.')


def process_update(config, update, sender=api_request, now=None, receipts=None, database=None):
    """Handle private bot navigation; persist hashes, never chat contents."""
    now = time.time() if now is None else now
    if not isinstance(update, dict):
        raise ValueError('Invalid update')
    kind = update.get('update_type')
    if kind not in ('bot_started', 'message_created'):
        return
    timestamp = update.get('timestamp')
    if not isinstance(timestamp, (int, float)) or not now - 28800 <= timestamp / 1000 <= now + 300:
        return
    if kind == 'bot_started':
        user = update.get('user') or {}
        chat = update.get('chat_id')
        identity = f'{kind}:{chat}:{timestamp}'
        payload = update.get('payload') or ''
        command = '/start'
    else:
        message = update.get('message') or {}
        recipient = message.get('recipient') or {}
        if recipient.get('chat_type') != 'dialog':
            return
        user = message.get('sender') or {}
        chat = recipient.get('chat_id')
        body = message.get('body') or {}
        text = body.get('text')
        if not isinstance(text, str):
            return
        words = text.strip().split(maxsplit=1)
        command = words[0].lower() if words else ''
        aliases = {'помощь': '/help', 'подключение': '/status', 'о проекте': '/about'}
        command = aliases.get(text.strip().casefold(), command)
        if command not in ('/start', '/help', '/status', '/about', '/stop'):
            command = '/unknown'
        payload = words[1] if len(words) == 2 and command == '/start' else ''
        mid = body.get('mid')
        if not isinstance(mid, str) or not 1 <= len(mid) <= 256:
            return
        identity = f'{kind}:{chat}:{mid}'
    if user.get('is_bot') is not False or type(chat) is not int:
        return
    key = hashlib.sha256(identity.encode()).hexdigest()
    recipient_hash = hashlib.sha256(str(chat).encode()).hexdigest()
    target = Path(receipts) if receipts else RUNTIME / 'max-events.sqlite3'
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target, timeout=12)) as connection:
        if os.name != 'nt':
            target.chmod(0o600)
        connection.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, recipient TEXT, at REAL)')
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('DELETE FROM receipts WHERE at < ?', (now - 86400,))
        if connection.execute('SELECT 1 FROM receipts WHERE id = ?', (key,)).fetchone():
            return
        recent = connection.execute('SELECT 1 FROM receipts WHERE recipient = ? AND at > ?',
                                    (recipient_hash, now - (5 if command == '/unknown' else 1))).fetchone()
        pairing = isinstance(payload, str) and payload.startswith('notify_')
        if not recent or pairing or command == '/stop':
            body = reply_body(config, command)
            if pairing or command in ('/stop', '/status'):
                from max_notifications import finish_pairing, stop_from_bot
                if database is None:
                    from repository import repository
                    database = repository.path
                if pairing:
                    body['text'] = finish_pairing(database, payload, user.get('user_id'), chat)
                elif command == '/status':
                    body['text'] = subscription_status(database, user.get('user_id'), chat)
                else:
                    stop_from_bot(database, user.get('user_id'), chat)
                    body['text'] = 'Уведомления MAX отключены. Подключить их снова можно в профиле платформы.'
            sender(config, 'POST', f'/messages?chat_id={chat}', body)
        connection.execute('INSERT INTO receipts VALUES (?, ?, ?)', (key, recipient_hash, now))
        connection.commit()


def webhook(handler):
    try:
        config = load_config()
        secret = handler.headers.get('X-Max-Bot-Api-Secret', '')
        if not hmac.compare_digest(secret.encode(), config['secret'].encode()):
            handler.reply(403, {'error': 'Forbidden'})
            return
        size = int(handler.headers.get('Content-Length', '0'))
        if not 0 < size <= 65536:
            handler.reply(413, {'error': 'Invalid request size'})
            return
        process_update(config, json.loads(handler.rfile.read(size)))
        handler.reply(200, {'ok': True})
    except (ValueError, TypeError, AttributeError):
        handler.reply(400, {'error': 'Invalid MAX update'})
    except (BotError, sqlite3.Error, OSError):
        handler.reply(503, {'error': 'MAX integration temporarily unavailable'})
