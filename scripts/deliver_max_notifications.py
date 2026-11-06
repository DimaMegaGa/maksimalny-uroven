"""One short invocation per minute via the hosting scheduler, no background daemon."""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--database', default=os.environ.get('MAKS_DB_PATH', str(ROOT / 'runtime/maks.sqlite3')))
args = parser.parse_args()
database = Path(args.database).resolve()
if not database.is_file():
    raise SystemExit('School database does not exist')
os.environ['MAKS_DB_PATH'] = str(database)
sys.path.insert(0, str(ROOT / 'backend'))
from max_bot import load_config, api_request
from max_notifications import deliver

try:
    print('MAX notifications sent:', deliver(database, load_config(), api_request))
except Exception:
    raise SystemExit('MAX notification delivery unavailable; private details omitted') from None
