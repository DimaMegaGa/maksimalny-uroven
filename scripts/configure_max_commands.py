"""Update command hints using the existing private bot configuration."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from max_bot import COMMANDS, api_request, load_config

if __name__ == '__main__':
    api_request(load_config(), 'PATCH', '/me/commands', {'commands': COMMANDS})
    print('MAX command hints updated: start, help, status, about, stop')
