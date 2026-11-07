import argparse
from repository import repository, BackendError


def main():
    parser = argparse.ArgumentParser(description='Локальный демонстрационный доступ министерства')
    parser.add_argument('command', choices=['create', 'reset', 'list'])
    parser.add_argument('--id')
    parser.add_argument('--label', default='Оператор министерства')
    parser.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    if args.command == 'list':
        with repository.connection() as c:
            for row in c.execute('SELECT id,label FROM ministries'):
                print(row['id'], row['label'])
        return
    if args.command == 'create':
        identity, code = repository.bootstrap_ministry(args.label)
    else:
        identity = args.id
        code = repository.rotate_ministry(identity)
    print('Демонстрационный кабинет. Интеграции с настоящим министерством нет.')
    print('Идентификатор:', identity)
    print('\nСЕКРЕТНЫЙ КОД КАБИНЕТА МИНИСТЕРСТВА:\n\n' + code)
    print('\nСохраните код. Повторно посмотреть его нельзя; доступ можно перевыпустить.')
    print('http://127.0.0.1:19112 → код кабинета')
    if args.interactive:
        input('После сохранения кода нажмите Enter...')


if __name__ == '__main__':
    try:
        main()
    except (BackendError, KeyboardInterrupt, EOFError) as error:
        print('Операция не завершена:', error)
        raise SystemExit(1)
