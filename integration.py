"""Per-user runtime and reversible Claude/Windows integration."""
import json
import os
from pathlib import Path
import subprocess
import sys
import venv
from distribution import atomic_json
from uninstall import clean_settings

EVENTS=('SessionStart','UserPromptSubmit','PreToolUse','Notification','Stop','SessionEnd')


def install_root(root,home=None):
    root=Path(root).absolute();expected=Path(home or Path.home())/'.claude'/'claude-pet'
    if root!=expected or root.resolve()!=expected.absolute():raise ValueError('Install only into ~/.claude/claude-pet')
    for path in (root,root.parent):
        if path.is_symlink() or path.is_junction():raise ValueError('Redirected installation directory')
    if (root/'.git').exists():raise ValueError('This is a development checkout; do not overwrite it with the sharing installer')
    return root


def hook_settings(data,root,python):
    data=clean_settings(data,root)
    hooks=data.setdefault('hooks',{})
    command=subprocess.list2cmdline([str(python),'-X','utf8','-I',str(Path(root)/'pet_hook.py')])
    for event in EVENTS:
        groups=hooks.setdefault(event,[])
        if not isinstance(groups,list):raise ValueError('Invalid hook groups')
        entry={'hooks':[{'type':'command','command':command,'timeout':10}]}
        if event=='PreToolUse':entry['matcher']='*'
        groups.append(entry)
    return data


def register_hooks(root,python):
    root=Path(root);path=root.parent/'settings.json'
    original=path.read_bytes() if path.exists() else None
    current=json.loads(original.decode('utf-8-sig')) if original is not None else {}
    updated=hook_settings(current,root,python)
    backup=root/'settings-before-install.json'
    if original is not None and not backup.exists():backup.write_bytes(original)
    if (path.read_bytes() if path.exists() else None)!=original:raise RuntimeError('Claude settings changed; retry setup')
    atomic_json(path,updated)
    return original


def startup_path():
    return Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup/Claude Pet.lnk'


def register_startup(root,pythonw):
    shortcut=startup_path();shortcut.parent.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.update(CLAUDE_PET_LINK=str(shortcut),CLAUDE_PET_ROOT=str(root),CLAUDE_PET_PYW=str(pythonw))
    command=("$ErrorActionPreference='Stop'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:CLAUDE_PET_LINK); "
        "$s.TargetPath=$env:CLAUDE_PET_PYW; $s.Arguments='-X utf8 -I '+[char]34+$env:CLAUDE_PET_ROOT+'\\pet.pyw'+[char]34+' --login-start'; "
        "$s.WorkingDirectory=$env:CLAUDE_PET_ROOT; $s.IconLocation=$env:CLAUDE_PET_ROOT+'\\assets\\claude-pet.ico'; $s.Save()")
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],env=env,check=True,
        capture_output=True,creationflags=0x08000000,timeout=20)


def runtime_python(root):return Path(root)/'.runtime'/'Scripts'/'python.exe'


def prepare_runtime(root):
    if sys.version_info<(3,12):raise RuntimeError('Python 3.12+ with tkinter is required')
    root=Path(root);folder=root/'.runtime';python=runtime_python(root)
    if not python.exists():venv.EnvBuilder(with_pip=True).create(folder)
    subprocess.run([str(python),'-X','utf8','-I','-c','import tkinter, ssl, venv'],check=True,timeout=30)
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','Pillow>=11.0,<13'],check=True,timeout=180)
    subprocess.run([str(python),'-X','utf8','-I','-c','from PIL import Image; import tkinter'],check=True,timeout=30)
    return python


def start_pet(root,python=None,tray_only=False):
    python=Path(python or runtime_python(root)).with_name('pythonw.exe')
    args=[str(python),'-X','utf8','-I',str(Path(root)/'pet.pyw')]
    if tray_only:args.append('--tray-only')
    return subprocess.Popen(args,cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,creationflags=0x08000000)
