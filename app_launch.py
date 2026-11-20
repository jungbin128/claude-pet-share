"""Detect Claude desktop opening without reading titles or conversation data."""
import ctypes as c
from ctypes import wintypes as w


class ClaudePresence:
    def __init__(self):
        self.k=c.WinDLL('kernel32',use_last_error=True);self.u=c.WinDLL('user32',use_last_error=True)
        class Entry(c.Structure):
            _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',c.c_size_t),
                ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),
                ('flags',w.DWORD),('name',w.WCHAR*260)]
        self.Entry=Entry
        self.k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];self.k.CreateToolhelp32Snapshot.restype=w.HANDLE
        self.k.Process32FirstW.argtypes=[w.HANDLE,c.POINTER(Entry)];self.k.Process32FirstW.restype=w.BOOL
        self.k.Process32NextW.argtypes=[w.HANDLE,c.POINTER(Entry)];self.k.Process32NextW.restype=w.BOOL
        self.k.CloseHandle.argtypes=[w.HANDLE]
        self.CALLBACK=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        self.u.EnumWindows.argtypes=[self.CALLBACK,w.LPARAM]
        self.u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
        self.u.IsWindowVisible.argtypes=[w.HWND];self.u.IsWindowVisible.restype=w.BOOL
        self.u.GetWindowLongW.argtypes=[w.HWND,c.c_int]

    def running(self):
        snapshot=self.k.CreateToolhelp32Snapshot(2,0)
        if snapshot==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
        pids=set()
        try:
            entry=self.Entry();entry.size=c.sizeof(entry)
            found=self.k.Process32FirstW(snapshot,c.byref(entry))
            while found:
                if entry.name.lower()=='claude.exe':pids.add(entry.pid)
                found=self.k.Process32NextW(snapshot,c.byref(entry))
        finally:self.k.CloseHandle(snapshot)
        if not pids:return False
        visible=False
        @self.CALLBACK
        def each(hwnd,_):
            nonlocal visible
            if not self.u.IsWindowVisible(hwnd) or self.u.GetWindowLongW(hwnd,-20)&0x80:return True
            pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,c.byref(pid))
            if pid.value in pids:visible=True;return False
            return True
        self.u.EnumWindows(each,0)
        return visible
