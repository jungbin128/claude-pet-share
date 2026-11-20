"""Remove only this dedicated Claude Pet installation and its integrations."""
import argparse
import copy
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time


def validate_root(root, home=None):
    root=Path(root).absolute()
    expected=Path(home or Path.home())/'.claude'/'claude-pet'
    if root!=expected or root.is_symlink() or root.is_junction() or root.parent.is_symlink() or root.parent.is_junction():
        raise ValueError('Only the dedicated ~/.claude/claude-pet folder may be removed')
    if root.resolve()!=expected.absolute():raise ValueError('Installation path redirects outside expected location')
    for filename in ('pet.pyw','pet_hook.py','tray_host.py'):
        if not (root/filename).is_file():raise ValueError('Not a recognized Claude Pet installation')
    return root


def clean_settings(data,root):
    result=copy.deepcopy(data)
    if not isinstance(result,dict):raise ValueError('Claude settings must be an object')
    hooks=result.get('hooks')
    if hooks is None:return result
    if not isinstance(hooks,dict):raise ValueError('Invalid hooks configuration')
    target=str(Path(root)/'pet_hook.py').replace('\\','/').lower()
    pattern=re.compile(r"(?:^|[\s\"'])"+re.escape(target)+r"(?=$|[\s\"'])")
    for event,groups in list(hooks.items()):
        if not isinstance(groups,list):continue
        kept=[]
        for group in groups:
            if not isinstance(group,dict) or not isinstance(group.get('hooks'),list):
                kept.append(group);continue
            remaining=[]
            for hook in group['hooks']:
                command=hook.get('command','') if isinstance(hook,dict) else ''
                owned=isinstance(hook,dict) and hook.get('type')=='command' and isinstance(command,str) and pattern.search(command.replace('\\','/').lower())
                if not owned:remaining.append(hook)
            if remaining or not group['hooks']:
                group['hooks']=remaining;kept.append(group)
        if kept:hooks[event]=kept
        else:hooks.pop(event,None)
    if not hooks:result.pop('hooks',None)
    return result


def remove_hooks(root):
    settings=Path(root).parent/'settings.json'
    if not settings.exists():return
    raw=settings.read_bytes()
    current=json.loads(raw.decode('utf-8-sig'));updated=clean_settings(current,root)
    if current==updated:return
    # Refuse to overwrite concurrent settings edits; failure leaves installation intact.
    replacement=settings.with_name('settings.claude-pet-uninstall.tmp')
    try:
        replacement.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        if settings.read_bytes()!=raw:raise RuntimeError('Claude settings changed during removal; retry')
        os.replace(replacement,settings)
    finally:replacement.unlink(missing_ok=True)


def startup_shortcut(root):
    appdata=os.environ.get('APPDATA')
    if not appdata:return None
    return Path(appdata)/'Microsoft/Windows/Start Menu/Programs/Startup/Claude Pet.lnk'


def remove_startup(root):
    shortcut=startup_shortcut(root)
    if shortcut is None or not shortcut.exists():return
    # Only delete our shortcut when its arguments identify this exact installation.
    command="[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CLAUDE_PET_SHORTCUT); [Console]::Write($s.Arguments)"
    env=os.environ.copy();env['CLAUDE_PET_SHORTCUT']=str(shortcut)
    args=subprocess.run(['powershell.exe','-NoProfile','-Command',command],env=env,
        capture_output=True,text=True,encoding='utf8',errors='replace',creationflags=0x08000000,timeout=15,check=True).stdout
    target=str(Path(root)/'pet.pyw').replace('\\','/').lower()
    if re.search(r"(?:^|[\s\"'])"+re.escape(target)+r"(?=$|[\s\"'])",args.replace('\\','/').lower()):shortcut.unlink()
    else:raise RuntimeError('Startup shortcut belongs to another installation; unchanged')


def remove_installation(root, home=None, cleanup_startup=remove_startup):
    root=validate_root(root,home)
    remove_hooks(root)
    cleanup_startup(root)
    time.sleep(.3)  # Let hooks already in flight finish after detaching integrations.
    # Python on Windows removes directory junctions themselves, never their contents.
    def writable_retry(function,path,error):
        checked=Path(path)
        if not isinstance(error,PermissionError) or not checked.resolve().is_relative_to(root.resolve()):raise error
        checked.chmod(stat.S_IWRITE|stat.S_IREAD)
        function(path)
    for attempt in range(30):
        try:
            shutil.rmtree(root,onexc=writable_retry)
            return
        except OSError:
            if not root.exists():return
            if attempt==29:raise
            time.sleep(.2)


def launch_uninstall(root,wait_pid):
    root=validate_root(root)
    work=Path(tempfile.mkdtemp(prefix='claude-pet-remove-'))
    script=work/'uninstall.py';shutil.copyfile(Path(__file__),script)
    marker=root/'.uninstalling'
    try:
        marker.write_text('Removal in progress',encoding='utf8')
        helper=Path(getattr(sys,'_base_executable',sys.executable)).with_name('pythonw.exe')
        if not helper.exists():helper=Path(getattr(sys,'_base_executable',sys.executable))
        subprocess.Popen([str(helper),'-X','utf8','-I',str(script),'--remove',str(root),'--wait',str(wait_pid)],
            cwd=work,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=0x08000000)
    except Exception:
        marker.unlink(missing_ok=True)
        shutil.rmtree(work)
        raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--remove',required=True);parser.add_argument('--wait',required=True,type=int)
    args=parser.parse_args();validate_root(args.remove)
    k=c.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.CloseHandle.argtypes=[w.HANDLE]
    process=k.OpenProcess(0x100000,False,args.wait)
    try:
        if not process and c.get_last_error()!=87:raise c.WinError(c.get_last_error())
        if process and k.WaitForSingleObject(process,20000)!=0:raise RuntimeError('Pet manager did not stop; no files removed')
        remove_installation(args.remove)
    except Exception as error:
        u=c.WinDLL('user32');u.MessageBoxW.argtypes=[w.HWND,w.LPCWSTR,w.LPCWSTR,w.UINT]
        (Path(args.remove)/'.uninstalling').unlink(missing_ok=True)
        u.MessageBoxW(None,'삭제를 완료하지 못했습니다.\n'+str(error),'Claude 펫 삭제',0x10)
    finally:
        if process:k.CloseHandle(process)
        script=Path(__file__).resolve()
        if script.parent.name.startswith('claude-pet-remove-') and script.parent.parent==Path(tempfile.gettempdir()).resolve():
            script.unlink(missing_ok=True)
            try:script.parent.rmdir()
            except OSError:pass


if __name__=='__main__':main()
