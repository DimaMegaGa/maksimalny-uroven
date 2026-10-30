"""Consistent SQLite online backup; works while the local server is running."""
import sqlite3
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parent
source = root / 'backend' / 'data' / 'maks.sqlite3'
if not source.exists():
    raise SystemExit('Database not created. Run start.cmd first.')
target = root / 'backups' / ('maks-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
target.parent.mkdir(exist_ok=True)
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
src.close()
dst.close()
print(target)
