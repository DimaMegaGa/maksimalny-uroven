"""Initialize a persistent portable key and replace this process with the server."""
import os
import sys
from pathlib import Path
from cryptography.fernet import Fernet


def main():
    path = Path(os.environ['MAKS_VAULT_KEY_FILE'])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        Fernet(path.read_bytes().strip())
    else:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(Fernet.generate_key())
    os.execv(sys.executable, [sys.executable, str(Path(__file__).with_name('server.py')), '--bind', os.environ.get('MAKS_BIND', '127.0.0.1'), *sys.argv[1:]])


if __name__ == '__main__':
    main()
