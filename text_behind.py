"""Local OCR/accessibility worker with transient captures and bounded recognition cache."""
import json
import hashlib
import base64
import ctypes
import os
from pathlib import Path
import queue
import subprocess
import threading
import time



_CAPTURE_LOCK=threading.Lock()



def region_has_detail(image):
    """Do not let OCR hallucinate text on an essentially flat background."""
    low,high=image.convert('L').getextrema()
    return high-low>=12


def capture_regions(regions):
    """Read behind our own overlays, restoring capture flags before OCR/encoding."""
    from ctypes import wintypes
    from PIL import ImageGrab,Image
    # A private DLL wrapper keeps callback signatures isolated from the main UI thread.
    u=ctypes.WinDLL('user32',use_last_error=True)
    u.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    u.GetWindowRect.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    u.IsWindowVisible.argtypes=[ctypes.c_void_p]
    u.SetWindowDisplayAffinity.argtypes=[ctypes.c_void_p,ctypes.c_uint]
    u.GetWindowDisplayAffinity.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,ctypes.c_void_p,ctypes.c_void_p)
    u.EnumWindows.argtypes=[callback_type,ctypes.c_void_p]
    left=min(r['rect'][0] for r in regions)-16
    top=min(r['rect'][1] for r in regions)-16
    right=max(r['rect'][2] for r in regions)+16
    bottom=max(r['rect'][3] for r in regions)+16
    changed=[]
    def exclude(hwnd,_):
        pid=wintypes.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value==os.getpid() and u.IsWindowVisible(hwnd):
            rect=wintypes.RECT()
            if u.GetWindowRect(hwnd,ctypes.byref(rect)) and rect.left<right and rect.right>left and rect.top<bottom and rect.bottom>top:
                original=wintypes.DWORD()
                if not u.GetWindowDisplayAffinity(hwnd,ctypes.byref(original)) or not u.SetWindowDisplayAffinity(hwnd,0x11):
                    failed[0]=True
                else:changed.append((hwnd,original.value))
        return True
    failed=[False]
    with _CAPTURE_LOCK:
        try:
            u.EnumWindows(callback_type(exclude),None)
            if failed[0]:raise OSError('capture exclusion unavailable')
            ctypes.windll.dwmapi.DwmFlush()
            frame=ImageGrab.grab(bbox=(left,top,right,bottom),all_screens=True,include_layered_windows=True)
        finally:
            for hwnd,affinity in reversed(changed):u.SetWindowDisplayAffinity(hwnd,affinity)
            ctypes.windll.dwmapi.DwmFlush()
    result=[]
    try:
        for region in regions:
            l,t,r,b=region['rect']
            core=frame.crop((l-left,t-top,r-left,b-top))
            if not region_has_detail(core):
                continue
            patch=frame.crop((l-left-16,t-top-16,r-left+16,b-top+16)).convert('RGBA')
            patch=patch.resize((patch.width*2,patch.height*2),Image.Resampling.BICUBIC)
            result.append({'id':region['id'],'width':patch.width,'height':patch.height,
                'pixels':base64.b64encode(patch.tobytes('raw','BGRA')).decode('ascii'),
                'roi':[32,32,32+(r-l)*2,32+(b-t)*2]})
    finally:frame.close()
    return result


def effective_transparency(manual, enabled=False, has_text=False, hovered=False):
    manual=max(0,min(80,int(manual)))
    return 80 if enabled and has_text and not hovered else manual



def plan_ocr_request(regions,cache):
    """Reuse unchanged pixels and send one exemplar for identical regions."""
    fresh=[];hits=set();pending={}
    for region in regions:
        fingerprint=(region['width'],region['height'],tuple(region['roi']),
            hashlib.blake2b(region['pixels'].encode('ascii'),digest_size=16).digest())
        if fingerprint in cache:
            detected=cache.pop(fingerprint)
            cache[fingerprint]=detected
            if detected:hits.add(region['id'])
        else:
            if fingerprint not in pending:fresh.append(region)
            pending.setdefault(fingerprint,[]).append(region['id'])
    return fresh,hits,pending


def remember_ocr_result(pending,hits,cache,limit=64):
    expanded=set()
    for fingerprint,ids in pending.items():
        detected=ids[0] in hits
        cache[fingerprint]=detected
        if detected:expanded.update(ids)
    while len(cache)>limit:cache.pop(next(iter(cache)))
    return expanded


class TextBehindWatcher:
    def __init__(self):
        self._queue=queue.Queue(maxsize=1)
        self._stop=threading.Event()
        self._proc=None
        self._busy=0
        self._result=None
        self.backend=None
        self.last_error=None
        self._ocr_cache={}
        self._thread=threading.Thread(target=self._run,daemon=True)
        self._thread.start()

    def submit(self,key,regions):
        try:self._queue.get_nowait()
        except queue.Empty:pass
        try:self._queue.put_nowait((key,regions))
        except queue.Full:pass

    def result(self):
        if self._busy and time.monotonic()-self._busy>6:
            self._kill()
            self._busy=0
            self._result=None
            self.last_error='timeout'
        return self._result

    def _kill(self):
        proc=self._proc
        if proc and proc.poll() is None:
            try:proc.kill()
            except OSError:pass

    def _run(self):
        while not self._stop.is_set():
            try:key,regions=self._queue.get(timeout=.3)
            except queue.Empty:continue
            proc=None
            cached_hits=set();pending={}
            try:
                self._busy=time.monotonic()
                try:
                    captured=capture_regions(regions)
                    fresh,cached_hits,pending=plan_ocr_request(captured,self._ocr_cache)
                    payload={'regions':fresh}
                    backend='ocr'
                except OSError:
                    payload={'pid':os.getpid(),'regions':regions}
                    backend='uia'
                if backend=='ocr' and not payload['regions']:
                    self._result=(key,cached_hits)
                    self.last_error=None
                    continue
                proc=self._proc
                if proc and self.backend!=backend:
                    self._kill();proc.wait(timeout=1)
                    for pipe in (proc.stdin,proc.stdout):pipe.close()
                    proc=None
                if proc is None or proc.poll() is not None:
                    filename='ocr_text_behind.ps1' if backend=='ocr' else 'text_behind.ps1'
                    proc=subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                        '-WindowStyle','Hidden','-File',str(Path(__file__).with_name(filename))],
                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                        creationflags=0x08000000)
                    self._proc=proc
                    self.backend=backend
                if self._stop.is_set():self._kill();break
                proc.stdin.write((json.dumps(payload)+'\n').encode('utf8'));proc.stdin.flush()
                line=proc.stdout.readline()
                if not line:raise OSError('detector stopped')
                result=json.loads(line.decode('utf-8-sig'))
                self.last_error=None if result.get('ok') else result.get('why','scan_failed')
                allowed={r['id'] for r in regions}
                hits=set(result.get('hits',[])) & allowed if result.get('ok') else set()
                if backend=='ocr':
                    hits=cached_hits | (remember_ocr_result(pending,hits,self._ocr_cache) if result.get('ok') else set())
                self._result=(key,hits)
            except (OSError,ValueError,subprocess.TimeoutExpired) as error:
                self.last_error=type(error).__name__
                self._result=(key,set())
                self._kill()
                if self._stop.wait(1):break
            finally:
                self._busy=0
                if proc and proc.poll() is not None:
                    for pipe in (proc.stdin,proc.stdout):
                        try:pipe.close()
                        except (OSError,AttributeError):pass
                    if self._proc is proc:self._proc=None
        self._kill()
        proc=self._proc
        if proc:
            try:proc.wait(timeout=.5)
            except (OSError,subprocess.TimeoutExpired):pass
            for pipe in (proc.stdin,proc.stdout):
                try:pipe.close()
                except (OSError,AttributeError):pass
            self._proc=None

    def stop(self):
        self._stop.set()
        self._kill()
