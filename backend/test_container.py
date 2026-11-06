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
        import test_public_origin
        import test_quality
        import test_max_notifications

        suite = unittest.defaultTestLoader.loadTestsFromModule(test_local)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(test_public_origin))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(test_quality.QualityTests))
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(test_max_notifications.NotificationTests))
        result = unittest.TextTestRunner().run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
