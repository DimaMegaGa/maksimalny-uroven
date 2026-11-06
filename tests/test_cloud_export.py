import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from cryptography.fernet import Fernet

spec = importlib.util.spec_from_file_location(
    'export_cloud', Path(__file__).resolve().parents[1] / 'scripts/export_cloud_database.py'
)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        source, key = root / 'source.sqlite3', root / 'source.key'
        key.write_bytes(Fernet.generate_key())
        payload = json.dumps([{'name': 'Вымышленный участник', 'code': 'fixture-only'}]).encode()
        sealed = 'fernet1:' + Fernet(key.read_bytes()).encrypt(payload).decode()
        with closing(sqlite3.connect(source)) as connection:
            connection.execute(
                'CREATE TABLE delivery_packages(id TEXT PRIMARY KEY,sealed_rows TEXT)'
            )
            connection.execute('INSERT INTO delivery_packages VALUES(?,?)', ('package', sealed))
            for name in ('sessions', 'director_sessions', 'ministry_sessions', 'login_attempts'):
                connection.execute('CREATE TABLE ' + name + '(id TEXT)')
                connection.execute('INSERT INTO ' + name + ' VALUES(?)', ('old-session',))
            connection.commit()
        return source, key, payload

    def test_copy_preserves_original_and_rotates_encryption(self):
        with tempfile.TemporaryDirectory() as directory:
            source, key, payload = self.fixture(directory)
            before = hashlib.sha256(source.read_bytes()).digest()
            destination = Path(directory) / 'export'
            exporter.export(source, destination, key)
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
            self.assertNotEqual(key.read_bytes(), (destination / 'vault.key').read_bytes())
            with closing(sqlite3.connect(destination / 'maks.sqlite3')) as connection:
                value = connection.execute('SELECT sealed_rows FROM delivery_packages').fetchone()[
                    0
                ]
                self.assertEqual(
                    Fernet((destination / 'vault.key').read_bytes()).decrypt(value[8:].encode()),
                    payload,
                )
                for table in (
                    'sessions',
                    'director_sessions',
                    'ministry_sessions',
                    'login_attempts',
                ):
                    self.assertEqual(
                        connection.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0
                    )
            with self.assertRaises(FileExistsError):
                exporter.export(source, destination, key)

    def test_wrong_key_does_not_leave_a_partial_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source, key, _ = self.fixture(directory)
            wrong = Path(directory) / 'wrong.key'
            wrong.write_bytes(Fernet.generate_key())
            destination = Path(directory) / 'export'
            with self.assertRaises(Exception):
                exporter.export(source, destination, wrong)
            self.assertFalse(destination.exists())
            with closing(sqlite3.connect(source)) as connection:
                self.assertEqual(
                    connection.execute('SELECT count(*) FROM sessions').fetchone()[0], 1
                )


if __name__ == '__main__':
    unittest.main()
