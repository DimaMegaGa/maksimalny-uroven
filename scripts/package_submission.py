"""Build a source-only archive without local credentials, databases or logs."""

from pathlib import Path
import argparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'README.md',
    'backend/russian_trusted_root_ca.pem',
    'Dockerfile',
    'compose.yaml',
    'compose.cloud.yaml',
    'requirements.txt',
    '.gitignore',
    '.dockerignore',
    'start.cmd',
    'stop.cmd',
    'backup.cmd',
    'create-director.cmd',
    'create-ministry.cmd',
    'start-ministry.cmd',
    'check-max.cmd',
    'start.py',
    'stop.py',
    'backup.py',
}
FOLDERS = {'frontend', 'backend', 'tests', 'templates', 'docs', 'scripts', 'deployment', '.github'}
EXTENSIONS = {
    '.py',
    '.js',
    '.mjs',
    '.cjs',
    '.css',
    '.html',
    '.svg',
    '.png',
    '.sql',
    '.md',
    '.csv',
    '.txt',
    '.yaml',
    '.yml',
    '.toml',
    '.example',
}
EXCLUDED = {'data', 'runtime', 'backups', 'logs', '__pycache__', 'node_modules', '.git'}


def package(destination):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if not path.is_file() or path.is_symlink():
            continue
        if relative.as_posix() in FILES:
            paths.append(path)
            continue
        if relative.parts[0] not in FOLDERS or EXCLUDED.intersection(relative.parts):
            continue
        if (
            path.suffix not in EXTENSIONS
            or path.name.startswith('.env')
            or path.name == 'cloud.env'
        ):
            continue
        paths.append(path)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, 'maksimalny-uroven/' + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(not EXCLUDED.intersection(Path(name).parts) for name in archive.namelist())
    print(f'Verified source archive: {len(paths)} files; {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    package(parser.parse_args().destination)
