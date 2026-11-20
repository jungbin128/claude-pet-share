"""Windows notification-area host. Pet workers exist only while visible."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import socket
import os
import subprocess
import sys
import time

from autorun import is_suspended, prepare_launch, set_enabled, get_mode, set_mode, summary, autorun_menu_items

BASE = Path(__file__).resolve().parent
TITLE = "ClaudePet.TrayHost.1"
COMMAND = 0x8002
SHOW, AUTO, HIDE = 1, 2, 3
UNINSTALL, TOGGLE_AUTORUN, LOGIN, SET_LOGIN, SET_CLAUDE, CLAUDE_SESSION, READY, OPEN_UPDATES = 6, 7, 8, 9, 10, 11, 12, 13


def api():
    u=c.WinDLL('user32', use_last_error=True)
    u.FindWindowW.argtypes=[w.LPCWSTR,w.LPCWSTR];u.FindWindowW.restype=w.HWND
    u.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.PostMessageW.restype=w.BOOL
    return u


def notify(command):
    u=api();hwnd=u.FindWindowW(TITLE,TITLE)
    return bool(hwnd and u.PostMessageW(hwnd,COMMAND,command,0))


def stop_pet():
    try:
        with socket.create_connection(('127.0.0.1',48765),timeout=.15) as conn:
            conn.sendall(b'quit')
    except OSError:
        pass


class Controller:
    def __init__(self, base=BASE, spawn=None, stop=stop_pet):
        self.base=Path(base);self.spawn=spawn or self._spawn;self.stop=stop
        self.child=None;self.hidden=False;self.stopping=False;self.pending=False
        self.exiting=False;self.deadline=0;self.claude_running=None;self.child_ready=False

    def _spawn(self):
        py=Path(sys.executable).with_name('pythonw.exe')
        return subprocess.Popen([str(py if py.exists() else Path(sys.executable)),
            '-X','utf8','-I',str(self.base/'pet.pyw'),'--tray-child'],
            cwd=self.base,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=0x08000000)

    def alive(self):
        return self.child is not None and self.child.poll() is None

    def show(self, automatic=False, source="claude"):
        if self.exiting or (automatic and (self.hidden or is_suspended(self.base))):return
        if not prepare_launch(self.base,automatic,source):return
        self.hidden=False
        if self.alive():
            self.pending=self.stopping
        else:
            self.child=self.spawn();self.stopping=False;self.pending=False;self.child_ready=False

    def hide(self):
        self.hidden=True;self.pending=False
        if not self.stopping:
            self.stopping=True;self.deadline=time.monotonic()+5
        if self.alive():self.stop()

    def shutdown(self):
        self.exiting=True
        self.hide()

    def toggle_autorun(self):
        set_enabled(self.base, is_suspended(self.base))

    def claude_session_started(self):
        if prepare_launch(self.base,True,"claude"):
            self.hidden=False
            self.show(automatic=True,source="claude")

    def observe_claude(self,running):
        previous=self.claude_running;self.claude_running=running
        if running and previous is not True and prepare_launch(self.base,True,"claude"):
            if previous is False:self.hidden=False
            self.show(automatic=True,source="claude")

    def tick(self):
        if self.stopping and self.alive():self.stop()
        if self.stopping and self.alive() and time.monotonic()>self.deadline:
            self.child.terminate()
        if self.stopping and not self.alive():
            self.stopping=False
            if self.pending and not self.exiting:self.show()
        return self.exiting and not self.alive()

    def status(self):
        if is_suspended(self.base):return '자동 실행 중지'
        return '실행 중' if self.alive() and not self.hidden else '펫 숨김'


def tray_menu_items(ctl, action, open_autorun=None,open_updates=None,update_value=""):
    return [
        ('표시',None,False,True,{'section':True}),
        ("펫 켜기",lambda:action(SHOW),False,False,{"icon":"pet"}),
        ("펫 숨기기",lambda:action(HIDE),True,False,{"icon":"power"}),
        ('실행 설정',None,False,True,{'section':True}),
        ('자동 실행',open_autorun,False,True,{'icon':'clock','arrow':True,'value':summary(ctl.base)}),
        ('업데이트',open_updates,False,True,{'icon':'clock','arrow':True,'value':update_value}),
        None,("Claude 펫 삭제",lambda:action(UNINSTALL),True,False,{"icon":"trash"}),
    ]


def run(automatic=False,source="claude",fresh=False,tray_only=False):
    if (BASE/".uninstalling").exists() or (BASE/".update-in-progress").exists():return
    u=api()
    mutex_api=c.WinDLL('kernel32',use_last_error=True)
    mutex_api.CreateMutexW.argtypes=[c.c_void_p,w.BOOL,w.LPCWSTR];mutex_api.CreateMutexW.restype=w.HANDLE
    mutex_api.CloseHandle.argtypes=[w.HANDLE]
    mutex=mutex_api.CreateMutexW(None,False,'Local\\ClaudePet.TrayHost.1')
    if not mutex:raise c.WinError(c.get_last_error())
    existing=c.get_last_error()==183
    if existing:
        try:
            for _ in range(30):
                if notify((LOGIN if source=="login" else (CLAUDE_SESSION if fresh else AUTO)) if automatic else SHOW):return
                time.sleep(.05)
            raise RuntimeError('Tray host is starting; retry shortly')
        finally:mutex_api.CloseHandle(mutex)
    mutex_api.GetModuleHandleW.argtypes=[w.LPCWSTR];mutex_api.GetModuleHandleW.restype=w.HINSTANCE
    instance=mutex_api.GetModuleHandleW(None)
    ctl=Controller()
    from app_launch import ClaudePresence
    presence=ClaudePresence();next_presence=0
    from updater import UpdateService,launch_worker,update_menu_items
    updates=UpdateService(BASE)
    if tray_only:ctl.hidden=True
    LRESULT=c.c_ssize_t
    PROC=c.WINFUNCTYPE(LRESULT,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
    class WC(c.Structure):
        _fields_=[('style',w.UINT),('proc',PROC),('cls',c.c_int),('wnd',c.c_int),
            ('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),
            ('background',w.HBRUSH),('menu',w.LPCWSTR),('name',w.LPCWSTR)]
    class GUID(c.Structure):
        _fields_=[('a',w.DWORD),('b',w.WORD),('d',w.WORD),('e',c.c_byte*8)]
    class NID(c.Structure):
        _fields_=[('size',w.DWORD),('hwnd',w.HWND),('id',w.UINT),('flags',w.UINT),
            ('callback',w.UINT),('icon',w.HICON),('tip',w.WCHAR*128),
            ('state',w.DWORD),('mask',w.DWORD),('info',w.WCHAR*256),
            ('version',w.UINT),('title',w.WCHAR*64),('infoflags',w.DWORD),
            ('guid',GUID),('balloonicon',w.HICON)]
    u.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.DefWindowProcW.restype=LRESULT
    u.RegisterClassW.argtypes=[c.POINTER(WC)];u.RegisterClassW.restype=w.WORD
    u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p];u.CreateWindowExW.restype=w.HWND
    u.LoadImageW.argtypes=[w.HINSTANCE,w.LPCWSTR,w.UINT,c.c_int,c.c_int,w.UINT];u.LoadImageW.restype=w.HANDLE
    u.DestroyIcon.argtypes=[w.HICON];u.DestroyWindow.argtypes=[w.HWND]
    u.IsWindow.argtypes=[w.HWND];u.IsWindow.restype=w.BOOL
    u.SetPropW.argtypes=[w.HWND,w.LPCWSTR,w.HANDLE]
    u.GetCursorPos.argtypes=[c.POINTER(w.POINT)]
    u.SetTimer.argtypes=[w.HWND,c.c_size_t,w.UINT,c.c_void_p];u.SetTimer.restype=c.c_size_t
    u.KillTimer.argtypes=[w.HWND,c.c_size_t]
    u.GetMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT];u.GetMessageW.restype=c.c_int
    u.TranslateMessage.argtypes=[c.POINTER(w.MSG)];u.DispatchMessageW.argtypes=[c.POINTER(w.MSG)];u.DispatchMessageW.restype=LRESULT
    u.RegisterWindowMessageW.argtypes=[w.LPCWSTR];u.RegisterWindowMessageW.restype=w.UINT
    shell=c.WinDLL('shell32',use_last_error=True)
    shell.Shell_NotifyIconW.argtypes=[w.DWORD,c.POINTER(NID)];shell.Shell_NotifyIconW.restype=w.BOOL
    restart=u.RegisterWindowMessageW('TaskbarCreated');callback=0x8001
    icon=u.LoadImageW(None,str(BASE/'assets'/'claude-pet.ico'),1,32,32,0x10)
    if not icon:
        mutex_api.CloseHandle(mutex)
        raise c.WinError(c.get_last_error())
    nid=NID();nid.size=c.sizeof(NID);nid.id=1;nid.flags=7;nid.callback=callback;nid.icon=icon
    added=False;last_tip=None;hwnd=None
    menu_ui=None
    updating_ui=False
    ui_token=None

    def action(command):
        if command in (SHOW,AUTO,LOGIN):ctl.show(command!=SHOW,source="login" if command==LOGIN else "claude")
        elif command in (SET_LOGIN,SET_CLAUDE):set_mode(BASE,"login" if command==SET_LOGIN else "claude")
        elif command==CLAUDE_SESSION:ctl.claude_session_started()
        elif command==READY:ctl.child_ready=True
        elif command==OPEN_UPDATES:menu(hwnd,True)
        elif command==HIDE:ctl.hide()
        elif command==TOGGLE_AUTORUN:ctl.toggle_autorun()
        elif command==UNINSTALL:
            text=("Claude 펫을 이 PC에서 삭제할까요?\n\n프로그램·스킨·개인 설정·상태·로그 및 펫 전용 훅과 시작 항목이 삭제됩니다.\n"
                "다른 Claude 설정과 원본 대화 기록은 유지합니다.\n\n삭제 폴더: "+str(BASE))
            u.MessageBoxW.argtypes=[w.HWND,w.LPCWSTR,w.LPCWSTR,w.UINT]
            if u.MessageBoxW(hwnd,text,"Claude 펫 삭제",0x134)!=6:return
            try:
                from uninstall import launch_uninstall
                launch_uninstall(BASE,os.getpid())
                ctl.shutdown()
            except Exception as error:
                u.MessageBoxW(hwnd,"삭제를 시작하지 못했습니다.\n"+str(error),"Claude 펫 삭제",0x10)

    def update(force=False):
        nonlocal added,last_tip
        tip='Claude Pet · '+ctl.status()
        if force:added=False
        if not added or tip!=last_tip:
            nid.tip=tip
            added=bool(shell.Shell_NotifyIconW(1 if added else 0,c.byref(nid)))
            if added:last_tip=tip

    def menu(hwnd,show_updates=False):
        nonlocal menu_ui
        if menu_ui is None:
            import runpy
            import tkinter as tk
            namespace=runpy.run_path(str(BASE/'pet.pyw'),run_name='tray_menu')
            root=tk.Tk();root.withdraw()
            menu_ui=(root,namespace['Menu'](root))
        root,popup=menu_ui
        def open_autorun():
            popup.navigate(lambda:autorun_menu_items(BASE,
                lambda:popup.navigate(items,"Claude Pet","트레이 및 실행 설정"),
                lambda:action(TOGGLE_AUTORUN),
                lambda mode:action(SET_LOGIN if mode=="login" else SET_CLAUDE)),
                "자동 실행","펫을 자동으로 켜는 시점")
        def open_updates():
            popup.navigate(lambda:update_menu_items(updates,
                lambda:popup.navigate(items,"Claude Pet","트레이 및 실행 설정")),
                "업데이트",updates.status)
        def items():return tray_menu_items(ctl,action,open_autorun,open_updates,
            updates.offer['version'] if updates.offer else "")
        point=w.POINT();u.GetCursorPos(c.byref(point));u.SetForegroundWindow(hwnd)
        popup.popup(point.x,point.y,items,"Claude Pet","트레이 및 실행 설정")
        if show_updates:open_updates()
        u.SetTimer(hwnd,1,50,None)

    @PROC
    def proc(window,msg,wp,lp):
        nonlocal updating_ui,next_presence,ui_token
        try:
            if msg==COMMAND:action(wp);update();return 0
            if msg==callback:
                if lp==0x203:action(SHOW)
                elif lp in (0x205,0x7b):menu(window)
                update();return 0
            if msg==restart:update(True);return 0
            if msg==0x113:
                updates.tick()
                if updates.prepared and not updates.install_requested and not ctl.exiting and not ctl.alive():
                    updates.prepared=False
                    if not ctl.hidden:ctl.show()
                ready=added and ((ctl.alive() and ctl.child_ready) or (ctl.hidden and not ctl.alive()))
                u.SetPropW(window,"ClaudePet.Ready",1 if ready else 0)
                menu_open=menu_ui is not None and menu_ui[1].open_
                if (not ctl.exiting and updates.install_requested and updates.package and not menu_open
                        and updates.can_apply(ctl.alive())):
                    updates.install_requested=False
                    try:
                        launch_worker(BASE,updates.package,updates.offer,os.getpid(),tray_only=ctl.hidden)
                        ctl.shutdown()
                    except Exception:
                        updates.status='업데이트 시작 실패'
                        updates.prepared=False
                        if not ctl.hidden:ctl.show()
                if time.monotonic()>=next_presence and not ctl.exiting:
                    next_presence=time.monotonic()+1
                    ctl.observe_claude(presence.running())
                if menu_ui is not None and not updating_ui:
                    updating_ui=True
                    try:
                        popup=menu_ui[1]
                        token=(updates.status,updates.auto,updates.busy,is_suspended(BASE),get_mode(BASE))
                        if popup.open_ and token!=ui_token:
                            popup.items=popup.builder()
                            if popup.heading=="업데이트":popup.caption=updates.status
                            popup.render();ui_token=token
                        menu_ui[0].update()
                    finally:updating_ui=False
                    u.SetTimer(window,1,50 if menu_ui[1].open_ else 250,None)
                if ctl.tick():u.DestroyWindow(window)
                else:update()
                return 0
            if msg==0x10:ctl.shutdown();return 0
            if msg==0x2:u.PostQuitMessage(0);return 0
        except Exception:
            import traceback
            with (BASE/'pet_error.log').open('a',encoding='utf8') as log:traceback.print_exc(file=log)
        return u.DefWindowProcW(window,msg,wp,lp)

    try:
        wc=WC();wc.proc=proc;wc.name=TITLE;wc.instance=instance
        if not u.RegisterClassW(c.byref(wc)):raise c.WinError(c.get_last_error())
        hwnd=u.CreateWindowExW(0,TITLE,TITLE,0,0,0,0,0,None,None,instance,None)
        if not hwnd:raise c.WinError(c.get_last_error())
        nid.hwnd=hwnd
        update()
        if not tray_only:ctl.show(automatic,source)
        if not u.SetTimer(hwnd,1,250,None):raise c.WinError(c.get_last_error())
        message=w.MSG()
        while True:
            result=u.GetMessageW(c.byref(message),None,0,0)
            if result==0:break
            if result==-1:raise c.WinError(c.get_last_error())
            u.TranslateMessage(c.byref(message));u.DispatchMessageW(c.byref(message))
    finally:
        if menu_ui is not None:
            menu_ui[0].destroy()
        if hwnd:
            u.KillTimer(hwnd,1)
            shell.Shell_NotifyIconW(2,c.byref(nid))
            if u.IsWindow(hwnd):u.DestroyWindow(hwnd)
        if ctl.alive():
            ctl.stop()
            try:ctl.child.wait(timeout=3)
            except subprocess.TimeoutExpired:ctl.child.terminate()
        u.DestroyIcon(icon);mutex_api.CloseHandle(mutex)
