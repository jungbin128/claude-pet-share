"""Auditable source packages and transactional managed-file replacement."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from zipfile import ZipFile, ZIP_DEFLATED

REPOSITORY='jungbin128/claude-pet-share'
VERSION_PATTERN=re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')
TOP_LEVEL=set('pet.pyw pixelpet.py imagepet.py fire_rings.py pixel_finish.py pet_hook.py watchers.py multi_monitor.py screen_layout.py text_behind.py text_behind.ps1 ocr_text_behind.ps1 chat_watch.ps1 claude_ui.ps1 usage_sync.ps1 completion_state.py bubble_preferences.py autorun.py app_launch.py shell_priority.py tray_host.py uninstall.py distribution.py integration.py install.py updater.py update_fetch.py update_worker.py VERSION CHANGELOG.md README.md CLAUDE_INSTALL.md PRIVACY.md requirements.txt setup.ps1 Start Pet.cmd'.split())
# File names containing spaces are explicit rather than split into words.
TOP_LEVEL.difference_update({'Start','Pet.cmd'});TOP_LEVEL.add('Start Pet.cmd')
MAX_FILE=20*1024*1024
MAX_TOTAL=80*1024*1024


def version(value):
    if not isinstance(value,str) or not VERSION_PATTERN.fullmatch(value):raise ValueError('Invalid X.Y.Z version')
    return tuple(map(int,value.split('.')))


def digest(data):return hashlib.sha256(data).hexdigest()


def atomic_json(path,data):
    path=Path(path);temporary=path.with_name(f'{path.name}.{os.getpid()}.tmp')
    try:
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def managed_path(name):
    if not isinstance(name,str) or '\\' in name or ':' in name:raise ValueError('Unsafe package path')
    p=PurePosixPath(name)
    if p.is_absolute() or name!=p.as_posix() or any(part in ('','..','.') or part.endswith((' ','.')) for part in p.parts):raise ValueError('Unsafe package path')
    reserved={'con','prn','aux','nul',*('com'+str(i) for i in range(1,10)),*('lpt'+str(i) for i in range(1,10))}
    if any(part.split('.')[0].casefold() in reserved for part in p.parts):raise ValueError('Reserved Windows file name')
    if len(p.parts)==1 and (name in TOP_LEVEL or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.(py|pyw|ps1)',name)):return name
    if p.parts[0]=='assets' and len(p.parts) in (2,3):
        if all(re.fullmatch(r'[a-zA-Z0-9_-]+',part) for part in p.parts[1:-1]) and re.fullmatch(r'[a-zA-Z0-9_-]+\.(png|ico)',p.name):return name
    if len(p.parts)==3 and p.parts[0]=='skins' and re.fullmatch(r'[a-z0-9_-]+',p.parts[1]):
        if p.name=='skin.json' or re.fullmatch(r'[a-z][a-z0-9_]*\.png',p.name):return name
    raise ValueError('Package attempts to change a private or unmanaged file: '+name)


def validate_manifest(manifest):
    if not isinstance(manifest,dict) or manifest.get('schema')!=1:raise ValueError('Unknown package manifest')
    version(manifest.get('version'))
    if manifest.get('repository')!=REPOSITORY:raise ValueError('Wrong release repository')
    files=manifest.get('files')
    if not isinstance(files,dict) or not files or len(files)>200:raise ValueError('Invalid file manifest')
    if not {'pet.pyw','pet_hook.py','tray_host.py','install.py','updater.py','VERSION','requirements.txt'}<=files.keys():raise ValueError('Incomplete package')
    seen=set()
    for name,hash_value in files.items():
        managed_path(name)
        if name.casefold() in seen:raise ValueError('Duplicate case-insensitive path')
        seen.add(name.casefold())
        if not isinstance(hash_value,str) or not re.fullmatch('[0-9a-f]{64}',hash_value):raise ValueError('Invalid file checksum')
    minimum=manifest.get('python_min',[3,12])
    if not isinstance(minimum,list) or len(minimum)!=2 or any(type(v) is not int for v in minimum) or tuple(minimum)>sys.version_info[:2]:raise ValueError('A newer Python runtime is required')
    return manifest


def safe_destination(root,name):
    root=Path(root)
    if root.is_symlink() or root.is_junction():raise ValueError('Redirected installation root')
    candidate=root/name
    current=candidate
    while current!=root:
        if current.is_symlink() or current.is_junction():raise ValueError('Redirected managed path: '+name)
        current=current.parent
    if not candidate.resolve().is_relative_to(root.resolve()):raise ValueError('File escapes installation')
    return candidate


def read_archive(path,expected_digest=None):
    path=Path(path)
    if path.stat().st_size>MAX_TOTAL:raise ValueError('Package too large')
    if expected_digest and digest(path.read_bytes())!=expected_digest:raise ValueError('Package SHA-256 mismatch')
    with ZipFile(path) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(n.casefold() for n in names)) or len(names)>201:raise ValueError('Duplicate or excessive archive entries')
        if sum(i.file_size for i in infos)>MAX_TOTAL:raise ValueError('Uncompressed package too large')
        for info in infos:
            if info.file_size>MAX_FILE or info.flag_bits&1 or stat.S_ISLNK(info.external_attr>>16):raise ValueError('Invalid archive member')
            if info.filename!='manifest.json':managed_path(info.filename)
        if 'manifest.json' not in names:raise ValueError('Missing package manifest')
        manifest=validate_manifest(json.loads(archive.read('manifest.json')))
        if set(names)!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Unlisted package files')
        files={name:archive.read(name) for name in manifest['files']}
        if any(digest(data)!=manifest['files'][name] for name,data in files.items()):raise ValueError('Managed file checksum mismatch')
        if files['VERSION'].decode('utf8').strip()!=manifest['version']:raise ValueError('Version does not match manifest')
        return manifest,files


def build_package(source,output):
    source=Path(source);files={}
    for name in sorted(TOP_LEVEL):
        path=source/name
        if path.is_file():files[name]=path.read_bytes()
    # The public README contains only sharing information, never personal previews.
    share=source/'docs'/'SHARE_README.md'
    if share.exists():files['README.md']=share.read_bytes()
    for prefix in ('assets','skins/charmander','skins/tokito_muichiro','skins/mung_morning'):
        for path in sorted((source/prefix).rglob('*')):
            if not path.is_file():continue
            name=path.relative_to(source).as_posix()
            packaged=(name in {'assets/claude-pet.ico','assets/claude-pet.png','assets/pet-icons/robot.png',
                               'assets/pet-icons/charmander.png','assets/fonts/mung_morning_label.png'}
                      or name.startswith(('skins/charmander/','skins/tokito_muichiro/','skins/mung_morning/')))
            if not packaged:continue
            try:managed_path(name)
            except ValueError:continue
            files[name]=path.read_bytes()
    manifest={'schema':1,'version':files['VERSION'].decode().strip(),'repository':REPOSITORY,
        'python_min':[3,12],'files':{name:digest(data) for name,data in sorted(files.items())}}
    validate_manifest(manifest)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        for name,data in sorted(files.items()):archive.writestr(name,data)
    read_archive(output)
    return manifest


def backup_files(root,names,backup):
    root=Path(root);backup=Path(backup);backup.mkdir(parents=True,exist_ok=False)
    existed=[]
    for name in names:
        path=safe_destination(root,name)
        if path.exists():
            if not path.is_file():raise ValueError('Managed target is not a file')
            target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);existed.append(name)
    atomic_json(backup/'backup-index.json',{'paths':list(names),'existed':existed})


def restore_backup(root,backup):
    root=Path(root);backup=Path(backup);index=json.loads((backup/'backup-index.json').read_text(encoding='utf8'))
    for name in index['paths']:
        if name not in ('manifest.json','installed_manifest.json'):managed_path(name)
        path=safe_destination(root,name)
        if name in index['existed']:
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(backup/name,path)
        else:path.unlink(missing_ok=True)


def apply_package(root,package,backup,expected_digest=None):
    root=Path(root);manifest,files=read_archive(package,expected_digest)
    previous={}
    metadata=root/'installed_manifest.json'
    if metadata.exists():previous=validate_manifest(json.loads(metadata.read_text(encoding='utf8')))['files']
    names=sorted(set(files)|set(previous)|{'manifest.json','installed_manifest.json'})
    for name in names:safe_destination(root,name)
    for name in set(files)-set(previous):
        existing=root/name
        if existing.exists() and (not existing.is_file() or existing.read_bytes()!=files[name]):
            raise ValueError('Preserving an existing unmanaged file: '+name)
    backup_path=Path(backup).absolute()
    if not backup_path.is_relative_to(root.absolute()):raise ValueError("Backup must stay inside installation")
    safe_destination(root,backup_path.relative_to(root.absolute()).as_posix())
    backup_files(root,names,backup)
    try:
        for name,data in files.items():
            path=safe_destination(root,name);path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_name(path.name+'.update-tmp')
            try:
                temporary.write_bytes(data);os.replace(temporary,path)
            finally:temporary.unlink(missing_ok=True)
        for name in set(previous)-set(files):safe_destination(root,name).unlink(missing_ok=True)
        atomic_json(root/'manifest.json',manifest);atomic_json(metadata,manifest)
    except Exception:
        restore_backup(root,backup)
        raise
    return manifest
