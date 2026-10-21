"""Windows Credential Manager adapter for API secrets."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol

_TARGET_NAME = "OfficeAI/OpenAI/ApiKey"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_MAX_SECRET_BYTES = 5_120


class CredentialStoreError(RuntimeError):
    """Raised when a secret cannot be stored or read safely."""


class CredentialStore(Protocol):
    def save_api_key(self, api_key: str) -> None: ...
    def read_api_key(self) -> str | None: ...
    def delete_api_key(self) -> None: ...


class WindowsCredentialStore:
    """Persist the API key in the current Windows user's Credential Manager."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise CredentialStoreError("Защищённое хранилище ключей доступно только в Windows.")
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CredentialW)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    def save_api_key(self, api_key: str) -> None:
        secret = _validate_api_key(api_key)
        buffer = ctypes.create_string_buffer(secret)
        credential = _CredentialW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = _TARGET_NAME
        credential.CredentialBlobSize = len(secret)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "OpenAI API key"
        if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialStoreError("Windows не сохранила ключ API в защищённом хранилище.")

    def read_api_key(self) -> str | None:
        credential_pointer = ctypes.POINTER(_CredentialW)()
        if not self._advapi32.CredReadW(_TARGET_NAME, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential_pointer)):
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError("Не удалось прочитать ключ API из защищённого хранилища.")
        try:
            credential = credential_pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            try:
                return raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise CredentialStoreError("Сохранённый ключ API имеет неверный формат.") from error
        finally:
            self._advapi32.CredFree(credential_pointer)

    def delete_api_key(self) -> None:
        if not self._advapi32.CredDeleteW(_TARGET_NAME, _CRED_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != _ERROR_NOT_FOUND:
                raise CredentialStoreError("Не удалось удалить ключ API из защищённого хранилища.")


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _validate_api_key(value: str) -> bytes:
    if not isinstance(value, str):
        raise CredentialStoreError("Ключ API должен быть текстом.")
    secret = value.strip().encode("utf-8", errors="strict")
    if not 20 <= len(secret) <= _MAX_SECRET_BYTES or any(byte < 32 or byte == 127 for byte in secret):
        raise CredentialStoreError("Ключ API имеет недопустимую длину или содержит управляющие символы.")
    return secret
