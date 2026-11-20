"""Keep this app below visible Windows taskbars and shell flyouts."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import PureWindowsPath
import time

TASKBARS={'Shell_TrayWnd','Shell_SecondaryTrayWnd'}
FLYOUTS={'NotifyIconOverflowWindow','TopLevelWindowForOverflowXamlIsland',
    'ControlCenterWindow','XamlExplorerHostIslandWindow'}
SHELL_APPS={'shellexperiencehost.exe','shellhost.exe','startmenuexperiencehost.exe'}
FLAGS=0x0001|0x0002|0x0010|0x0200


def is_shell_window(class_name, executable):
    name=executable.lower()
    return (class_name in TASKBARS or class_name in FLYOUTS or
        name in SHELL_APPS or (class_name=='#32768' and name=='explorer.exe'))


def choose_anchor(windows):
    """Input is top-to-bottom; each tuple is (HWND, own, shell, topmost)."""
    popups=[i for i,row in enumerate(windows) if row[2] and not row[1]]
    return windows[popups[-1]][0] if popups else None


class ShellPriority:
    def __init__(self):
        self.u=c.WinDLL('user32',use_last_error=True)
        self.k=c.WinDLL('kernel32',use_last_error=True)
        self.dwm=c.WinDLL('dwmapi')
        self.CALLBACK=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        self.u.EnumWindows.argtypes=[self.CALLBACK,w.LPARAM]
        self.u.IsWindowVisible.argtypes=[w.HWND];self.u.IsWindowVisible.restype=w.BOOL
        self.u.IsWindow.argtypes=[w.HWND];self.u.IsWindow.restype=w.BOOL
        self.u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,c.c_int]
        self.u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
        self.u.GetWindowLongW.argtypes=[w.HWND,c.c_int];self.u.GetWindowLongW.restype=c.c_long
        self.u.GetWindowRect.argtypes=[w.HWND,c.POINTER(w.RECT)]
        self.u.GetSystemMetrics.argtypes=[c.c_int];self.u.GetSystemMetrics.restype=c.c_int
        self.u.SetWindowPos.argtypes=[w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
        self.k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.k.OpenProcess.restype=w.HANDLE
        self.k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
        self.k.CloseHandle.argtypes=[w.HANDLE]
        self.dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
        self.names={};self.anchor=None;self._next=0

    def executable(self,pid):
        now=time.monotonic()
        cached=self.names.get(pid)
        if cached and now<cached[0]:return cached[1]
        handle=self.k.OpenProcess(0x1000,False,pid);name=''
        if handle:
            try:
                text=c.create_unicode_buffer(1024);size=w.DWORD(len(text))
                if self.k.QueryFullProcessImageNameW(handle,0,text,c.byref(size)):
                    name=PureWindowsPath(text.value).name.lower()
            finally:self.k.CloseHandle(handle)
        if len(self.names)>256:self.names.clear()
        self.names[pid]=(now+30,name)
        return name

    def scan(self):
        rows=[]
        left=self.u.GetSystemMetrics(76);top=self.u.GetSystemMetrics(77)
        right=left+self.u.GetSystemMetrics(78);bottom=top+self.u.GetSystemMetrics(79)
        @self.CALLBACK
        def each(hwnd,_):
            if not self.u.IsWindowVisible(hwnd):return True
            rect=w.RECT();self.u.GetWindowRect(hwnd,c.byref(rect))
            if rect.right<=max(rect.left,left) or rect.bottom<=max(rect.top,top) or rect.left>=right or rect.top>=bottom:return True
            cloaked=w.DWORD()
            if self.dwm.DwmGetWindowAttribute(hwnd,14,c.byref(cloaked),c.sizeof(cloaked))==0 and cloaked.value:return True
            pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,c.byref(pid))
            own=pid.value==os.getpid()
            text=c.create_unicode_buffer(256);self.u.GetClassNameW(hwnd,text,len(text))
            shell=False
            if not own:
                # Name lookup is cached; no UI Automation or screenshots are needed.
                shell=is_shell_window(text.value,self.executable(pid.value))
            rows.append((hwnd,own,shell,bool(self.u.GetWindowLongW(hwnd,-20)&8)))
            return True
        self.u.EnumWindows(each,0)
        return rows

    def raise_window(self,hwnd):
        anchor=self.anchor if self.anchor and self.u.IsWindow(self.anchor) else -1
        self.u.SetWindowPos(hwnd,anchor,0,0,0,0,FLAGS)

    def enforce(self):
        now=time.monotonic()
        if now<self._next:return
        self._next=now+.15
        rows=self.scan();anchor=choose_anchor(rows)
        own=[row[0] for row in rows if row[1]]
        previous=self.anchor;self.anchor=anchor
        if anchor:
            index=next(i for i,row in enumerate(rows) if row[0]==anchor)
            if any(row[1] for row in rows[:index]) or previous!=anchor:
                # Reverse insertion keeps the pet menu and focused editor in front of its bubbles.
                for hwnd in reversed(own):self.raise_window(hwnd)
        elif previous:
            for hwnd in reversed(own):self.raise_window(hwnd)
