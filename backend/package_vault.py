"""Protect delivery attachments with DPAPI or an explicitly configured portable key."""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from access_control import BackendError


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def transform(raw, decrypt=False):
    if os.name != 'nt':
        raise BackendError('Хранилище пакетов настроено для Windows DPAPI. Для другого сервера нужен отдельный защищённый ключ.', 503)
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise BackendError('Не удалось открыть защищённый пакет под текущей учётной записью Windows.', 503)
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL('kernel32', use_last_error=True).LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)


def portable_cipher():
    key_file = os.environ.get('MAKS_VAULT_KEY_FILE')
    if not key_file:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(Path(key_file).read_bytes().strip())
    except (ImportError, OSError, ValueError):
        raise BackendError('Проверьте библиотеку cryptography и файл ключа хранилища.', 503) from None


def seal(payload):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    cipher = portable_cipher()
    if cipher is not None:
        return 'fernet1:' + cipher.encrypt(raw).decode('ascii')
    return base64.b64encode(transform(raw)).decode()


def unseal(value):
    if value.startswith('fernet1:'):
        cipher = portable_cipher()
        if cipher is None:
            raise BackendError('Для открытия пакета нужен исходный файл ключа хранилища.', 503)
        try:
            return json.loads(cipher.decrypt(value[len('fernet1:'):].encode('ascii')))
        except Exception:
            raise BackendError('Не удалось проверить или расшифровать пакет.', 503) from None
    return json.loads(transform(base64.b64decode(value), decrypt=True))
