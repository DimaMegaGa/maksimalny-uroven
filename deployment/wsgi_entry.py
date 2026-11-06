import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not os.environ.get('MAKS_PUBLIC_ORIGIN'):
    raise RuntimeError('Set MAKS_PUBLIC_ORIGIN to the exact HTTPS address of this account')
os.environ.setdefault('MAKS_DB_PATH', str(ROOT / 'runtime/maks.sqlite3'))
os.environ.setdefault('MAKS_VAULT_KEY_FILE', str(ROOT / 'runtime/vault.key'))
sys.path.insert(0, str(ROOT / 'backend'))
from wsgi import application
