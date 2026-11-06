# МАКСимальный Уровень

Школьная платформа: учитель публикует задания и проверяет ответы, ученик получает баллы, достижения и может запросить обмен баллов на оценку. Отдельный портал министерства создаёт доступы по CSV/XLSX и отправляет готовые списки директору. Кабинет министерства демонстрационный; подключения к государственным реестрам нет.

## Посмотреть работающий проект

- [Бот и мини-приложение MAX](https://max.ru/ideya_fiks_30_bot) — нажмите «Начать» и «Открыть платформу».
- [Школьная платформа](https://maksimalny-uroven-30d.alwaysdata.net/).
- [Портал министерства](https://maksimalny-uroven-30d.alwaysdata.net/ministry/).

В архиве для жюри рядом с папкой проекта лежат стартовая инструкция и отдельный файл демонстрационных доступов. Эти коды относятся к опубликованному сайту. При самостоятельном запуске создаётся своя база и новые учётки.

## Запуск через Python на Windows

Нужен Python 3.11 или новее. Откройте терминал в этой папке:

```sh
python -m pip install -r requirements.txt
python start.py
```

Можно также открыть `start.cmd` двойным щелчком. Он запускает оба портала:

| Портал | Адрес |
|---|---|
| Школа: ученик, учитель, директор | http://127.0.0.1:19111/ |
| Министерство | http://127.0.0.1:19112/ |

Запуск без открытия браузера: `python start.py --no-browser`.
Остановка: `python stop.py` или `stop.cmd`. Резервная копия: `backup.cmd`.
Не открывайте `index.html` напрямую: авторизации нужен Python-сервер.
Для Linux/macOS используйте Docker ниже: он также настраивает переносимый ключ шифрования.

## Создать доступы в своей копии

В новом терминале из той же папки выполните:

```sh
python backend/manage_access.py create-director --school "Школа проверки" --label "Директор"
python backend/manage_ministry.py create --label "Оператор министерства"
```

Сохраните показанные коды. Директор входит на школьном сайте, министерство — на отдельном портале.
Далее в министерстве выберите организацию и директора, загрузите `templates/roster-template.csv`, создайте пакет и отправьте его директору. После отправки профили учеников и учителей активируются. Их ФИО и коды доступны в пакете директора.

Подробности: [доступ и списки](docs/ACCESS.md).

## Запуск через Docker

Нужны Docker и Compose v2. Выполняйте команды из этой папки:

```sh
docker compose build
docker compose up -d
docker compose ps
```

Адреса те же: школа — `http://127.0.0.1:19111/`, министерство — `http://127.0.0.1:19112/`.
Для создания первых доступов в контейнерах:

```sh
docker compose exec school python backend/manage_access.py create-director --school "Школа проверки" --label "Директор"
docker compose exec ministry python backend/manage_ministry.py create --label "Оператор министерства"
```

Остановка: `docker compose down`. База сохраняется в томе `maks-data`; не удаляйте том, если хотите сохранить учётки и результаты.

Сборка и отдельный запуск контейнера школьного сайта:

```sh
docker build -t maks-level:submission .
docker run --rm --name maks-school -p 127.0.0.1:19111:8765 -v maks-data:/data maks-level:submission
```

Экспорт образа в файл и загрузка на другой компьютер:

```sh
docker save -o maks-level-image.tar maks-level:submission
docker load -i maks-level-image.tar
```

В архив включён Dockerfile для сборки; готовый файл Docker-образа `.tar` в него не вложен. Сборка Docker на ПК автора не проверялась; исходники содержат workflow сборки и проверок в `.github/workflows/container.yml`.

## Структура проекта

| Папка или файл | Назначение |
|---|---|
| `frontend/` | Страницы, стили, изображения, логика интерфейса и MAX Bridge |
| `backend/` | Python API, SQLite, роли, задания, баллы и интеграция с ботом |
| `templates/` | Шаблон списка для импорта |
| `tests/`, `backend/test_*.py` | Автоматические проверки на отдельных данных |
| `scripts/` | Доставка уведомлений, экспорт и упаковка |
| `deployment/` | Размещение на сервере |
| `docs/` | Описание доступа, архитектуры и интеграции MAX |
| `Dockerfile`, `compose.yaml` | Сборка и запуск двух порталов |
| `requirements.txt` | Библиотеки Python с версиями |

База и закрытые настройки создаются во время работы. В архив не входят рабочая база alwaysdata, токен бота и ключи шифрования.

## Проверки

```sh
python -m pip install -r requirements.txt
python backend/test_container.py
node tests/test-client.cjs
node tests/test-max-bridge.cjs
python tests/test-max-bot.py
```

Для JavaScript-проверок нужен Node.js 18 или новее. Тесты используют отдельные временные базы.

## Размещение и уведомления MAX

Опубликованная версия размещена на alwaysdata. Порядок собственной установки: [deployment/CASE.md](deployment/CASE.md).
Для локального просмотра доступ к MAX API не нужен. Для уведомлений в своей установке потребуются свой бот, закрытая конфигурация, HTTPS webhook и планировщик доставки.

- [Архитектура](docs/ARCHITECTURE.md).
- [Подключение MAX](docs/MAX.md).
- [Уведомления от бота](docs/MAX-NOTIFICATIONS.md).
- [Дополнительные команды запуска](docs/RUNNING.md).

## Docker-образ для жюри

Готовый образ публикуется в [релизах GitHub](https://github.com/DimaMegaGa/maksimalny-uroven/releases) после успешной сборки и тестов. Скачайте `maks-level-image.tar.gz` и выполните `docker load -i maks-level-image.tar.gz`. Имя образа — `maks-level:submission`.
