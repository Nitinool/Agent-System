"""Windows APIs. DLLs are loaded only when an adapter is constructed."""

import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
from .models import Activity


class SessionPrefix(ctypes.Structure):
    _fields_ = [("session_id", wintypes.DWORD), ("state", ctypes.c_int), ("flags", wintypes.LONG)]



class SessionData(ctypes.Union):
    # The full WTSINFOEX_LEVEL1 contains LARGE_INTEGER fields, giving this union 8-byte alignment.
    _fields_ = [("prefix", SessionPrefix), ("alignment", ctypes.c_longlong)]



class SessionInfo(ctypes.Structure):
    _fields_ = [("level", wintypes.DWORD), ("data", SessionData)]



class WindowsReader:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        self.wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self.wts.WTSQuerySessionInformationW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
        ]
        self.wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
        self.wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        self.wts.WTSFreeMemory.restype = None

    def is_locked(self):
        buffer = ctypes.c_void_p()
        size = wintypes.DWORD()
        if not self.wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25,
                                                   ctypes.byref(buffer), ctypes.byref(size)):
            return None
        try:
            if not buffer.value or size.value < ctypes.sizeof(SessionInfo):
                return None
            info = ctypes.cast(buffer, ctypes.POINTER(SessionInfo)).contents
            if info.level != 1 or info.data.prefix.flags not in (0, 1):
                return None
            return info.data.prefix.flags == 0 or info.data.prefix.state != 0
        finally:
            self.wts.WTSFreeMemory(buffer)

    def read_window(self, hwnd):
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        if not self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        title = ctypes.create_unicode_buffer(32768)
        self.user32.GetWindowTextW(hwnd, title, len(title))
        process = f"未知程序 (PID {pid.value})"
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                image = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(image))
                if self.kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                    process = Path(image.value).name
            finally:
                self.kernel32.CloseHandle(handle)
        return Activity(process, title.value, pid.value)

    def read(self):
        hwnd = self.user32.GetForegroundWindow()
        activity = self.read_window(hwnd)
        # Discard a sample if focus switched while querying it.
        return activity if hwnd == self.user32.GetForegroundWindow() else None



class SingleInstance:
    def __init__(self, db_path):
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        key = hashlib.sha256(str(db_path.resolve()).lower().encode()).hexdigest()[:24]
        ctypes.set_last_error(0)
        self.handle = self.kernel32.CreateMutexW(None, False, "Local\\ActivityLogger-" + key)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_running = ctypes.get_last_error() == 183

    def close(self):
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
