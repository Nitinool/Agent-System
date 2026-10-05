"""Local-only token storage encrypted for the current Windows user with DPAPI."""

import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile

from .sync import SyncError


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    if os.name != "nt":
        raise SyncError("记住 Token 需要 Windows；可不勾选记住并仅在本次运行使用。")
    crypt32, kernel32 = ctypes.WinDLL("crypt32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise SyncError("无法读取或保存加密 Token，请在这台电脑重新填写。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


class TokenStore:
    def __init__(self, directory):
        self.path = Path(directory) / "sync-token.dpapi" if directory else None

    def load(self):
        if self.path is None or not self.path.exists():
            return ""
        try:
            return _crypt(base64.b64decode(self.path.read_bytes(), validate=True), decrypt=True).decode("utf-8")
        except (OSError, ValueError, UnicodeError):
            raise SyncError("本机 Token 文件无法读取，请重新填写。") from None

    def save(self, token):
        if self.path is None:
            raise SyncError("当前临时数据库不保存 Token。")
        encrypted = base64.b64encode(_crypt(token.encode("utf-8")))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(encrypted)
            os.replace(temporary, self.path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def clear(self):
        if self.path:
            self.path.unlink(missing_ok=True)
