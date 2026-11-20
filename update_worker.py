"""Out-of-process apply, health check and rollback. Standard library only."""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parent))
from distribution import read_archive,apply_package,restore_backup
from integration import install_root,start_pet


def wait_process(pid):
    k=c.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.CloseHandle.argtypes=[w.HANDLE]
    process=k.OpenProcess(0x100000,False,pid)
    if not process:
        if c.get_last_error()!=87:raise c.WinError(c.get_last_error())
        return
    try:
        if k.WaitForSingleObject(process,20000)!=0:raise RuntimeError('Pet manager did not stop')
    finally:k.CloseHandle(process)


def host_api():
    u=c.WinDLL('user32');u.FindWindowW.argtypes=[w.LPCWSTR,w.LPCWSTR];u.FindWindowW.restype=w.HWND
    u.GetPropW.argtypes=[w.HWND,w.LPCWSTR];u.GetPropW.restype=w.HANDLE
    u.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    return u


def healthy(process,timeout=20):
    u=host_api();end=time.monotonic()+timeout;since=None
    while time.monotonic()<end:
        if process.poll() is not None:return False
        hwnd=u.FindWindowW('ClaudePet.TrayHost.1','ClaudePet.TrayHost.1')
        if hwnd and u.GetPropW(hwnd,'ClaudePet.Ready'):
            since=since or time.monotonic()
            if time.monotonic()-since>=2:return True
        else:since=None
        time.sleep(.2)
    return False


def stop_new_host(process):
    u=host_api();hwnd=u.FindWindowW('ClaudePet.TrayHost.1','ClaudePet.TrayHost.1')
    if hwnd:u.PostMessageW(hwnd,0x10,0,0)
    try:process.wait(timeout=8)
    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)


def apply_and_restart(plan,root=None,launch=start_pet,health=healthy,stop=stop_new_host):
    root=Path(root or plan['root']);backup=root/'updates'/('rollback-'+uuid.uuid4().hex)
    process=None
    try:
        read_archive(plan['package'],plan['digest'])
        apply_package(root,plan['package'],backup,plan['digest'])
        # This release keeps the same Pillow contract; never alter a system Python.
        subprocess.run([plan['python'],'-X','utf8','-I','-c','from PIL import Image; import tkinter'],check=True,timeout=20,capture_output=True)
        (root/'.update-in-progress').unlink(missing_ok=True)
        process=launch(root,plan['python'],plan.get('tray_only',False))
        if not health(process):raise RuntimeError('New version failed its startup health check')
    except Exception:
        if process is not None:stop(process)
        (root/'.update-in-progress').write_text('Restoring previous version',encoding='utf8')
        if (backup/'backup-index.json').exists():restore_backup(root,backup)
        (root/'.update-in-progress').unlink(missing_ok=True)
        launch(root,plan['python'],plan.get('tray_only',False))
        raise
    # Keep only this one program-only rollback, never copies of private state.
    for path in (root/'updates').glob('rollback-*'):
        if path!=backup and path.is_dir() and not path.is_symlink() and not path.is_junction():shutil.rmtree(path)


def main():
    folder=Path(__file__).resolve().parent
    plan=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
    root=install_root(plan['root'])
    try:
        wait_process(plan['wait_pid'])
        apply_and_restart(plan,root)
    except Exception as error:
        (root/'.update-in-progress').unlink(missing_ok=True)
        u=c.WinDLL('user32');u.MessageBoxW.argtypes=[w.HWND,w.LPCWSTR,w.LPCWSTR,w.UINT]
        u.MessageBoxW(None,'업데이트를 완료하지 못했습니다. 기존 버전을 유지하거나 복구했습니다.\n'+str(error),'Claude Pet 업데이트',0x30)
    finally:
        if folder.name.startswith('claude-pet-update-') and folder.parent==Path(__import__('tempfile').gettempdir()).resolve():shutil.rmtree(folder)


if __name__=='__main__':main()
