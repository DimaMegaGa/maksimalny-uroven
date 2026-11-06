import argparse
from repository import repository, BackendError


def main():
    parser = argparse.ArgumentParser(
        description='Локальная выдача кодов директора. Через сайт эта операция недоступна.'
    )
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser(
        'create-director', help='Создать директора и назначить его организации'
    )
    create.add_argument('--school', action='append')
    create.add_argument('--label', default='Директор')
    create.add_argument('--interactive', action='store_true')
    commands.add_parser('list-directors', help='Показать идентификаторы директоров без кодов')
    rotate = commands.add_parser(
        'reset-director', help='Выдать новый код и отозвать старые сеансы директора'
    )
    rotate.add_argument('--id', required=True)
    rotate.add_argument('--interactive', action='store_true')
    args = parser.parse_args()
    if args.command == 'list-directors':
        with repository.connection() as c:
            rows = c.execute('SELECT id,label,active FROM directors ORDER BY created_at').fetchall()
        for row in rows:
            print(row['id'], '—', row['label'], '—', 'активен' if row['active'] else 'отключён')
        return
    if args.command == 'create-director':
        schools = args.school
        if not schools:
            print('Локальная настройка. Код не выдан Министерством образования.')
            print(
                'Укажите точное название школы. Для нескольких организаций разделите названия точкой с запятой.'
            )
            schools = [
                s.strip() for s in input('Образовательная организация: ').split(';') if s.strip()
            ]
        director_id, code = repository.bootstrap_director(schools, args.label)
    else:
        director_id = args.id
        code = repository.rotate_director(director_id)
    print('\nИдентификатор директора:', director_id)
    print('\nСПЕЦИАЛЬНЫЙ КОД ДИРЕКТОРА:\n\n' + code)
    print('\nСохраните код в своём менеджере паролей и передайте только директору.')
    print('Повторно получить этот код из базы нельзя: сохранён только хеш.')
    print('Для входа: http://127.0.0.1:8765 → Директор → этот код.')
    if args.interactive:
        input('\nКогда сохраните код, нажмите Enter, чтобы закрыть окно...')


if __name__ == '__main__':
    try:
        main()
    except (BackendError, EOFError, KeyboardInterrupt) as error:
        print('\nОперация не завершена:', str(error))
        raise SystemExit(1)
