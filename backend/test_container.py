"""Run integration tests with an isolated portable vault, without the real database."""
import os
import unittest
import tempfile
from pathlib import Path
from cryptography.fernet import Fernet


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        key = Path(directory) / 'vault.key'
        key.write_bytes(Fernet.generate_key())
        os.environ['MAKS_VAULT_KEY_FILE'] = str(key)
        import test_local
        result = unittest.main(module=test_local, exit=False).result
    raise SystemExit(0 if result.wasSuccessful() else 1)
