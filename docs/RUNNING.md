# Запуск проекта

Основная пошаговая инструкция находится в [README.md](../README.md).

## Python на Windows

Из корня проекта:

```sh
python -m pip install -r requirements.txt
python start.py
```

Школа: http://127.0.0.1:19111/. Министерство: http://127.0.0.1:19112/.
Оба портала используют общую локальную базу, но разные сеансы авторизации.

- Только школа: `python start.py --site school`.
- Только министерство: `python start.py --site ministry`.
- Без открытия браузера: `python start.py --no-browser`.
- Остановка: `python stop.py`.
- Резервная копия: `python backup.py`.

Команды создания директора и министерства приведены в README. Ученики и учителя создаются через импорт списка министерством.

## Ручной запуск HTTP-сервера

Если запускаете сервер напрямую, порт задаётся явно. В двух терминалах:

```sh
python backend/server.py --site school --port 19111
python backend/server.py --site ministry --port 19112
```

Остановка каждого процесса: Ctrl+C в его терминале. Для Linux/macOS используйте Docker из README либо предварительно настройте переносимый ключ `MAKS_VAULT_KEY_FILE`.

## Размещение на alwaysdata

См. [deployment/CASE.md](../deployment/CASE.md). Не переносите рабочую базу или чужие токены в публичный репозиторий.
