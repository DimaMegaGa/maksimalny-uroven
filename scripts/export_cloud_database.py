"""Create a separate encrypted cloud copy without changing the source database."""

import argparse
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from cryptography.fernet import Fernet


def export(source, destination, source_key=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    destination.mkdir(parents=True, exist_ok=False)
    try:
        target = destination / 'maks.sqlite3'
        key = Fernet.generate_key()
        cipher = Fernet(key)
        source_cipher = Fernet(Path(source_key).read_bytes().strip()) if source_key else None
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(target)) as copy:
                original.backup(copy)
        with closing(sqlite3.connect(target)) as copy:
            if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Source database integrity check failed')
            rows = copy.execute('SELECT id,sealed_rows FROM delivery_packages').fetchall()
            for identity, value in rows:
                if value.startswith('fernet1:'):
                    if source_cipher is None:
                        raise ValueError(
                            'Provide --source-vault-key for existing portable packages'
                        )
                    raw = source_cipher.decrypt(value[len('fernet1:') :].encode('ascii'))
                else:
                    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
                    from package_vault import transform

                    raw = transform(base64.b64decode(value, validate=True), decrypt=True)
                if not isinstance(json.loads(raw), list):
                    raise ValueError('Invalid delivery package')
                sealed = 'fernet1:' + cipher.encrypt(raw).decode('ascii')
                copy.execute(
                    'UPDATE delivery_packages SET sealed_rows=? WHERE id=?', (sealed, identity)
                )
            for table in ('sessions', 'director_sessions', 'ministry_sessions', 'login_attempts'):
                copy.execute('DELETE FROM ' + table)
            copy.commit()
        descriptor = os.open(destination / 'vault.key', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(key)
        (destination / 'export.json').write_text(
            json.dumps(
                {'format': 1, 'encryptedPackages': len(rows), 'sessionsRevokedInCopy': True}
            ),
            encoding='utf-8',
        )
    except Exception:
        for name in (
            'maks.sqlite3',
            'maks.sqlite3-journal',
            'maks.sqlite3-wal',
            'maks.sqlite3-shm',
            'vault.key',
            'export.json',
        ):
            (destination / name).unlink(missing_ok=True)
        destination.rmdir()
        raise
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--source-vault-key')
    args = parser.parse_args()
    try:
        directory = export(args.source, args.destination, args.source_vault_key)
        print('Encrypted cloud copy prepared:', directory)
        print('Source database unchanged. Nothing uploaded. Keep vault.key private.')
    except Exception as error:
        raise SystemExit(
            'Export stopped: '
            + type(error).__name__
            + '. Check source database, Windows account and source vault key.'
        ) from None
