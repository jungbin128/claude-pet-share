"""Reviewed-source, per-user setup. No administrator or GitHub login required."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent))
from distribution import REPOSITORY,read_archive,apply_package,restore_backup,atomic_json
from integration import install_root,prepare_runtime,register_hooks,register_startup,start_pet


def install(package,destination=None,home=None,runtime=prepare_runtime,hooks=register_hooks,startup=register_startup,launch=True):
    destination=install_root(destination or Path.home()/'.claude'/'claude-pet',home)
    manifest,_=read_archive(package)
    from integration import hook_settings
    settings_path=destination.parent/"settings.json"
    if settings_path.exists():hook_settings(json.loads(settings_path.read_text(encoding="utf-8-sig")),destination,Path("python.exe"))
    destination.mkdir(parents=True,exist_ok=True)
    if (destination/'pet.pid').exists():raise RuntimeError('An existing pet may be running. Hide it before reinstalling; use the updater for an installed copy.')
    python=runtime(destination)
    backup=destination/'updates'/('install-backup-'+uuid.uuid4().hex)
    apply_package(destination,package,backup)
    settings=destination.parent/'settings.json'
    old_settings=settings.read_bytes() if settings.exists() else None
    try:
        hooks(destination,python)
        startup(destination,Path(python).with_name('pythonw.exe'))
        atomic_json(destination/'install.json',{'schema':1,'managed':True,'repository':REPOSITORY,
            'python':str(python),'installed_at':datetime.now(timezone.utc).isoformat()})
    except Exception:
        # Restore only if no unrelated settings edit happened after our hook update.
        from integration import hook_settings
        expected=hook_settings(json.loads(old_settings.decode('utf-8-sig')) if old_settings else {},destination,python)
        try:
            if settings.exists() and json.loads(settings.read_text(encoding='utf-8-sig'))==expected:
                if old_settings is None:settings.unlink()
                else:settings.write_bytes(old_settings)
        finally:restore_backup(destination,backup)
        raise
    if launch:start_pet(destination,python)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--no-launch',action='store_true')
    parser.add_argument('--inspect',action='store_true',help='Validate package without installing anything')
    args=parser.parse_args()
    if args.inspect:
        manifest,_=read_archive(args.package)
        print(json.dumps({'version':manifest['version'],'files':len(manifest['files']),
            'destination':str(Path.home()/'.claude'/'claude-pet'),'network':'PyPI for Pillow; GitHub for updates'},ensure_ascii=False))
    else:
        result=install(args.package,launch=not args.no_launch)
        print('Claude Pet '+result['version']+' setup complete.')


if __name__=='__main__':main()
