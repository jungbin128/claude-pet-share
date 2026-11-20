"""GitHub-only update checks; downloads never contain user data."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from distribution import REPOSITORY,MAX_TOTAL,version,digest,read_archive,atomic_json


def powershell_fetch(url,destination=None):
    env=os.environ.copy();env['CLAUDE_PET_URL']=url
    prefix="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
    if destination:
        env['CLAUDE_PET_DOWNLOAD']=str(destination)
        command=prefix+"Invoke-WebRequest -UseBasicParsing -Uri $env:CLAUDE_PET_URL -OutFile $env:CLAUDE_PET_DOWNLOAD -TimeoutSec 45"
    else:
        command=prefix+"$r=Invoke-RestMethod -Uri $env:CLAUDE_PET_URL -Headers @{'User-Agent'='ClaudePet';'Accept'='application/vnd.github+json'} -TimeoutSec 30; $r | ConvertTo-Json -Depth 20 -Compress"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],env=env,
        check=True,capture_output=True,encoding='utf8',errors='replace',creationflags=0x08000000,timeout=55)
    if destination:return
    if len(result.stdout)>2*1024*1024:raise ValueError('Release metadata too large')
    return json.loads(result.stdout)


def release_offer(data,current):
    if not isinstance(data,dict) or data.get('draft') or data.get('prerelease'):return None
    tag=data.get('tag_name');new=version(tag)
    if new<=version(current):return None
    name='claude-pet-'+tag+'.zip'
    assets=[a for a in data.get('assets',[]) if a.get('name')==name]
    if len(assets)!=1:raise ValueError('Missing unique source package')
    asset=assets[0];checksum=asset.get('digest','')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',checksum):raise ValueError('Release asset has no SHA-256 digest')
    expected=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
    if asset.get('browser_download_url')!=expected:raise ValueError('Untrusted update download URL')
    if type(asset.get('size')) is not int or not 0<asset['size']<=MAX_TOTAL:raise ValueError('Invalid update size')
    return {'version':tag,'url':expected,'digest':checksum[7:],'size':asset['size']}


def download_offer(base,offer,fetch=powershell_fetch):
    folder=Path(base)/'updates';folder.mkdir(exist_ok=True)
    temporary=folder/('download-'+offer['version']+'.tmp')
    target=folder/('claude-pet-'+offer['version']+'.zip')
    try:
        fetch(offer['url'],temporary)
        if temporary.stat().st_size!=offer['size']:raise ValueError('Download size mismatch')
        manifest,_=read_archive(temporary,offer['digest'])
        if manifest['version']!=offer['version']:raise ValueError('Downloaded version mismatch')
        os.replace(temporary,target)
        return target
    finally:temporary.unlink(missing_ok=True)


def safe_to_restart():
    try:
        with socket.create_connection(('127.0.0.1',48765),timeout=.5) as connection:
            connection.settimeout(.8);connection.sendall(b'prepare-update')
            return connection.recv(16)==b'yes'
    except OSError:return False


class UpdateService:
    INTERVAL=300
    def __init__(self,base,fetch=powershell_fetch):
        self.base=Path(base);self.fetch=fetch;self.offer=None;self.package=None
        try:
            self.current_version=(self.base/'VERSION').read_text(encoding='utf8').strip()
            version(self.current_version)
        except (OSError,ValueError):self.current_version='확인 불가'
        self.version_label='현재 버전 '+self.current_version
        self.status='확인 전';self.busy=False;self.install_requested=False
        self.next_check=time.monotonic()+15;self._lock=threading.Lock()
        self._idle_result=False;self._idle_at=0;self._idle_checking=False;self.manual_requested=False;self.prepared=False
        try:
            metadata=json.loads((self.base/'install.json').read_text(encoding='utf8'))
            self.enabled=metadata.get('managed') is True and metadata.get('repository')==REPOSITORY and not (self.base/'.git').exists()
        except (OSError,ValueError,AttributeError):self.enabled=False
        if not self.enabled:self.status='공유 설치에서 사용'
        try:self.auto=json.loads((self.base/'update_config.json').read_text(encoding='utf8')).get('auto') is True
        except (OSError,ValueError,AttributeError):self.auto=False

    def set_auto(self,value):
        atomic_json(self.base/'update_config.json',{'auto':bool(value)})
        self.auto=bool(value)
        if not self.auto and not self.manual_requested:self.install_requested=False

    def check(self):
        if not self.enabled or self.busy:return
        self._start(False)

    def request_install(self):
        if self.enabled and self.offer and not self.busy:
            self.manual_requested=True
            self._start(True)

    def _start(self,download):
        with self._lock:
            if self.busy:return
            self.busy=True
        self.status='다운로드 중' if download else '확인 중'
        def work():
            try:
                if not download:
                    current=(self.base/'VERSION').read_text(encoding='utf8').strip()
                    data=self.fetch(f'https://api.github.com/repos/{REPOSITORY}/releases/latest')
                    self.offer=release_offer(data,current);self.package=None;self.install_requested=False;self.manual_requested=False
                if self.offer and (download or self.auto):
                    self.package=download_offer(self.base,self.offer,self.fetch)
                    self.install_requested=download or self.auto
                    self.status='적용 대기' if self.install_requested else '다운로드 완료'
                else:self.status=self.offer['version']+' 사용 가능' if self.offer else '최신 버전'
            except Exception:
                self.status='연결·검증 실패'
            finally:
                self.next_check=time.monotonic()+self.INTERVAL
                self.busy=False
        threading.Thread(target=work,name='ClaudePetUpdate',daemon=True).start()

    def can_apply(self,child_alive):
        if not child_alive:return True
        now=time.monotonic()
        if now-self._idle_at<1:return self._idle_result
        if not self._idle_checking:
            self._idle_checking=True
            def probe():
                try:
                    self._idle_result=safe_to_restart();self.prepared=self._idle_result
                    self._idle_at=time.monotonic()
                finally:self._idle_checking=False
            threading.Thread(target=probe,name='ClaudePetIdleCheck',daemon=True).start()
        return False

    def tick(self):
        if self.enabled and not self.busy and not self.install_requested and time.monotonic()>=self.next_check:self.check()


def launch_worker(base,package,offer,wait_pid,tray_only=False):
    base=Path(base)
    if (base/'.git').exists():raise ValueError('Automatic replacement is disabled for development checkouts')
    read_archive(package,offer['digest'])
    folder=Path(tempfile.mkdtemp(prefix='claude-pet-update-'))
    for name in ('update_worker.py','distribution.py','integration.py','uninstall.py'):
        shutil.copyfile(base/name,folder/name)
    plan={'root':str(base),'package':str(package),'digest':offer['digest'],'wait_pid':wait_pid,
        'python':sys.executable,'tray_only':tray_only,'version':offer['version']}
    atomic_json(folder/'plan.json',plan)
    try:
        (base/'.update-in-progress').write_text('Updating managed program files',encoding='utf8')
        helper=Path(getattr(sys,'_base_executable',sys.executable)).with_name('pythonw.exe')
        if not helper.exists():helper=Path(getattr(sys,'_base_executable',sys.executable))
        subprocess.Popen([str(helper),'-X','utf8','-I',str(folder/'update_worker.py'),str(folder/'plan.json')],
            cwd=folder,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
    except Exception:
        (base/'.update-in-progress').unlink(missing_ok=True);shutil.rmtree(folder)
        raise


def update_menu_items(service,back):
    return [
        ('뒤로',back,False,True,{'icon':'back'}),None,
        ('업데이트 상태',None,False,True,{'section':True,'value':service.status}),
        ('새 버전 확인',service.check,False,True,{'icon':'clock','disabled':service.busy or not service.enabled}),
        ('지금 업데이트',service.request_install,False,False,{'icon':'open','disabled':service.busy or not service.offer or not service.enabled}),
        None,
        ('자동 업데이트',lambda:service.set_auto(not service.auto),False,True,{'icon':'clock','disabled':not service.enabled,
            'toggle':{'label':'','value':service.auto,'change':lambda:service.set_auto(not service.auto)}}),
    ]
