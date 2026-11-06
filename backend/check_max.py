"""Read-only MAX bot diagnostics. No token persistence or bot configuration changes."""

import getpass
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
import warnings
from urllib.parse import urlsplit
from max_bot import CA_FILE, CA_FINGERPRINT


API = 'https://platform-api2.max.ru'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError('redirect_refused')


def fetch(path, token):
    if path not in ('/me', '/subscriptions'):
        raise ValueError('Unsupported diagnostic endpoint')
    request = urllib.request.Request(
        API + path, headers={'Authorization': token, 'Accept': 'application/json'}, method='GET'
    )
    pem = CA_FILE.read_text(encoding='ascii')
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != CA_FINGERPRINT:
        raise ValueError('Unexpected trust certificate')
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=pem)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=12) as response:
        data = response.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError('Response too large')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Unexpected response')
    return result


def safe(value, token):
    return ''.join(c for c in str(value).replace(token, '[скрыто]') if c.isprintable())[:200]


def explain(error):
    if isinstance(error, urllib.error.HTTPError):
        return {
            401: 'MAX не принял токен. Проверьте, что это API-токен бота, а не одноразовый код получения доступа.',
            403: 'MAX запретил доступ. Нужно уточнить права выданного токена у организаторов.',
            429: 'Слишком много запросов. Повторите проверку позже.',
        }.get(
            error.code,
            'MAX вернул ошибку HTTP '
            + str(error.code)
            + '. Повторите позже или уточните условия доступа.',
        )
    if isinstance(error, urllib.error.URLError) and isinstance(
        error.reason, (ssl.SSLError, ssl.CertificateError)
    ):
        return 'Не удалось проверить сертификат сервера MAX. Проверка защиты не отключалась. Нужно проверить сертификаты по официальной инструкции MAX.'
    if isinstance(error, (urllib.error.URLError, OSError)):
        return 'Не удалось подключиться к API MAX. Проверьте интернет и доступность сервиса; это ещё не означает, что токен неверный.'
    return 'MAX вернул неожиданный ответ. Токен не сохранён; требуется дополнительная проверка.'


def main():
    print('Проверка токена бота MAX')
    print('Будут выполнены только запросы информации о боте и его подписках.')
    print('Настройки не изменяются, сообщения не отправляются, токен не сохраняется.')
    print('При вводе токена символы не отображаются — это нормально.\n')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            token = getpass.getpass('Вставьте токен и нажмите Enter: ').strip()
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print(
            '\nВвод отменён или скрытый ввод недоступен. Запустите check-max.cmd обычным двойным щелчком.'
        )
        return 1
    if not 8 <= len(token) <= 4096 or not all(33 <= ord(c) <= 126 for c in token):
        print(
            'Проверьте токен: вставьте только его значение без кавычек, пробелов и переноса строки.'
        )
        return 1
    try:
        bot = fetch('/me', token)
        if bot.get('is_bot') is not True or not isinstance(bot.get('user_id'), int):
            print(
                'Ответ не подтверждает, что это токен бота MAX. Уточните назначение токена у организаторов.'
            )
            return 1
    except (urllib.error.URLError, OSError, ValueError) as error:
        print('\n' + explain(error))
        return 1
    print('\nТокен принят MAX. Бот найден.')
    print('Название:', safe(bot.get('first_name') or bot.get('name') or 'Не указано', token))
    print('Идентификатор:', bot['user_id'])
    username = bot.get('username')
    if (
        isinstance(username, str)
        and re.fullmatch(r'[A-Za-z0-9_]+', username)
        and token not in username
    ):
        print('Обычная ссылка на бота: https://max.ru/' + username)
    else:
        print('Публичное имя бота не получено. Ссылку потребуется уточнить у организаторов.')
    try:
        data = fetch('/subscriptions', token)
        subscriptions = data.get('subscriptions')
        if not isinstance(subscriptions, list):
            raise ValueError('Unexpected subscriptions')
        print('\nНастроенных подписок на уведомления:', len(subscriptions))
        domains = set()
        for item in subscriptions:
            if not isinstance(item, dict):
                continue
            host = urlsplit(str(item.get('url', ''))).hostname or ''
            if host and re.fullmatch(r'[A-Za-z0-9.-]+', host) and token not in host:
                domains.add(host)
        if domains:
            print('Домены получателей:', ', '.join(sorted(domains)))
            print('У бота уже настроены получатели событий. Их настройки сохранены без изменений.')
        else:
            print('Эта проверка не определяет, получает ли другой сервис события методом опроса.')
    except (urllib.error.URLError, OSError, ValueError) as error:
        print('\nБот найден, но проверить подписки не удалось. ' + explain(error))
    print(
        '\nПередайте для следующего шага название и обычную ссылку на бота. Сам токен не отправляйте.'
    )
    print('Проверка не определяет, кто имеет доступ к настройке URL мини-приложения.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nПроверка отменена.')
        raise SystemExit(1)
