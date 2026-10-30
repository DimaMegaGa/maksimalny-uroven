"""Stop only the server holding this installation's random control token."""
import json
import urllib.request
import urllib.error
from pathlib import Path

root = Path(__file__).resolve().parent / 'backend' / 'data'
for filename in ('server-control.json', 'ministry-server-control.json'):
    path = root / filename
    if not path.exists():
        continue
    control = json.loads(path.read_text(encoding='utf-8'))
    request = urllib.request.Request('http://127.0.0.1:' + str(control['port']) + '/api/shutdown',
        data=json.dumps({'controlToken': control['token']}).encode(),
        headers={'X-Maks-Request': '1', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        print(f"Server on port {control['port']} stopped. Database preserved.")
    except urllib.error.URLError:
        print(f"Server on port {control['port']} is not running.")
