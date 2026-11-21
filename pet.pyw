"""Claude 펫 — 화면 위에 늘 떠 있는 픽셀 펫 한 마리 + 작업방(대화)마다 말풍선 하나.

state/*.json 을 0.25초마다 읽는다 (바뀐 파일만 다시 읽음).
  - Claude Code: pet_hook.py (훅)이 기록
  - 코워크·일반 채팅: watchers.py 가 앱 기록·화면 정보(UI Automation)를 읽어 기록
말풍선: 대화마다 하나, 펫 둘레 6자리(왼위·오른위·왼쪽·오른쪽·왼아래·오른아래)에 퍼진다.
  한 번 정한 자리는 그 대화가 계속 쓴다. 작업 중이면 큰 말풍선(진행 막대 + 지금 하는 일), 끝나면 작은 말풍선.
  말풍선을 누르면 그 대화가 Claude 앱에서 열리고, 오른쪽 위 X 로 숨긴다.
  말풍선 밑 흰 막대에 올리면 입력창 → Enter 로 그 대화에 바로 보낸다 (한글 조합은 입력창 안에서 바로 보임).
펫: 평소엔 가만히, 안테나 전구만 상태 색으로 빛남. 커서를 올리면 폴짝 + 손 흔들기, 작업이 끝나면 확인할 때까지 만세 리액션 반복.
  펫 밑 흰 막대에 올리면 판: 새 대화 버튼 + 사용량(현재·주간 %, 리셋 시각, 동기화 버튼).
조작: 드래그로 이동(모니터별 위치 기억), 우클릭 메뉴(크기 조절, 말풍선 숨기기, 끄기 등).
그림은 Pillow로 3배 크게 그린 뒤 줄이고, 픽셀 단위 투명 창(UpdateLayeredWindow)에 올린다.
"""
import ctypes
import functools
import glob
import json
import math
import os
import random
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes

# The lightweight tray host owns the visible pet worker.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__" and "--tray-child" not in sys.argv:
    from tray_host import run
    try:
        run(automatic=any(arg in sys.argv for arg in ("--auto-start","--login-start","--claude-start","--claude-session-start")),
            source="login" if "--login-start" in sys.argv else "claude",
            fresh="--claude-session-start" in sys.argv,tray_only="--tray-only" in sys.argv)
    except Exception:
        import traceback
        with open(os.path.join(os.path.dirname(__file__), "pet_error.log"), "a", encoding="utf8") as log:
            traceback.print_exc(file=log)
    sys.exit(0)

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pixelpet  # noqa: E402
import imagepet  # noqa: E402
from autorun import prepare_launch, is_suspended, set_enabled, set_mode, summary as autorun_summary, autorun_menu_items
from shell_priority import ShellPriority
from completion_state import CompletionState  # noqa: E402
from multi_monitor import MirroredPets, corresponding_center  # noqa: E402
from screen_layout import place_panel, arrange_bubbles  # noqa: E402
from text_behind import TextBehindWatcher, effective_transparency  # noqa: E402
from bubble_preferences import room_options, opacity_options, bubble_geometry  # noqa: E402
BUILTIN_SKINS = {}   # 그려 둔 펫 (키 → 모듈, 모듈엔 NAME). 'robot' 은 pixelpet

ROBOT = pixelpet   # 기본 펫. 'pixelpet' 이름은 지금 쓰는 펫(로봇 또는 내 그림 펫)을 가리킨다


def set_skin(name):
    """펫 바꾸기: None/'robot' 은 로봇, 그 밖엔 skins/<name>/sprite.png 그림 펫. 실패하면 로봇."""
    global pixelpet
    skin = ROBOT
    if name in BUILTIN_SKINS:
        skin = BUILTIN_SKINS[name]
    elif name and name != "robot":
        try:
            skin = imagepet.ImageSkin(name)
        except Exception:
            log_error()
    pixelpet = skin
    try:
        pet_sprite.cache_clear()
    except NameError:
        pass
    return skin is not ROBOT


def signature_glow(state, t, since_done=None):
    """시그니처 불빛 (모든 펫 공통, docs/PET_DESIGN.md) -> (세기, 반지름 배율).
    평소: 아주 희미한 숨쉬기(4초 주기) / 작업 중: 2초 맥박 / 기다림: 1초 맥박 / 끝난 순간: 반짝 후 1.2초에 잦아듦."""
    if since_done is not None and 0 <= since_done < 1.2:
        k = 1 - since_done / 1.2
        return 0.6 + 1.0 * k, 1.0 + 1.4 * k
    if state == "working":
        return 0.25 + 0.6 * (0.5 + 0.5 * math.sin(t * math.pi)), 1.0
    if state == "waiting":
        return 0.3 + 0.6 * (0.5 + 0.5 * math.sin(t * 2 * math.pi)), 1.0
    if state == "done":
        return 0.35 + 0.35 * (0.5 + 0.5 * math.sin(t * math.pi)), 1.0
    return 0.10 + 0.14 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 4)), 1.0
from watchers import ChatWatcher, CoworkWatcher  # noqa: E402
from pet_hook import save as save_state  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE, "state")
CONF_FILE = os.path.join(BASE, "pet_config.json")
PID_FILE = os.path.join(BASE, "pet.pid")

# ---- 한 번만 실행 -------------------------------------------------------
if __name__ == "__main__":
    if "--tray-child" not in sys.argv and not prepare_launch(BASE, automatic="--auto-start" in sys.argv):
        sys.exit(0)
    try:
        _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock.bind(("127.0.0.1", 48765))
        _lock.listen(4)
        _lock.setblocking(False)
    except OSError:
        sys.exit(0)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

# ---- Win32 -------------------------------------------------------------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
try:
    SCALE = user32.GetDpiForSystem() / 96.0
except Exception:
    SCALE = 1.0

HANDLE = ctypes.c_void_p
user32.GetDC.restype = HANDLE
user32.GetDC.argtypes = [HANDLE]
user32.ReleaseDC.argtypes = [HANDLE, HANDLE]
gdi32.CreateCompatibleDC.restype = HANDLE
gdi32.CreateCompatibleDC.argtypes = [HANDLE]
gdi32.CreateDIBSection.restype = HANDLE
gdi32.CreateDIBSection.argtypes = [HANDLE, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), HANDLE, ctypes.c_uint]
gdi32.SelectObject.restype = HANDLE
gdi32.SelectObject.argtypes = [HANDLE, HANDLE]
gdi32.DeleteObject.argtypes = [HANDLE]
gdi32.DeleteDC.argtypes = [HANDLE]
user32.GetWindowLongW.argtypes = [HANDLE, ctypes.c_int]
user32.SetWindowLongW.argtypes = [HANDLE, ctypes.c_int, ctypes.c_long]
user32.UpdateLayeredWindow.argtypes = [HANDLE, HANDLE, ctypes.c_void_p, ctypes.c_void_p, HANDLE,
                                       ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = HANDLE
user32.GetAncestor.argtypes = [HANDLE, ctypes.c_uint]
user32.SetWindowPos.argtypes = [HANDLE, HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.GetForegroundWindow.restype = HANDLE
user32.GetWindowThreadProcessId.argtypes = [HANDLE, ctypes.c_void_p]
user32.SetForegroundWindow.argtypes = [HANDLE]
user32.BringWindowToTop.argtypes = [HANDLE]
user32.IsIconic.argtypes = [HANDLE]
user32.ShowWindow.argtypes = [HANDLE, ctypes.c_int]
user32.IsWindowVisible.argtypes = [HANDLE]
user32.GetWindowTextLengthW.argtypes = [HANDLE]
user32.GetWindowTextW.argtypes = [HANDLE, ctypes.c_wchar_p, ctypes.c_int]
user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]

# 한글 입력기(IMM) 함수 형식은 한 번만 정한다 (입력창이 0.04초마다 부름)
imm32 = ctypes.windll.imm32
imm32.ImmGetContext.restype = HANDLE
imm32.ImmGetContext.argtypes = [HANDLE]
imm32.ImmReleaseContext.argtypes = [HANDLE, HANDLE]
imm32.ImmGetCompositionStringW.argtypes = [HANDLE, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]


def S(v):
    return int(round(v * SCALE))


_last_err = [None]


def log_error():
    """같은 오류는 한 번만 pet_error.log 에 남긴다."""
    import traceback
    tb = traceback.format_exc()
    if tb == _last_err[0]:
        return
    _last_err[0] = tb
    try:
        with open(os.path.join(BASE, "pet_error.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + tb + "\n")
    except Exception:
        pass


_shell_priority = None


class Layered:
    """Tk 창을 픽셀 단위 알파 창으로 바꾸고 PIL 이미지를 올린다."""

    def __init__(self, win):
        self.win = win
        win.update_idletasks()
        self.refresh()

    def refresh(self):
        """Tk 는 창을 다시 보일 때 실제 창(HWND)을 새로 만들 수 있어 매번 확인한다."""
        hwnd = int(self.win.wm_frame(), 16)
        self.hwnd = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
        want = 0x80000 | 0x80 | 0x08000000  # LAYERED | TOOLWINDOW | NOACTIVATE
        ex = user32.GetWindowLongW(self.hwnd, -20)
        if ex & want != want:
            user32.SetWindowLongW(self.hwnd, -20, ex | want)

    def show(self, img, x, y):
        self.refresh()
        w, h = img.size
        # 알파 곱하기(premultiply)를 한 번에 → B,G,R,A 순서로
        data = img.convert("RGBa").tobytes("raw", "BGRa")
        sdc = user32.GetDC(None)
        mdc = gdi32.CreateCompatibleDC(sdc)
        hbmp = old = None
        try:  # 중간에 실패해도 그리기 자원(DC·비트맵)은 반드시 돌려준다
            bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(mdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            if not hbmp or not bits.value:
                return
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(mdc, hbmp)
            pt, src = wintypes.POINT(int(x), int(y)), wintypes.POINT(0, 0)
            size = wintypes.SIZE(w, h)
            blend = BLENDFUNCTION(0, 0, 255, 1)
            user32.UpdateLayeredWindow(self.hwnd, sdc, ctypes.byref(pt), ctypes.byref(size), mdc,
                                       ctypes.byref(src), 0, ctypes.byref(blend), 2)
        finally:
            if old:
                gdi32.SelectObject(mdc, old)
            if hbmp:
                gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(None, sdc)

    def move(self, x, y):
        user32.SetWindowPos(self.hwnd, None, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0010)

    def topmost(self):
        if _shell_priority is not None:
            _shell_priority.raise_window(self.hwnd)
        else:
            user32.SetWindowPos(self.hwnd, HANDLE(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)


# ---- 모양 · 색 · 글꼴 -----------------------------------------------------
SS = 3      # 3배로 그린 뒤 줄여서 매끈하게
PIX_MIN, PIX_MAX = 1, 5   # 소수 배율 지원, 클릭마다 약 10% 조절 (pet_config.json 의 fc)
FONT_DIR = os.path.join(os.environ.get("WINDIR",r"C:\Windows"),"Fonts")


def font(size, bold=False):
    return ImageFont.truetype(os.path.join(FONT_DIR, "malgunbd.ttf" if bold else "malgun.ttf"), S(size))


F_TITLE, F_BODY, F_MENU = font(12.5, True), font(12), font(12)
F_SMALL = font(10.5)
F_TINY = font(9.5)

C = {  # (펫 몸 색은 pixelpet.PAL)
    # 말풍선 · 메뉴 (밝은 회백색 바탕, 진한 글자)
    "bubble": (249, 249, 249), "title": (26, 26, 30), "text": (118, 118, 124), "faint": (150, 150, 156),
    "sub": (128, 128, 134), "bubble_top": (246, 246, 246), "bubble_bot": (230, 230, 232),
    "bubble_line": (206, 206, 210), "bar_bg": (218, 218, 222), "input": (255, 255, 255),
    "menu_hover": (236, 236, 240), "danger": (220, 60, 60), "sep": (228, 228, 232),
    # 상태
    "idle": (148, 160, 190), "working": (59, 130, 246), "waiting": (245, 158, 11), "done": (34, 197, 94),
}
PRIORITY = {"waiting": 3, "working": 2, "done": 1, "idle": 0}


def rgba(c, a=255):
    return tuple(c[:3]) + (a,)


@functools.lru_cache(maxsize=24)
def soft_shadow(w, h, radius, blur, alpha):
    m = blur * 3
    im = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([m, m, m + w, m + h], radius=radius, fill=(0, 0, 0, alpha))
    return im.filter(ImageFilter.GaussianBlur(blur)), m


_ss_fonts = {}


TEXT_WEIGHT = 60   # 글자 외곽선 진하기 (0 = 맑은 고딕 그대로, 255 = 한 단계 굵게)


def bold_text(big, xy, text, fnt, color, anchor, stroke=1):
    """3배 그림판(big)에 글자를 반투명한 아주 얇은 외곽선과 함께 써서, 맑은 고딕을 살짝만 굵게."""
    if not text:
        return
    k = (fnt.path, fnt.size)
    f2 = _ss_fonts.get(k)
    if f2 is None:
        f2 = _ss_fonts[k] = ImageFont.truetype(fnt.path, fnt.size * SS)
    x, y = xy[0] * SS, xy[1] * SS
    d = ImageDraw.Draw(big)
    x0, y0, x1, y1 = d.textbbox((x, y), text, font=f2, anchor=anchor, stroke_width=stroke)
    x0, y0 = int(x0) - 2, int(y0) - 2
    layer = Image.new("RGBA", (int(x1) - x0 + 4, int(y1) - y0 + 4), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((x - x0, y - y0), text, font=f2, fill=rgba(color), anchor=anchor,
                               stroke_width=stroke, stroke_fill=rgba(color, TEXT_WEIGHT))
    big.alpha_composite(layer, (max(0, x0), max(0, y0)))


def trunc(text, fnt, maxw):
    text = " ".join(str(text or "").split())
    if fnt.getlength(text) <= maxw:
        return text
    while text and fnt.getlength(text + "…") > maxw:
        text = text[:-1]
    return text + "…"


# ---- 설정 · 상태 ---------------------------------------------------------
def load_conf():
    try:
        with open(CONF_FILE, encoding="utf-8") as f:
            conf = json.load(f)
        if isinstance(conf, dict):
            # Keep existing users' selected skin when its public ID changes.
            aliases = {"cinder": "charmander", "muichiro": "tokito_muichiro"}
            skin = conf.get("skin")
            if isinstance(skin, str) and skin in aliases:
                conf["skin"] = aliases[skin]
                save_conf(conf)
        return conf
    except Exception:
        return {}


def save_conf(c):
    if __name__ != "__main__":   # 시험용으로 불러온 경우 실제 설정(위치 등)을 덮어쓰지 않는다
        return
    tmp = f"{CONF_FILE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f)
        os.replace(tmp, CONF_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


class _MonInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def work_area(pt=None):
    """작업 영역(작업표시줄 제외). pt 를 주면 그 점에서 가장 가까운 모니터 기준 (모니터 여러 대 지원)."""
    if pt is not None:
        try:
            hm = user32.MonitorFromPoint(wintypes.POINT(int(pt[0]), int(pt[1])), 2)  # NEAREST
            mi = _MonInfo(cbSize=ctypes.sizeof(_MonInfo))
            if hm and user32.GetMonitorInfoW(hm, ctypes.byref(mi)):
                w = mi.rcWork
                return w.left, w.top, w.right, w.bottom
        except Exception:
            pass
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom



def enumerate_work_areas():
    """Enumerate attached displays, including negative desktop coordinates."""
    areas = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, HANDLE, HANDLE, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def visit(hm, dc, rect, data):
        info = _MonInfo(cbSize=ctypes.sizeof(_MonInfo))
        if user32.GetMonitorInfoW(hm, ctypes.byref(info)):
            w = info.rcWork
            areas.append((w.left, w.top, w.right, w.bottom))
        return True
    callback = callback_type(visit)
    user32.EnumDisplayMonitors.argtypes = [HANDLE, ctypes.c_void_p, callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return sorted(set(areas)) or [work_area()]


def focus_claude_window():
    found = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip() == "Claude":
                    found.append(hwnd)
        return True

    user32.EnumWindows(proto(cb), 0)
    if not found:
        return
    h = found[0]
    if user32.IsIconic(h):
        user32.ShowWindow(h, 9)  # SW_RESTORE
    # Alt 키 흉내는 Claude 메뉴(File/Edit…)를 열어 버리므로 쓰지 않는다.
    if not user32.SetForegroundWindow(h):
        fg = user32.GetForegroundWindow()
        t_fg = user32.GetWindowThreadProcessId(fg, None)
        t_me = ctypes.windll.kernel32.GetCurrentThreadId()
        user32.AttachThreadInput(t_me, t_fg, True)
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
        user32.AttachThreadInput(t_me, t_fg, False)


MAX_BUBBLES = 5


_file_cache = {}   # 상태 파일 → (수정 시각, 크기, 읽은 내용): 바뀐 파일만 다시 읽는다


def _load_state(p):
    st_ = os.stat(p)
    key = (st_.st_mtime_ns, st_.st_size)
    hit = _file_cache.get(p)
    if hit and hit[0] == key:
        return dict(hit[1])
    with open(p, encoding="utf-8") as f:
        s = json.load(f)
    if not isinstance(s, dict):
        raise ValueError("not a state dict")
    _file_cache[p] = (key, s)
    return dict(s)


def read_sessions(limit=MAX_BUBBLES):
    """말풍선을 띄울 대화들 (덜 급한 것 → 급한 것 순서; 마지막이 펫 바로 위).
    나이에 따른 상태 변화(30분·12시간·3일·숨김)는 매번 다시 계산한다."""
    now = time.time()
    out = []
    paths = glob.glob(os.path.join(STATE_DIR, "*.json"))
    path_set = set(paths)
    for p in list(_file_cache):
        if p not in path_set:
            _file_cache.pop(p, None)
    for p in paths:
        try:  # 파일 하나가 깨져도 나머지 말풍선은 그대로
            s = _load_state(p)
            sid = s.get("session_id") or os.path.splitext(os.path.basename(p))[0]
            if sid == "unknown":
                continue
            upd = float(s.get("updated") or 0)
            age = now - upd
            if age > 3 * 24 * 3600:
                try:
                    os.remove(p)
                except Exception:
                    pass
                continue
            if s.get("dismissed") and upd <= float(s["dismissed"]) + 1:
                continue  # 사용자가 숨긴 말풍선 (새 활동이 생기면 다시 나타남)
            st = s.get("state", "idle")
            if st not in PRIORITY:
                continue
            if st in ("working", "waiting") and age > 30 * 60:
                st = "idle"
            if st == "idle" or (st == "done" and age > 12 * 3600):
                continue
            s["session_id"] = sid
            s["_state"] = st
            out.append(s)
        except Exception:
            continue
    out.sort(key=lambda s: (PRIORITY[s["_state"]], s.get("updated", 0)))
    return out if limit is None else out[-limit:]


def set_dismissed(sid):
    p = os.path.join(STATE_DIR, f"{sid}.json")
    try:
        with open(p, encoding="utf-8") as f:
            s = json.load(f)
        s["dismissed"] = time.time()
        save_state(p, s)  # 원자적 저장 (훅과 동시에 써도 내용이 날아가지 않게)
    except Exception:
        log_error()


def fmt_dur(sec):
    sec = int(max(0, sec))
    if sec < 60:
        return f"{sec}초"
    if sec < 3600:
        return f"{sec // 60}분{sec % 60}초" if sec < 600 else f"{sec // 60}분"
    return f"{sec // 3600}시간{sec % 3600 // 60}분"


# ---- 그리기 도우미 -------------------------------------------------------
class Pen:
    """논리 좌표로 그리면 (SCALE×SS) 픽셀로 바꿔 그린다. ox, oy 는 원점 이동."""

    def __init__(self, img, ox=0.0, oy=0.0):
        self.d = ImageDraw.Draw(img)
        self.k = SCALE * SS
        self.ox, self.oy = ox, oy

    def _b(self, x0, y0, x1, y1):
        k = self.k
        return [(self.ox + x0) * k, (self.oy + y0) * k, (self.ox + x1) * k, (self.oy + y1) * k]

    def rrect(self, x0, y0, x1, y1, r, fill):
        self.d.rounded_rectangle(self._b(x0, y0, x1, y1), radius=r * self.k, fill=fill)

    def oval(self, cx, cy, rx, ry, fill):
        self.d.ellipse(self._b(cx - rx, cy - ry, cx + rx, cy + ry), fill=fill)

    def arc(self, cx, cy, r, start, end, w, fill):
        self.d.arc(self._b(cx - r, cy - r, cx + r, cy + r), start, end, fill=fill, width=max(1, int(w * self.k)))

    def line(self, pts, w, fill):
        k = self.k
        q = [((self.ox + x) * k, (self.oy + y) * k) for x, y in pts]
        self.d.line(q, fill=fill, width=max(1, int(w * k)), joint="curve")
        for x, y in (pts[0], pts[-1]):
            self.oval(x, y, w / 2, w / 2, fill)


# ---- 우클릭 메뉴 ---------------------------------------------------------
@functools.lru_cache(maxsize=32)
def pet_menu_logo(key):
    """Load the small face emblem; other skins get an automatic sprite thumbnail."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pet-icons", key + ".png")
        if os.path.isfile(path):
            with Image.open(path) as source:
                return source.convert("RGBA")
        source = (ROBOT if key == "robot" else BUILTIN_SKINS.get(key))
        sprite = source.draw() if source else imagepet.ImageSkin(key).sprite
        box = sprite.getbbox()
        if box:
            sprite = sprite.crop(box)
        sprite.thumbnail((30, 30), Image.Resampling.NEAREST)
        logo = Image.new("RGBA", (32, 32))
        logo.alpha_composite(sprite, ((32 - sprite.width) // 2, (32 - sprite.height) // 2))
        return logo
    except (OSError, ValueError, KeyError):
        return None


class Menu:
    W = 236
    ITEM_H = 38
    PAD = 8
    HEADER = 62
    SHADOW = 14

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry("1x1+-32000+-32000")
        self.layer = Layered(self.win)
        # 창을 숨겼다(withdraw) 다시 보이면 Tk 가 실제 창을 새로 만들어 투명 그리기가 깨진다(회색 상자).
        # 그래서 메뉴 창은 늘 띄워 두고, 닫을 땐 화면 밖의 투명한 1픽셀로 만든다.
        self._blank = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        self.layer.show(self._blank, -32000, -32000)
        self.open_ = False
        self.hover = -1
        self.items = []
        self._slider_drag = None
        self._slider_timer = None
        self.win.bind("<ButtonPress-1>", self.on_slider_press)
        self.win.bind("<B1-Motion>", self.on_slider_motion)
        self.win.bind("<Motion>", self.on_motion)
        self.win.bind("<Leave>", lambda e: self.set_hover(-1))
        self.win.bind("<ButtonRelease-1>", self.on_click)

    def layout(self):
        rows, y = [], self.PAD + self.HEADER
        for it in self.items:
            meta=it[4] if it is not None and len(it)>4 else {}
            h=9 if it is None else (28 if meta.get("section") else (84 if "slider" in meta else self.ITEM_H))
            rows.append((it, y, y + h))
            y += h
        return rows, y + self.PAD

    def render(self):
        rows, h = self.layout()
        m = self.SHADOW
        W, H = S(self.W + 2 * m), S(h + 2 * m)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sh, sm = soft_shadow(S(self.W), S(h), S(16), S(6), 65)
        img.alpha_composite(sh, (S(m) - sm, S(m + 3) - sm))
        big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        p = Pen(big, m, m)
        p.rrect(0, 0, self.W, h, 16, (218, 215, 211, 255))
        p.rrect(0.7, 0.7, self.W - 0.7, h - 0.7, 15.5, (253, 252, 250, 255))
        p.rrect(16, 17, 44, 45, 9, (248, 230, 215, 255))
        self.draw_icon(big, "pet", m + 22, m + 23, (178, 88, 46))
        bold_text(big, (S(m + 55), S(m + 24)), self.heading, F_TITLE, (47, 43, 40), "lm", stroke=0)
        bold_text(big, (S(m + 55), S(m + 44)), self.caption, F_TINY, (139, 130, 121), "lm", stroke=0)
        p.rrect(16, 61, self.W - 16, 61.6, 0.3, (234, 230, 225, 255))
        for i, (it, y0, y1) in enumerate(rows):
            if it is None:
                p.rrect(17, (y0 + y1) / 2, self.W - 17, (y0 + y1) / 2 + 0.6, 0.3, (235, 231, 226, 255))
                continue
            meta = it[4] if len(it) > 4 else {}
            if meta.get("section"):
                cy=(y0+y1)/2+2
                bold_text(big,(S(m+19),S(m+cy)),it[0],F_SMALL,(128,119,110),"lm",stroke=0)
                bold_text(big,(S(m+self.W-19),S(m+cy)),str(meta.get("value","")),F_SMALL,meta.get("value_color",(178,88,46)),"rm",stroke=0)
                continue
            if "slider" in meta:
                slider=meta["slider"]
                value=slider["value"]
                y=y0+42
                x0,x1=20,self.W-20
                knob=x0+(x1-x0)*(value-slider["min"])/(slider["max"]-slider["min"])
                bold_text(big,(S(m+20),S(m+y0+16)),it[0],F_MENU,(69,63,58),"lm",stroke=0)
                bold_text(big,(S(m+self.W-20),S(m+y0+16)),f"{value}%",F_MENU,(178,88,46),"rm",stroke=0)
                p.rrect(x0,y-2,x1,y+2,2,(228,222,215,255))
                if knob>x0:p.rrect(x0,y-2,knob,y+2,2,(202,127,86,255))
                p.oval(knob,y,7,7,(178,88,46,255))
                p.oval(knob,y,5.3,5.3,(255,253,250,255))
                bold_text(big,(S(m+x0),S(m+y+22)),"선명",F_TINY,(139,130,121),"lm",stroke=0)
                bold_text(big,(S(m+x1),S(m+y+22)),"투명",F_TINY,(139,130,121),"rm",stroke=0)
                continue
            disabled = meta.get("disabled", False)
            selected = meta.get("selected", False)
            if selected or (i == self.hover and not disabled):
                p.rrect(7, y0 + 2, self.W - 7, y1 - 2, 9,
                        (250, 235, 224, 255) if selected else (242, 239, 235, 255))
            color = (185, 179, 173) if disabled else ((186, 67, 56) if it[2] else (69, 63, 58))
            cy = (y0 + y1) / 2
            logo = pet_menu_logo(meta["skin"]) if "skin" in meta else None
            if logo is not None:
                p.rrect(12, cy - 15, 42, cy + 15, 8, (245, 241, 235, 255))
                logo = logo.resize((S(28) * SS, S(28) * SS), Image.Resampling.NEAREST)
                big.alpha_composite(logo, (S(m + 13) * SS, S(m + cy - 14) * SS))
            else:
                self.draw_icon(big, meta.get("icon", "pet"), m + 19, m + cy - 8, color)
            value=str(meta.get("value",""))
            reserve=77 if "toggle" in meta else (F_SMALL.getlength(value)/SCALE+10 if value else 0)
            label = trunc(it[0], F_MENU, S(self.W - 82 - reserve))
            bold_text(big, (S(m + 47), S(m + cy)), label, F_MENU, color, "lm", stroke=0)
            if value:
                bold_text(big,(S(m+self.W-(38 if meta.get("arrow") else 18)),S(m+cy)),value,F_SMALL,
                          (185,179,173) if disabled else (139,110,91),"rm",stroke=0)
            if "toggle" in meta:
                enabled=meta["toggle"]["value"]
                bold_text(big,(S(m+self.W-62),S(m+cy)),meta["toggle"].get("label","자동실행"),F_TINY,(139,130,121),"rm",stroke=0)
                x0,x1=self.W-54,self.W-15
                p.rrect(x0,cy-10,x1,cy+10,10,(244,115,35,255) if enabled else (207,203,198,255))
                p.oval((x1-10) if enabled else (x0+10),cy,7,7,(255,255,255,255))
            if selected or meta.get("arrow"):
                self.draw_icon(big, "check" if selected else "next", m + self.W - 31, m + cy - 8,
                               (178, 88, 46) if selected else (151, 142, 132))
        img.alpha_composite(big.resize((W, H), Image.LANCZOS))
        self.size, self.rows = (W, H), rows
        # UpdateLayeredWindow resizes the outer HWND only. Keep Tk's inner input
        # window at the same size, including in the independent tray host.
        geometry=f"{W}x{H}{self.x:+d}{self.y:+d}"
        if geometry!=getattr(self,"_tk_geometry",None):
            self.win.geometry(geometry)
            self.win.update_idletasks()
            self._tk_geometry=geometry
        self.layer.show(img, self.x, self.y)
        self.layer.topmost()

    @staticmethod
    def draw_icon(big, kind, x, y, color):
        """Draw consistent small line icons without relying on emoji fonts."""
        d = ImageDraw.Draw(big)
        def path(points):
            d.line([((x + a) * SCALE * SS, (y + b) * SCALE * SS) for a, b in points],
                   fill=rgba(color), width=max(1, S(1.2) * SS), joint="curve")
        if kind in ("plus", "minus", "new"):
            path([(3, 8), (13, 8)])
            if kind != "minus": path([(8, 3), (8, 13)])
            if kind == "new": path([(12, 1), (1, 1), (1, 15), (15, 15), (15, 11)])
        elif kind == "open":
            path([(9, 2), (2, 2), (2, 14), (14, 14), (14, 7)])
            path([(7, 9), (15, 1), (10, 1)]);path([(15, 1), (15, 6)])
        elif kind == "bubble":
            path([(2, 2), (14, 2), (14, 11), (7, 11), (3, 15), (3, 11), (2, 11), (2, 2)])
        elif kind == "screens":
            path([(1, 2), (11, 2), (11, 10), (1, 10), (1, 2)])
            path([(5, 10), (5, 13), (2, 13), (8, 13)])
            path([(12, 5), (15, 5), (15, 14), (10, 14), (10, 12)])
        elif kind == "back":
            path([(10, 3), (5, 8), (10, 13)])
        elif kind == "next":
            path([(6, 4), (10, 8), (6, 12)])
        elif kind == "check":
            path([(3, 8), (7, 12), (14, 4)])
        elif kind == "clock":
            d.ellipse([(x+1)*SCALE*SS,(y+1)*SCALE*SS,(x+15)*SCALE*SS,(y+15)*SCALE*SS],outline=rgba(color),width=max(1,S(1.2)*SS))
            path([(8,4),(8,8),(11,10)])
        elif kind == "size":
            path([(1,6),(1,1),(6,1)]);path([(10,15),(15,15),(15,10)])
            path([(1,1),(6,6)]);path([(10,10),(15,15)])
        elif kind == "trash":
            path([(3, 4), (13, 4)]);path([(6, 4), (6, 2), (10, 2), (10, 4)])
            path([(4, 6), (5, 14), (11, 14), (12, 6)])
            path([(7, 7), (7, 11)]);path([(9, 7), (9, 11)])
        elif kind == "power":
            path([(8, 1), (8, 8)])
            path([(4, 3), (1, 7), (2, 12), (6, 15), (11, 14), (15, 10), (14, 6), (12, 3)])
        else:
            path([(3, 4), (13, 4), (15, 8), (13, 14), (3, 14), (1, 8), (3, 4)])
            path([(5, 8), (5, 9)]);path([(11, 8), (11, 9)])
            path([(8, 1), (8, 4)])

    def navigate(self, builder, heading="Claude Pet", caption="펫 · 말풍선 · 실행 설정"):
        self.builder, self.heading, self.caption = builder, heading, caption
        self.items = builder()
        self.hover = -1
        self.fit_screen()
        self.render()

    def fit_screen(self):
        _, h = self.layout()
        l, t, r, b = work_area((self.x + S(self.SHADOW), self.y + S(self.SHADOW)))
        self.x = max(l, min(self.x, r - S(self.W + 2 * self.SHADOW)))
        self.y = max(t, min(self.y, b - S(h + 2 * self.SHADOW)))

    def popup(self, x, y, builder, heading="Claude Pet", caption="펫 · 말풍선 · 실행 설정"):
        """builder() → 메뉴 항목 [(글자, 동작, 빨간색?, 누른 뒤 메뉴 유지?) 또는 None(구분선)]."""
        self.heading, self.caption = heading, caption
        self.builder = builder
        self.items = builder()
        rows, h = self.layout()
        l, t, r, b = work_area((x, y))
        m = S(self.SHADOW)
        self.x = min(max(x + S(16) - m, l), r - S(self.W) - 2 * m)
        self.y = min(max(y - m, t), b - S(h) - 2 * m)
        self.hover = -1
        self.open_ = True
        self.render()
        self.win.after(40, lambda: self.open_ and self.render())
        self.armed = False
        self.watch()

    def close(self):
        self.finish_slider()
        self.open_ = False
        self._stop_watch()
        self.layer.show(self._blank, -32000, -32000)

    def _stop_watch(self):
        if getattr(self, "_watch_id", None):
            try:
                self.win.after_cancel(self._watch_id)
            except Exception:
                pass
            self._watch_id = None

    def item_at(self, ex, ey):
        m = self.SHADOW
        lx, ly = ex / SCALE - m, ey / SCALE - m
        if not (0 <= lx <= self.W):
            return -1
        for i, (it, y0, y1) in enumerate(self.rows):
            if it is not None and y0 <= ly < y1 and not (len(it) > 4 and (it[4].get("disabled") or it[4].get("section"))):
                return i
        return -1

    def set_hover(self, i):
        if i != self.hover and self.open_:
            self.hover = i
            self.render()

    def on_slider_press(self, e):
        i=self.item_at(e.x,e.y)
        if i>=0:
            item=self.rows[i][0]
            if len(item)>4 and "slider" in item[4]:
                self._slider_drag=i
                self._slider_x=e.x
                self.apply_slider()

    def on_slider_motion(self, e):
        if self._slider_drag is None:
            return
        self._slider_x=e.x
        if self._slider_timer is None:
            self._slider_timer=self.win.after(24,self.apply_slider)

    def apply_slider(self):
        self._slider_timer=None
        if self._slider_drag is None or not self.open_:
            return
        slider=self.rows[self._slider_drag][0][4]["slider"]
        ratio=(self._slider_x/SCALE-self.SHADOW-20)/(self.W-40)
        value=round(slider["min"]+max(0,min(1,ratio))*(slider["max"]-slider["min"]))
        if value!=slider["value"]:
            slider["change"](value)
            self.items=self.builder()
            self.render()

    def finish_slider(self):
        if self._slider_timer is not None:
            self.win.after_cancel(self._slider_timer)
            self._slider_timer=None
        if self._slider_drag is not None:
            self.apply_slider()
            slider=self.rows[self._slider_drag][0][4]["slider"]
            self._slider_drag=None
            slider["commit"]()

    def on_motion(self, e):
        self.set_hover(self.item_at(e.x, e.y))

    def on_click(self, e):
        if self._slider_drag is not None:
            self._slider_x=e.x
            self.finish_slider()
            return
        i = self.item_at(e.x, e.y)
        if i < 0:
            return
        item = self.rows[i][0]
        if len(item)>4 and "slider" in item[4]:
            return
        if len(item)>4 and "toggle" in item[4] and e.x/SCALE-self.SHADOW >= self.W-108:
            try:
                item[4]["toggle"]["change"]()
                self.items=self.builder()
                self.render()
            except Exception:
                log_error()
            return
        keep = len(item) > 3 and item[3]
        if not keep:
            self.close()
        try:
            item[1]()
        except Exception:
            log_error()
        if keep and self.open_:  # 크기 조절처럼 여러 번 누르는 항목은 메뉴를 열어 둔다
            self.items = self.builder()
            self.fit_screen()
            self.render()

    def watch(self):
        """메뉴 바깥을 누르거나 Esc 를 누르면 닫기. (타이머는 하나만 돌도록 이전 것을 취소)"""
        self._stop_watch()
        if not self.open_:
            return
        down = (user32.GetAsyncKeyState(1) & 0x8000) or (user32.GetAsyncKeyState(2) & 0x8000)
        if not down:
            self.armed = True
        elif self.armed and self._slider_drag is None:
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            W, H = self.size
            if not (self.x <= pt.x < self.x + W and self.y <= pt.y < self.y + H):
                self.close()
                return
        if user32.GetAsyncKeyState(0x1B) & 0x8000:
            self.close()
            return
        self._watch_id = self.win.after(50, self.watch)



@functools.lru_cache(maxsize=120)
def bubble_spinner(phase, transparency=0):
    """Only the tiny moving arc changes; bubble text/background stay cached."""
    size=S(16)
    big=Image.new("RGBA",(size*SS,size*SS))
    Pen(big).arc(8,8,4.5,phase*30,phase*30+110,1.8,rgba(C["working"]))
    img=big.resize((size,size),Image.Resampling.LANCZOS)
    if transparency:
        img.putalpha(img.getchannel("A").point(lambda a:round(a*(1-transparency/100))))
    return img



@functools.lru_cache(maxsize=64)
def bubble_font(path,size):
    return ImageFont.truetype(path,size)


def scaled_bubble_font(base,factor):
    return base if factor==1 else bubble_font(base.path,max(6,round(base.size*factor)))


def bubble_level(app, sid):
    conf=getattr(app,"conf",{})
    area=getattr(app,"_opacity_area",None)
    detected=getattr(app,"_text_behind",set())
    has_text=(area,sid) in detected if area is not None else sid in detected
    hovered=getattr(app,"hover_bubble",None)==sid
    if area is not None:
        hovered=hovered and getattr(app,"_hover_area",None)==area
    manual,enabled=opacity_options(conf,sid)
    return effective_transparency(manual,enabled,has_text,hovered)


def draw_bar(pen, xc, y, hot, opacity=1):
    """작은 흰 막대 + 말풍선과 같은 테두리 + 옅은 그림자 (흰 화면 위에서도 보이게)."""
    half = 17 if hot else 13
    pen.rrect(xc - half - 0.5, y - 1.5, xc + half + 0.5, y + 4, 3, (0, 0, 0, round(40*opacity)))          # 그림자
    pen.rrect(xc - half - 1, y - 3, xc + half + 1, y + 3, 3, rgba(C["bubble_line"],round(255*opacity)))     # 테두리
    pen.rrect(xc - half, y - 2, xc + half, y + 2, 2, (255, 255, 255, round((255 if hot else 240)*opacity)))


_usage_cache = {}


def read_usage():
    """Claude 앱이 이 PC에 남기는 사용량 기록 (plan-usage-history.json 의 마지막 값).
    fh = 5시간 사용량 %, sd = 주간(7일) 사용량 %. 파일이 바뀌었을 때만 다시 읽는다."""
    for p in glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\Claude-Data\claude_*\plan-usage-history.json")):
        try:
            mt = os.stat(p).st_mtime_ns
            if _usage_cache.get("key") == (p, mt):
                return _usage_cache["val"]
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            last = (d.get("samples") or [])[-1]
            u = last.get("u") or {}
            val = {"fh": float(u.get("fh", 0)), "sd": float(u.get("sd", 0)), "t": last.get("t", 0) / 1000}
            _usage_cache.update(key=(p, mt), val=val)
            return val
        except Exception:
            continue
    return None


_WD = {w: i for i, w in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
_MON = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun",
                                         "jul", "aug", "sep", "oct", "nov", "dec"))}
_KWD = "월화수목금토일"


def parse_reset(s, now=None):
    """앱 글자 'Resets at 6:40 PM' / 'Resets Sat 11:00 AM' / 'Resets Dec 11, 7:00 AM' / 'Resets in 2 hr 5 min'
    -> 다음에 오는 그 시각 (epoch 초). 못 읽으면 None."""
    import re
    import datetime as dt
    now = now or time.time()
    low = (s or "").lower()
    m = re.search(r"\bin\s+(?:(\d+)\s*h\w*)?\s*(?:(\d+)\s*m\w*)?", low)
    if m and (m.group(1) or m.group(2)) and not re.search(r"\d:\d\d", low):
        return now + int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b", low) or re.search(r"(\d{1,2}):(\d{2})()", low)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        hh = hh % 12 + (12 if m.group(3) == "p" else 0)
    base = dt.datetime.fromtimestamp(now)
    cand = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
    md = re.search(r"\b(" + "|".join(_MON) + r")[a-z]*\.?\s+(\d{1,2})\b", low)
    wd = re.search(r"\b(" + "|".join(_WD) + r")[a-z]*\b", low)
    if md:
        cand = cand.replace(month=_MON[md.group(1)], day=int(md.group(2)))
        if cand.timestamp() < now - 86400:
            cand = cand.replace(year=cand.year + 1)
    elif wd:
        cand += dt.timedelta(days=(_WD[wd.group(1)] - cand.weekday()) % 7)
        if cand.timestamp() < now - 60:
            cand += dt.timedelta(days=7)
    elif cand.timestamp() < now - 60:
        cand += dt.timedelta(days=1)
    return cand.timestamp()


def fmt_reset(ts, weekly):
    """리셋 시각 글자: 주간은 '토 11:00', 5시간은 '18:40' (오늘이 아니면 요일을 붙임)."""
    lt = time.localtime(ts)
    hm = time.strftime("%H:%M", lt)
    if weekly or time.localtime().tm_yday != lt.tm_yday:
        return f"{_KWD[lt.tm_wday]} {hm}"
    return hm


def learn_usage(conf, o, now=None):
    """채팅 감시 도우미가 읽은 앱 화면 글자(Code 입력창 옆 사용량 버튼, 설정 사용량 탭)에서
    리셋 시각과 최신 % 를 배워 conf['resets'] 에 기억한다. 바뀌었으면 True."""
    import re
    if not o:
        return False
    now = now or time.time()
    rs = conf.setdefault("resets", {})
    old = json.dumps(rs, sort_keys=True)
    btn = str(o.get("ubtn") or "")
    if btn:
        head = btn.split("Resets", 1)[0].lower()
        kind = "weekly" if "week" in head else ("session" if ("session" in head or "hour" in head) else None)
        if kind:
            ts = parse_reset(btn.split("Resets", 1)[1] if "Resets" in btn else "", now)
            if ts:
                rs[kind] = round(ts)
            p = re.search(r"(\d+(?:\.\d+)?)\s*%", btn)
            if p:
                rs[kind + "_pct"] = [float(p.group(1)), round(now)]
    for key, kind in (("sreset", "session"), ("wreset", "weekly")):
        ts = parse_reset(str(o.get(key) or ""), now)
        if ts:
            rs[kind] = round(ts)
    return json.dumps(rs, sort_keys=True) != old


def usage_view(base, rs, now=None):
    """판에 그릴 사용량: 앱 기록 파일(base) + 기억한 리셋 시각과 최신 %(rs)."""
    now = now or time.time()
    rs = rs or {}
    if not base and not rs:
        return None
    v = {"fh": (base or {}).get("fh"), "sd": (base or {}).get("sd")}
    t0 = (base or {}).get("t", 0)
    for kind, k in (("session", "fh"), ("weekly", "sd")):
        live = rs.get(kind + "_pct")
        if live and live[1] > t0:
            v[k] = live[0]
    if v["fh"] is None and v["sd"] is None:
        return None
    v["fh"], v["sd"] = v["fh"] or 0.0, v["sd"] or 0.0
    s = rs.get("session")
    v["sreset"] = fmt_reset(s, False) if s and s > now else None
    w = rs.get("weekly")
    if w:
        while w <= now:
            w += 7 * 86400   # 주간 한도는 매주 같은 요일·시각에 리셋
        v["wreset"] = fmt_reset(w, True)
    else:
        v["wreset"] = None
    return v


@functools.lru_cache(maxsize=96)
def pet_sprite(st, eyes, arms, bob, badge, stars, wave, f, skin_key=None, anim=()):
    """픽셀 펫 한 자세를 f 배로 키운 그림 (같은 자세는 다시 그리지 않고 재사용).
    anim: 평소 움직임을 그리는 펫(ANIMATED)에 넘기는 (이름, 값) 묶음 — 숨쉬기·불꽃·꼬리."""
    spr = pixelpet.draw(st, eyes=eyes, arms=arms, bob=bob, badge=badge, stars=stars, wave=wave, **dict(anim))
    _ = skin_key
    spr = spr.resize((max(1, round(spr.width * f)), max(1, round(spr.height * f))), Image.NEAREST)
    if isinstance(pixelpet, imagepet.ImageSkin) and pixelpet.nameplate:
        pixelpet.draw_nameplate(spr, f, bob=bob)
    return spr


@functools.lru_cache(maxsize=256)
def signature_halo(color, radius, blur, strength):
    """Colored inner halo plus diffuse outer light, legible on white and dark desktops."""
    outer_r = max(1, round(radius * 1.25))
    pad = outer_r + 3 * blur + 2
    size = (2 * pad, 2 * pad)
    outer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(outer).ellipse((pad - outer_r, pad - outer_r, pad + outer_r, pad + outer_r),
                                 fill=tuple(color) + (int(min(170, 150 * strength)),))
    outer = outer.filter(ImageFilter.GaussianBlur(blur))
    inner = Image.new("RGBA", size, (0, 0, 0, 0))
    near_r = max(1, round(radius * 1.05))
    ImageDraw.Draw(inner).ellipse((pad - near_r, pad - near_r, pad + near_r, pad + near_r),
                                 fill=tuple(color) + (int(min(230, 310 * strength)),))
    outer.alpha_composite(inner.filter(ImageFilter.GaussianBlur(max(1, blur * 0.42))))
    if strength > 1.0:
        flash = Image.new("RGBA", size, (0, 0, 0, 0))
        rc = radius * 0.45
        ImageDraw.Draw(flash).ellipse((pad - rc, pad - rc, pad + rc, pad + rc),
                                     fill=(255, 255, 255, int(min(255, 180 * (strength - 1.0) / 0.6))))
        outer.alpha_composite(flash.filter(ImageFilter.GaussianBlur(max(1, blur * 0.35))))
    return outer, pad


# ---- Claude 앱과 연결 ------------------------------------------------------
UI_PS1 = os.path.join(BASE, "claude_ui.ps1")
SYNC_PS1 = os.path.join(BASE, "usage_sync.ps1")


def run_usage_sync():
    """usage_sync.ps1: Claude 앱의 사용량 작은 창을 잠깐 열어 읽고 닫는다 → dict (실패하면 ok=False)."""
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                              "-File", SYNC_PS1], capture_output=True, timeout=12, stdin=subprocess.DEVNULL,
                             creationflags=0x08000000).stdout
        lines = out.decode("utf-8-sig", "replace").strip().splitlines()
        return json.loads(lines[-1]) if lines else {"ok": False, "why": "no output"}
    except Exception as ex:
        return {"ok": False, "why": type(ex).__name__}


def apply_usage_sync(conf, r, now=None):
    """동기화 결과를 conf['resets'] 에 기억 (현재·주간 % 와 리셋 시각)."""
    now = now or time.time()
    rs = conf.setdefault("resets", {})
    for key, kind in (("s", "session"), ("w", "weekly")):
        pct = r.get(f"{key}_pct")
        if pct is not None:
            rs[kind + "_pct"] = [float(pct), round(now)]
        ts = parse_reset(str(r.get(f"{key}_reset") or ""), now)
        if ts:
            rs[kind] = round(ts)


def run_ui(action, mode="code", title="", text=None):
    """claude_ui.ps1 을 백그라운드로 실행 (Claude 창은 펫이 먼저 앞으로 가져온다)."""
    args = ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
            "-File", UI_PS1, "-Action", action, "-Mode", mode]
    if title:
        args += ["-Title", title]
    if text is not None:
        p = os.path.join(BASE, f"_send_{int(time.time() * 1000)}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        args += ["-TextFile", p]
    focus_claude_window()
    try:
        subprocess.Popen(args, creationflags=0x08000000, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        log_error()


class AppTitles:
    """Claude 데스크톱 앱의 Code 대화 이름 (사이드바에 보이는 이름)을 세션 id 로 찾는다."""
    ROOT = r"%LOCALAPPDATA%\Claude-Data\claude_*\claude-code-sessions"

    def __init__(self):
        self.cache = {}   # 파일 → (mtime, cli id, title)
        self.map = {}
        self.last = 0.0

    def refresh(self):
        if time.time() - self.last < 5:
            return
        self.last = time.time()
        for f in glob.glob(os.path.join(os.path.expandvars(self.ROOT), "*", "*", "local_*.json")):
            try:
                mt = os.path.getmtime(f)
                c = self.cache.get(f)
                if c and c[0] == mt:
                    continue
                if time.time() - mt > 7 * 86400 and c is None:
                    self.cache[f] = (mt, None, None)
                    continue
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
                self.cache[f] = (mt, d.get("cliSessionId"), d.get("title"))
            except Exception:
                continue
        self.map = {c[1]: c[2] for c in self.cache.values() if c[1] and c[2]}

    def target(self, s):
        """(모드, 사이드바 이름, 말풍선 제목)"""
        src = s.get("source")
        if src == "chat":
            return "chat", "", s.get("title") or "채팅"
        if src == "cowork":
            return "chat", s.get("title") or "", s.get("title") or "코워크"
        t = self.map.get(s.get("session_id"))
        return "code", t or "", t or s.get("title") or s.get("prompt") or "Claude"


# ---- 말풍선 아래 입력창 ------------------------------------------------------
KEY = "#ff00fe"


class InputBox:
    """말풍선 아래 흰 막대에 마우스를 올리면 뜨는 입력창.
    누르면 고정되고, Enter 로 그 대화에 보낸다 (Shift+Enter 는 줄바꿈).
    글이 길어지면 옆으로 밀리지 않고 아래로 한 줄씩 늘어난다 (최대 MAX_LINES 줄, 그 뒤로는 스크롤)."""
    W, H = 252, 40          # 너비, 한 줄일 때 높이 (논리)
    MAX_LINES = 6
    TX = 16                 # 글자 영역 왼쪽 여백 (논리)
    TW = 202                # 글자 영역 너비 (논리)

    def __init__(self, pet):
        import tkinter.font as tkfont
        self.pet = pet
        self.sid = None
        self.pinned = False
        self._outside_since = None
        self.focused = False
        self.drafts = {}
        self.lines = 1
        self._bg_cache = {}
        self.grow_up = False
        self.anchor_y = 0
        # 테두리·그림자는 픽셀 단위 알파 창(fwin)에 그려 흰 화면 위에서도 매끈하게 보이게 한다.
        # 글자를 받는 Tk 창(win)은 색 하나를 투명하게 하는 방식이라 가장자리가 끊겨 보이므로 안쪽 흰 면만 맡는다.
        self.fwin = tk.Toplevel(pet.root)
        self.fwin.overrideredirect(True)
        self.fwin.attributes("-topmost", True)
        self.fwin.geometry("1x1+-32000+-32000")
        self.frame = Layered(self.fwin)
        self._frame_cache = {}
        self._blank = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        self.win = tk.Toplevel(pet.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.wm_attributes("-transparentcolor", KEY)
        self.win.config(bg=KEY)
        self.font = ("Malgun Gothic", 10)
        self._tkfont = tkfont.Font(family="Malgun Gothic", size=10)
        self.lh = self._tkfont.metrics("linespace")          # 한 줄 높이 (화면 픽셀)
        self.cv = tk.Canvas(self.win, width=S(self.W), height=S(self.H), bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack()
        self.bg_item = self.cv.create_image(0, 0, anchor="nw")
        hexc = "#%02x%02x%02x" % C["input"]
        self.hexc = hexc
        self.entry = tk.Text(self.win, height=1, wrap="word", bd=0, relief="flat", padx=0, pady=0,
                             spacing1=0, spacing2=0, spacing3=0, bg=hexc, fg="#1a1a1e",
                             insertbackground="#1a1a1e", insertwidth=2, insertontime=530, insertofftime=530,
                             font=self.font, highlightthickness=0, undo=False)
        self.text_item = self.cv.create_window(S(self.TX), self.text_top(1), window=self.entry, anchor="nw",
                                               width=S(self.TW), height=self.lh)
        # 빈 입력창 안내 글씨
        self.hint = tk.Label(self.win, text="메시지를 기다리고 있어요…", anchor="w", bg=hexc, fg="#a9a9b0",
                             font=self.font, bd=0, padx=0, pady=0, cursor="xterm")
        self.hint_item = self.cv.create_window(S(self.TX), self.text_top(1), window=self.hint, anchor="nw",
                                               width=S(self.TW), height=self.lh)
        self.hint.bind("<Button-1>", self.on_click)
        # 한글 조합 중일 때 조합 글자 뒤에 깜빡이는 커서
        self.comp_caret = tk.Frame(self.win, bg="#1a1a1e", width=2, height=self.lh)
        self.caret_item = self.cv.create_window(0, 0, window=self.comp_caret, anchor="nw", state="hidden")
        self.draw_bg(1)

        e = self.entry
        e.bind("<KeyPress>", self.on_key)
        e.bind("<KeyRelease>", self.on_key_release)
        e.bind("<<Modified>>", self.on_modified)
        e.bind("<Button-1>", self.on_click)
        e.bind("<Return>", self.on_return)
        e.bind("<Escape>", lambda ev: (self.hide(force=True), "break")[1])
        e.bind("<FocusOut>", self.on_focus_out)
        e.bind("<FocusIn>", lambda ev: (setattr(self, "focused", True), self.update_hint()))
        self.cv.bind("<Button-1>", self.on_canvas_click)
        self.win.update_idletasks()
        self._hooks = []
        self.no_ime_popup()
        self.win.withdraw()
        self.visible = False

    # ---- 모양 ----
    def height_px(self, n):
        return S(self.H) + (n - 1) * self.lh

    def text_top(self, n):
        """글자 영역 맨 위 y (화면 픽셀). 한 줄일 때 가운데에 오도록."""
        return (S(self.H) - self.lh) // 2

    def draw_bg(self, n):
        """n 줄 높이의 둥근 입력창 바탕 + 오른쪽 아래 보내기 버튼."""
        from PIL import ImageTk
        if n not in self._bg_cache:
            Wp, Hp = S(self.W), self.height_px(n)
            Wl, Hl = self.W, Hp / SCALE
            big = Image.new("RGBA", (Wp * SS, Hp * SS), (40, 40, 44, 0))
            p = Pen(big)
            r = min(Hl / 2, self.H / 2)
            p.rrect(2, 2, Wl - 2, Hl - 2, r - 1.5, rgba(C["input"]))   # 테두리는 fwin 이 그린다
            bx, by = Wl - 20, Hl - self.H / 2
            p.oval(bx, by, 12, 12, rgba(C["title"]))
            p.line([(bx, by + 5), (bx, by - 5)], 2, (255, 255, 255, 255))
            p.line([(bx - 4.5, by - 0.5), (bx, by - 5), (bx + 4.5, by - 0.5)], 2, (255, 255, 255, 255))
            small = big.resize((Wp, Hp), Image.BOX)   # LANCZOS 는 가장자리에 밝은 테가 생김
            flat = Image.alpha_composite(Image.new("RGBA", (Wp, Hp), C["input"] + (255,)), small)
            mask = small.getchannel("A").point(lambda a: 255 if a > 128 else 0)
            key = Image.new("RGBA", (Wp, Hp), (255, 0, 254, 255))
            key.paste(flat, (0, 0), mask)
            self._bg_cache[n] = ImageTk.PhotoImage(key.convert("RGB"))
        self.cv.itemconfigure(self.bg_item, image=self._bg_cache[n])
        self.send_hit = (S(self.W) - S(34), S(self.W), self.height_px(n) - S(self.H), self.height_px(n))

    SH = 6   # 테두리 창의 그림자 여백 (논리)

    def frame_img(self, n):
        """n 줄 높이 입력창의 테두리 + 흰 바탕 + 옅은 그림자 (알파 창용)."""
        if n not in self._frame_cache:
            Hp = self.height_px(n)
            Wl, Hl, m = self.W, Hp / SCALE, self.SH
            Wt, Ht = S(Wl + 2 * m), Hp + S(2 * m)
            big = Image.new("RGBA", (Wt * SS, Ht * SS), (0, 0, 0, 0))
            r = min(Hl / 2, self.H / 2)
            sh = Image.new("RGBA", big.size, (0, 0, 0, 0))
            Pen(sh).rrect(m, m + 1.5, m + Wl, m + Hl + 1.5, r, (0, 0, 0, 34))
            big.alpha_composite(sh.filter(ImageFilter.GaussianBlur(S(3) * SS)))
            p = Pen(big)
            p.rrect(m, m, m + Wl, m + Hl, r, rgba(C["bubble_line"]))
            p.rrect(m + 1, m + 1, m + Wl - 1, m + Hl - 1, r - 1, rgba(C["input"]))
            self._frame_cache[n] = big.resize((Wt, Ht), Image.LANCZOS)
        return self._frame_cache[n]

    def place(self, x, y):
        """입력창(글자 창)과 그 뒤 테두리 창을 함께 놓는다."""
        Hp = self.height_px(self.lines)
        self.screen_rect = (int(x), int(y), int(x)+S(self.W), int(y)+Hp)
        self.win.geometry(f"{S(self.W)}x{Hp}+{int(x)}+{int(y)}")
        self.frame.show(self.frame_img(self.lines), int(x) - S(self.SH), int(y) - S(self.SH))
        self.frame.topmost()
        self.win.lift()
        if self.pet.menu.open_:
            self.pet.menu.layer.topmost()

    def value(self):
        """입력된 글 (조합 중인 임시 글자는 빼고)."""
        e = self.entry
        rng = e.tag_ranges("comp")
        if rng:
            return e.get("1.0", rng[0]) + e.get(rng[1], "end-1c")
        return e.get("1.0", "end-1c")

    def set_value(self, s):
        self.entry.delete("1.0", "end")
        if s:
            self.entry.insert("1.0", s)
        self.entry.edit_modified(False)
        self.autosize()

    def display_lines(self):
        try:
            self.entry.update_idletasks()
            n = self.entry.count("1.0", "end", "displaylines")
            n = n[0] if isinstance(n, tuple) else n
            return max(1, int(n or 1))
        except Exception:
            return 1

    def autosize(self):
        """글 줄 수에 맞춰 입력창 높이를 바꾼다 (아래로, 말풍선 위에 떠 있으면 위로)."""
        n = min(self.display_lines(), self.MAX_LINES)
        if n == self.lines:
            return
        self.lines = n
        Hp = self.height_px(n)
        self.cv.configure(height=Hp)
        self.cv.itemconfigure(self.text_item, height=n * self.lh)
        self.draw_bg(n)
        if self.visible:
            y = self.anchor_y - Hp if self.grow_up else self.anchor_y
            self.place(self.win.winfo_x(), y)
        self.entry.see("insert")

    # ---- 입력기 ----
    def no_ime_popup(self):
        """이 입력창에서는 Windows 입력기의 '조합 중 글자' 팝업을 띄우지 말라고 알린다.
        (조합 중인 글자는 펫이 입력칸 안에 직접 그린다.) WM_IME_SETCONTEXT 에서
        ISC_SHOWUICOMPOSITIONWINDOW 표시를 지운다."""
        try:
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            user32.CallWindowProcW.restype = LRESULT
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                               ctypes.c_size_t, ctypes.c_ssize_t]
            WM_IME_SETCONTEXT, ISC_SHOWUICOMPOSITIONWINDOW = 0x0281, 0x80000000
            targets = {self.win.winfo_id(), self.entry.winfo_id()}
            try:
                targets.add(user32.GetAncestor(int(self.win.wm_frame(), 16), 2))
            except Exception:
                pass
            hooked = self.__dict__.setdefault("_hooked", set())
            for hwnd in targets:
                if not hwnd or hwnd in hooked:
                    continue
                hooked.add(hwnd)
                holder = {}

                def proc(h, msg, wp, lp, holder=holder):
                    if msg == WM_IME_SETCONTEXT:
                        lp = lp & ~ISC_SHOWUICOMPOSITIONWINDOW
                    elif msg in (0x010D, 0x010E):          # WM_IME_START/ENDCOMPOSITION
                        return 0                            # → 기본 처리기가 조합 상자를 열지 않음
                    elif msg == 0x010F and not (lp & 0x0800):  # WM_IME_COMPOSITION, 확정 글자 없음
                        return 0                            # → 조합 중 글자는 펫이 직접 그림
                    return user32.CallWindowProcW(holder["old"], h, msg, wp, lp)

                cb = WNDPROC(proc)
                holder["old"] = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))
                self._hooks.append(cb)
        except Exception:
            log_error()

    def comp_text(self):
        """한글 입력기가 지금 조합 중인 글자 (없으면 빈 문자열)."""
        try:
            imm = imm32
            hwnd = self.entry.winfo_id()
            ctx = imm.ImmGetContext(hwnd)
            if not ctx:
                return ""
            n = imm.ImmGetCompositionStringW(ctx, 0x0008, None, 0)  # GCS_COMPSTR (바이트 수)
            s = ""
            if n > 0:
                buf = ctypes.create_string_buffer(n + 2)
                imm.ImmGetCompositionStringW(ctx, 0x0008, buf, n)
                s = buf.raw[:n].decode("utf-16-le", "ignore")
            imm.ImmReleaseContext(hwnd, ctx)
            return s
        except Exception:
            return ""

    def caret_xy(self):
        """글자 영역 안 커서 위치 (x, y, h) 화면 픽셀. 맨 끝이면 마지막 글자 바로 뒤."""
        bb = self.entry.bbox("insert")
        if bb:
            return bb[0], bb[1], bb[3]
        bb = self.entry.bbox("insert -1c")
        if bb:
            return bb[0] + bb[2], bb[1], bb[3]
        return 0, 0, self.lh

    def fix_ime(self):
        """입력기에 커서 위치를 알려 준다 (한자 후보창 등이 커서 옆에 뜨도록). 바뀌었을 때만."""
        try:
            xyh = tuple(int(v) for v in self.caret_xy())
            if xyh == getattr(self, "_last_caret", None):
                return
            self._last_caret = xyh
            self.entry.tk.call("tk", "caret", self.entry._w, "-x", xyh[0], "-y", xyh[1], "-height", xyh[2])
        except Exception:
            log_error()

    def sync_caret(self, s=None):
        """한글 조합 중: Tk 커서(조합 글자 '앞'에 남음)는 숨기고, 조합 글자를 확정 글자 바로 뒤에 그리고,
        그 뒤에 깜빡이는 커서를 둔다. 확정되면 원래 커서로 돌아간다. (s: 이미 읽은 조합 글자)"""
        if s is None:
            s = self.comp_text()
        comp = bool(s)
        want = self.hexc if comp else "#1a1a1e"
        if getattr(self, "_caret_col", "#1a1a1e") != want:
            self._caret_col = want
            self.entry.configure(insertbackground=want)
        # 조합 중인 글자를 입력칸 안에 '임시 글자'(comp 표시)로 직접 넣어 둔다.
        # 별도 라벨로 그리면 글꼴 다듬기(안티에일리어싱)가 달라 굵기·번짐이 달라 보였다.
        # 임시 글자는 커서 '뒤'에 두므로, 확정된 글자는 그 앞(커서 자리)에 들어가고 임시 글자는 곧 지워진다.
        e = self.entry
        rng = e.tag_ranges("comp")
        shown = e.get(rng[0], rng[1]) if rng else ""
        if shown != s:
            self._guard = True
            try:
                if rng:
                    e.delete(rng[0], rng[1])
                if s:
                    at = e.index("insert")
                    e.insert(at, s, ("comp",))
                    e.mark_set("insert", at)
                e.edit_modified(False)
            finally:
                self._guard = False
            self.autosize()
        if not comp:
            self.cv.itemconfigure(self.caret_item, state="hidden")
            return
        # 깜빡이는 커서는 임시 글자 바로 뒤에
        rng = e.tag_ranges("comp")
        bb = e.bbox(f"{rng[1]} -1c") if rng else None
        if not bb:
            self.cv.itemconfigure(self.caret_item, state="hidden")
            return
        x, y = bb[0] + bb[2], bb[1]
        self.cv.coords(self.caret_item, S(self.TX) + x + 1, self.text_top(self.lines) + y)
        on = int(time.time() * 1000 / 530) % 2 == 0
        self.cv.itemconfigure(self.caret_item, state="normal" if on else "hidden")

    # ---- 안내 글씨 · 키 ----
    def update_hint(self, typing=False):
        show = not self.value() and not typing and not self.focused
        self.cv.itemconfigure(self.hint_item, state="normal" if show else "hidden")

    def on_key(self, e):
        if e.keysym in ("Return", "Escape", "Shift_L", "Shift_R", "Control_L", "Control_R", "Tab"):
            return
        self.update_hint(typing=True)

    def on_key_release(self, e):
        self.fix_ime()
        self.sync_caret()
        self.autosize()
        if e.keysym in ("BackSpace", "Delete") or self.value():
            self.update_hint()

    def on_modified(self, e=None):
        """글이 바뀐 그 순간 (한글 글자 확정 포함) 조합 라벨 정리 + 높이 조절."""
        if not self.entry.edit_modified():
            return
        self.entry.edit_modified(False)
        if getattr(self, "_guard", False):
            return  # 임시 조합 글자를 넣고 뺀 것 → 무시
        self.sync_caret()
        self.autosize()

    def on_return(self, e):
        if e.state & 0x0001:          # Shift+Enter: 줄바꿈
            return None
        self.send()
        return "break"

    def watch_hint(self):
        """입력창이 떠 있는 동안 상태를 계속 맞춘다 (키 이벤트가 안 오는 한글 조합도 잡음)."""
        self._stop_watch()
        if not self.visible:
            return
        s = self.comp_text()   # 한 틱에 한 번만 입력기에 묻는다
        if self.focused:
            self.fix_ime()
        self.sync_caret(s)
        self.update_hint(typing=bool(s))
        self._watch_id = self.win.after(40 if self.focused else 120, self.watch_hint)

    def _stop_watch(self):
        """감시 타이머는 하나만 돌게 (숨겼다 금방 다시 띄워도 겹치지 않음)."""
        if getattr(self, "_watch_id", None):
            try:
                self.win.after_cancel(self._watch_id)
            except Exception:
                pass
            self._watch_id = None

    # ---- 보이기 · 숨기기 ----
    def show_for(self, sid, sx, sy, top=None):
        """sy: 말풍선 바로 아래 y, top: 말풍선 바로 위 y (아래가 화면 밖일 때 위로 띄우고 위로 자람)."""
        if self.pinned and sid != self.sid:
            return
        if sid != self.sid:
            if self.sid:
                self.drafts[self.sid] = self.value()
            self.sid = sid
            self.set_value(self.drafts.get(sid, ""))
        l, t, r, b = work_area((sx, sy))
        x = min(max(sx, l), r - S(self.W))
        Hp = self.height_px(self.lines)
        self.grow_up = not (sy + Hp <= b or top is None)
        self.anchor_y = top if self.grow_up else sy
        y = self.anchor_y - Hp if self.grow_up else self.anchor_y
        if not self.visible:
            self.win.geometry(f"{S(self.W)}x{Hp}+{int(x)}+{int(y)}")
            self.win.deiconify()
            self.visible = True
            self.win.update_idletasks()
            self.no_ime_popup()
            self.watch_hint()
        self.place(x, y)
        self.update_hint()

    def check_auto_hide(self, now=None, pointer=None):
        """Unclicked previews follow actual cursor geometry, never stale hover/focus events."""
        if not self.visible or self.pinned:
            self._outside_since = None
            return
        if pointer is None:
            pt = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(pt)):
                return
            pointer = (pt.x, pt.y)
        now = time.monotonic() if now is None else now
        x,y = pointer
        left,top,right,bottom = self.screen_rect
        over_input = left <= x < right and top <= y < bottom
        if over_input or self.pet.input_anchor_contains(pointer, self.sid):
            self._outside_since = None
        elif self._outside_since is None:
            self._outside_since = now
        elif now-self._outside_since >= 0.6:
            self.hide()

    def on_focus_out(self, e=None):
        """다른 곳을 누르면 고정을 풀고 (쓰던 글은 대화별로 기억), 마우스가 없으면 닫힌다.
        입력창 안 작은 부품 때문에 생기는 가짜 신호는 잠깐 뒤 다시 확인해서 걸러낸다."""
        self.win.after(150, self._confirm_focus_out)

    def has_focus(self):
        try:
            fg = user32.GetForegroundWindow()
            mine = {self.win.winfo_id(), self.entry.winfo_id(),
                    user32.GetAncestor(int(self.win.wm_frame(), 16), 2)}
            if fg:
                return fg in mine or user32.GetAncestor(fg, 2) in mine
        except Exception:
            pass
        try:
            focused = self.win.focus_get()
            return focused is not None and focused.winfo_toplevel() == self.win
        except Exception:
            return False

    def _confirm_focus_out(self):
        if self.has_focus():
            return
        if self.sid:
            self.drafts[self.sid] = self.value()
        self.pinned = False
        self.focused = False
        self.update_hint()

    def on_canvas_click(self, e):
        x0, x1, y0, y1 = self.send_hit
        if x0 <= e.x <= x1 and y0 <= e.y <= y1:
            self.send()
        else:
            self.on_click(e)

    def on_click(self, e=None):
        self.pinned = True
        self.focused = True
        self.update_hint()
        try:
            hwnd = user32.GetAncestor(int(self.win.wm_frame(), 16), 2)
            if not user32.SetForegroundWindow(hwnd):
                fg = user32.GetForegroundWindow()
                t_fg = user32.GetWindowThreadProcessId(fg, None)
                t_me = ctypes.windll.kernel32.GetCurrentThreadId()
                user32.AttachThreadInput(t_me, t_fg, True)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(t_me, t_fg, False)
        except Exception:
            log_error()
        self.win.focus_force()
        self.entry.focus_force()
        if e is None or e.widget is not self.entry:
            self.entry.mark_set("insert", "end-1c")

    def send(self):
        text = self.value().strip()
        if not text or not self.sid:
            return
        self.pet.send_to(self.sid, text)
        self.drafts.pop(self.sid, None)
        self.set_value("")
        self.hide(force=True)

    def hide(self, force=False):
        if self.pinned and not force:
            return
        self._stop_watch()
        self.pinned = False
        self.focused = False
        self._outside_since = None
        self.sid = None
        if self.visible:
            self.win.withdraw()
            self.frame.show(self._blank, -32000, -32000)
            self.visible = False


# ---- 펫 + 말풍선 창 -------------------------------------------------------
class Pet:
    """픽셀 펫 한 마리 + 사방(왼쪽 위·오른쪽 위·왼쪽·오른쪽·왼쪽 아래·오른쪽 아래)에 대화별 말풍선."""
    BW = 252          # 말풍선 너비
    BH = 92           # 말풍선 칸 높이
    G = 10            # 펫과 말풍선 사이
    M = 12            # 창 가장자리 여유
    PANEL_W, PANEL_H = 204, 58   # 펫 밑 막대에 올리면 뜨는 판 (새 대화 버튼 + 사용량)
    SLOTS = ("TL", "TR", "L", "R", "BL", "BR")

    def __init__(self):
        self.conf = load_conf()
        self.conf.setdefault("bubble", True)
        self.conf.setdefault("auto_transparency", True)
        self.text_watcher=None
        self._text_behind=set()
        self._text_scan_at=0
        self._text_region_key=None
        self._opacity_area=None
        self._hover_area=None
        self._render_profiles={}
        fc = self.conf.get("fc") or round(int(self.conf.get("pix", 4)) / 2)
        self.pix = round(min(max(float(fc), PIX_MIN), PIX_MAX), 2)
        set_skin(self.conf.get("skin"))
        self.root = tk.Tk()
        self.root.title("Claude Pet")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        pc = self.conf.get("pc")
        l, t, r, b = work_area(pc)   # 저장된 위치가 있는 모니터 기준으로만 화면 안에 맞춘다
        pc = pc or [r - S(80), b - S(80)]
        self.pc = [min(max(pc[0], l + S(40)), r - S(40)), min(max(pc[1], t + S(60)), b - S(40))]
        self.root.geometry(f"10x10+{self.pc[0]}+{self.pc[1]}")
        self.layer = Layered(self.root)
        self.menu = Menu(self.root)
        self.titles = AppTitles()
        self.input = InputBox(self)

        self.sessions = []
        self.completions = CompletionState(self.conf.get("completion_notifications"))
        self.celebrate_since = time.time() if self.completions.pending else 0.0
        self.hover_pet_until = 0.0
        self.hover_since = None
        self.hover_bubble = None
        self.hover_x = None
        self.hover_nc = False
        self.hover_ul = False
        self.ulink_rect = None   # 판 안 '사용량 탭 열기' 글자 버튼 자리
        self.sync_c = None       # 판 왼쪽 위 동기화 버튼 (가운데 x, y)
        self.hover_sync = False
        self.syncing = False
        self._sync_last = 0.0
        self._sync_manual = False
        self._sync_result = None
        self.usage = None
        self.hover_bar = None
        self.pet_hover = False
        self.bar_rects = []
        self.next_blink = time.time() + 3
        self.bubble_cache = {}
        self.bubble_rects = []
        self._frame_key = None
        self._drag = None
        self._drag_xy = None
        self._drag_pending = False
        self._moved = False
        self.t0 = time.time()
        self.geom()

        self.displays = MirroredPets(self, enumerate_work_areas, work_area, Layered, S)

        self.poll()
        self.animate()
        self.keep_on_top()
        if __name__ == "__main__":
            self.root.after(200, self.poll_tray_command)
            global _shell_priority
            _shell_priority = ShellPriority()
            self.poll_shell_priority()
            from tray_host import notify, READY
            notify(READY)

    # ---- 배치 ----
    def geom(self):
        f = self.pix * SCALE * getattr(pixelpet, "render_scale", 1.0)
        self.f = f
        gx, gy = pixelpet.center()
        u = f / SCALE                                   # 한 칸의 논리 크기
        self.spr_off = (gx * u, gy * u)                 # 스프라이트 왼쪽 위 → 몸통 중심
        self.pet_margins=(S(gx*u+4),S(gy*u+4),
                          S((pixelpet.GW-gx)*u+4),S((pixelpet.GH-gy)*u+10))
        self.pw = max(gx, pixelpet.GW - gx) * u
        self.ptop = gy * u
        self.pbot = (pixelpet.GH - gy) * u + 12 + self.PANEL_H + 4
        side = self.pw + self.G + self.BW
        self.cx = self.M + side
        self.cy = self.M + self.BH + 4 + self.ptop
        self.W = 2 * side + 2 * self.M
        self.H = self.cy + self.pbot + 4 + self.BH + self.M
        self.Wp, self.Hp = S(self.W), S(self.H)
        cx, cy, BW, BH = self.cx, self.cy, self.BW, self.BH
        top_y1 = cy - self.ptop - 30
        bot_y0 = cy + self.pbot + 2
        self.slot_box = {
            "TL": (cx - 12 - BW, top_y1 - BH, cx - 12, top_y1, "bottom"),
            "TR": (cx + 12, top_y1 - BH, cx + 12 + BW, top_y1, "bottom"),
            "L": (cx - self.pw - self.G - 16 - BW, cy - BH / 2, cx - self.pw - self.G - 16, cy + BH / 2, "middle"),
            "R": (cx + self.pw + self.G + 16, cy - BH / 2, cx + self.pw + self.G + 16 + BW, cy + BH / 2, "middle"),
            "BL": (cx - 12 - BW, bot_y0, cx - 12, bot_y0 + BH, "top"),
            "BR": (cx + 12, bot_y0, cx + 12 + BW, bot_y0 + BH, "top"),
        }
        # 펫 아래 흰 막대 → 그 아래 판 (새 대화 버튼 + 사용량)
        self.petbar_y = cy + (pixelpet.GH - gy) * u + 2
        py0 = self.petbar_y + 8
        self.tb_rect = (cx - self.PANEL_W / 2, py0, cx + self.PANEL_W / 2, py0 + self.PANEL_H)
        bx = self.tb_rect[0] + 24
        self.nc_rect = (bx - 16, py0 + 7, bx + 16, py0 + self.PANEL_H - 7)   # 새 대화 버튼
        self.x, self.y = self.pc[0] - S(cx), self.pc[1] - S(cy)
        self._preferred_slots = {k: (a-cx, b-cy, c-cx, d-cy, align)
                                 for k, (a,b,c,d,align) in self.slot_box.items()}
        self._bar_offset = self.petbar_y - cy
        self._layout_signature = None
        self._layout_request = None

    def on_position_clamped(self):
        self.conf["pc"]=list(self.pc)
        if not self._drag:save_conf(self.conf)

    def overlay_layout(self):
        """Use the intersection of every displayed monitor's visible pet-relative area."""
        anchor = work_area(self.pc)
        displays = getattr(self, "displays", None)
        areas = (displays.areas or [anchor]) if displays and self.conf.get("all_monitors") else [anchor]
        request=(tuple(self.pc),self.pix,id(pixelpet),
                 tuple((s["session_id"],s["_state"]) for s in self.sessions),
                 tuple(sorted(self.conf.get("slots",{}).items())),self.toolbar_visible(),tuple(areas),
                 tuple(bubble_geometry(self.conf,s["session_id"],s["_state"]) for s in self.sessions))
        if request == getattr(self,"_layout_request",None):
            return False
        visible = []
        for area in areas:
            center = corresponding_center(self.pc, anchor, area)
            visible.append(((area[0]-center[0])/SCALE, (area[1]-center[1])/SCALE,
                            (area[2]-center[0])/SCALE, (area[3]-center[1])/SCALE))
        bounds = (max(r[0] for r in visible)+2, max(r[1] for r in visible)+2,
                  min(r[2] for r in visible)-2, min(r[3] for r in visible)-2)
        pet = (-self.pw-6, -self.ptop-8, self.pw+6, self._bar_offset-4)
        panel = place_panel(bounds, pet, self._bar_offset, (self.PANEL_W,self.PANEL_H))
        entries=[]
        for session, slot in self.assign_slots():
            x0,y0,x1,y1,align=self._preferred_slots[slot]
            width,h,_,_,_=bubble_geometry(self.conf,session["session_id"],session["_state"],self.BW)
            if slot in ("TL","L","BL"):x0=x1-width
            else:x1=x0+width
            y=y1-h if align=="bottom" else (y0 if align=="top" else (y0+y1-h)/2)
            entries.append((session["session_id"],width,h,(x0,y,x1,y+h)))
        panel_visible=self.toolbar_visible()
        obstacles=[pet]
        if panel_visible:
            obstacles.append((panel[0]-10,panel[1]-10,panel[2]+10,panel[3]+10))
        boxes=arrange_bubbles(entries,getattr(self,"_bubble_offsets",{}),bounds,obstacles)
        self._bubble_offsets=boxes
        rects=list(boxes.values())+[pet]+([panel] if panel_visible else [])
        # Resize the transparent canvas around the actual overlays, including upward stacks.
        left=min(r[0] for r in rects)-18;top=min(r[1] for r in rects)-18
        right=max(r[2] for r in rects)+18;bottom=max(r[3] for r in rects)+22
        signature=(tuple(sorted(boxes.items())),panel if panel_visible else None,round(left,3),round(top,3),round(right,3),round(bottom,3))
        changed=signature!=self._layout_signature
        self._layout_signature=signature
        self.cx,self.cy=-left,-top
        self.W,self.H=right-left,bottom-top
        self.Wp,self.Hp=S(self.W),S(self.H)
        self.x,self.y=self.pc[0]-S(self.cx),self.pc[1]-S(self.cy)
        self.slot_box={k:(a+self.cx,b+self.cy,c+self.cx,d+self.cy,align)
                       for k,(a,b,c,d,align) in self._preferred_slots.items()}
        self._bubble_boxes={sid:(a+self.cx,b+self.cy,c+self.cx,d+self.cy)
                            for sid,(a,b,c,d) in boxes.items()}
        self.petbar_y=self.cy+self._bar_offset
        self.tb_rect=tuple(v+(self.cx if i%2==0 else self.cy) for i,v in enumerate(panel))
        x0,y0,x1,y1=self.tb_rect
        self.nc_rect=(x0+8,y0+7,x0+40,y1-7)
        self._layout_request=request
        return changed

    def assign_slots(self):
        """대화별 기본 슬롯을 유지한다. 실제 화면 경계 회피는 overlay_layout에서 처리한다.
        새 대화는 화면 안의 빈자리부터, 급한 대화가 먼저 고른다. 기본 슬롯은 설정에 저장."""
        slots = self.conf.setdefault("slots", {})
        live = {s["session_id"] for s in self.sessions}
        gone = self.__dict__.setdefault("_gone_since", {})
        now = time.time()
        changed = False
        for sid in list(slots):
            if sid in live:
                gone.pop(sid, None)
                continue
            # 파일을 한 번 못 읽은 정도로 자리를 잃지 않게, 10초 넘게 안 보일 때만 비운다
            if slots[sid] not in self.SLOTS or now - gone.setdefault(sid, now) > 10:
                del slots[sid]
                gone.pop(sid, None)
                changed = True
        order = self.slot_order()
        for s in reversed(self.sessions):  # 급한 대화부터 빈자리 배정
            sid = s["session_id"]
            if sid not in slots:
                free = [n for n in order if n not in slots.values()]
                if not free:
                    continue
                slots[sid] = free[0]
                changed = True
        if changed:
            save_conf(self.conf)
        return [(s, slots[s["session_id"]]) for s in self.sessions if s["session_id"] in slots]

    def slot_order(self):
        l, t, r, b = work_area(self.pc)
        ok, bad = [], []
        for name in self.SLOTS:
            x0, y0, x1, y1, _ = self.slot_box[name]
            sx0, sy0, sx1, sy1 = self.x + S(x0), self.y + S(y0), self.x + S(x1), self.y + S(y1)
            (ok if (sx0 >= l and sy0 >= t and sx1 <= r and sy1 <= b) else bad).append(name)
        return ok + bad

    # ---- 상태 ----
    def poll(self):
        try:
            if not hasattr(self, "cowork"):
                self.cowork, self.chat = CoworkWatcher(), ChatWatcher()
            self.cowork.poll()
            self.chat.poll()
            self.titles.refresh()
            if learn_usage(self.conf, self.chat.latest):
                save_conf(self.conf)
            r = self._sync_result
            if r is not None:   # 동기화 끝
                self._sync_result = None
                self.syncing = False
                if r.get("ok"):
                    apply_usage_sync(self.conf, r)
                    save_conf(self.conf)
                elif self._sync_manual:   # Code 화면이 아니라 버튼이 없으면: 설정 > 사용량 탭을 연다
                    run_ui("usage")
            self.usage = usage_view(read_usage(), self.conf.get("resets"))
        except Exception:
            log_error()
        try:
            all_sessions = read_sessions(limit=None)
            self.sessions = all_sessions[-MAX_BUBBLES:]
            previous_pending = dict(self.completions.pending)
            if self.completions.update(all_sessions):
                if any(previous_pending.get(sid) != token for sid, token in self.completions.pending.items()):
                    self.celebrate_since = time.time()
                self.save_completions()
            live = {s["session_id"] for s in self.sessions}
            for sid in list(self.bubble_cache):
                if sid not in live:
                    del self.bubble_cache[sid]
                    getattr(self,"_bubble_body_cache",{}).pop(sid,None)
                    for variant in list(getattr(self,"_bubble_variants",{})):
                        if variant[0]==sid:self._bubble_variants.pop(variant,None)
        except Exception:
            log_error()
        # 입력창: 말풍선·입력창 둘 다에서 벗어나면 닫기 (고정된 건 유지)
        try:
            self.input.check_auto_hide()
            self.poll_text_behind()
        except Exception:
            log_error()
        self.root.after(250, self.poll)

    def toggle_auto_transparency(self, sid=None):
        if sid is not None:
            options=self.conf.setdefault("bubble_overrides",{}).setdefault(sid,{})
            options["auto_transparency"]=not opacity_options(self.conf,sid)[1]
            save_conf(self.conf)
            self._text_scan_at=0
            self.invalidate_bubble(sid)
            return
        self.conf["auto_transparency"]=not self.conf.get("auto_transparency",True)
        save_conf(self.conf)
        self._text_behind.clear()
        self._text_scan_at=0
        self._frame_key=None
        self.draw_now()

    def stop_text_detection(self):
        if self.text_watcher:
            self.text_watcher.stop()
            self.text_watcher=None
        if self._text_behind:
            self._text_behind.clear()
            self._frame_key=None
        self._text_region_key=None
        self._text_scan_at=0

    def poll_text_behind(self):
        if not any(opacity_options(self.conf,s["session_id"])[1] for s in self.sessions) or not self.conf["bubble"]:
            self.stop_text_detection()
            return
        if self._drag and self._moved:
            return
        regions=[]
        identities={}
        views=[self.displays.root_view]+list(self.displays.mirrors.values())
        for view in views:
            ox,oy=view.origin
            for x,y,r,b,sid in self.bubble_rects:
                if not opacity_options(self.conf,sid)[1]:continue
                rect=[ox+S(x),oy+S(y),ox+S(r),oy+S(b)]
                if self.conf.get("all_monitors"):
                    l,t,rr,bb=view.area
                    rect=[max(l,rect[0]),max(t,rect[1]),min(rr,rect[2]),min(bb,rect[3])]
                if rect[2]>rect[0] and rect[3]>rect[1]:
                    token=','.join(map(str,view.area))+'|'+sid
                    identities[token]=(tuple(view.area),sid)
                    regions.append({"id":token,"rect":rect})
        key=tuple((r["id"],tuple(r["rect"])) for r in regions)
        if key!=self._text_region_key:
            self._text_region_key=key
            self._text_behind.clear();self._frame_key=None;self._text_scan_at=0
        if not regions:
            self.stop_text_detection()
            return
        if self.text_watcher is None:self.text_watcher=TextBehindWatcher()
        result=self.text_watcher.result()
        detected={identities[token] for token in result[1] if token in identities} if result and result[0]==key else set()
        if detected!=self._text_behind:
            self._text_behind=set(detected);self._frame_key=None
        now=time.monotonic()
        if now>=self._text_scan_at:
            self.text_watcher.submit(key,regions)
            self._text_scan_at=now+1.4

    def pet_state(self):
        # Continue showing active work through the signature light, even while celebrating another room.
        active = [s["_state"] for s in self.sessions if s["_state"] in ("working", "waiting")]
        if active:
            return max(active, key=PRIORITY.get)
        return "done" if self.completions.pending else "idle"

    def save_completions(self):
        self.conf["completion_notifications"] = self.completions.snapshot()
        save_conf(self.conf)
        self._frame_key = None

    def acknowledge_completion(self, sid=None):
        if self.completions.acknowledge(sid):
            if not self.completions.pending:
                self.celebrate_since = 0.0
            self.save_completions()

    def session(self, sid):
        return next((s for s in self.sessions if s["session_id"] == sid), None)

    # ---- 조작 ----
    def lpos(self, e):
        return e.x / SCALE, e.y / SCALE

    def hit(self, x, y):
        """(종류, sid): 'x' 닫기, 'bar' 입력 막대, 'bubble', 'toolbar', 'pet' 또는 (None, None)."""
        for bx, byy, sid in self.bar_rects:
            if abs(x - bx) <= 22 and byy - 7 <= y <= byy + 8:
                return "bar", sid
        for x0, y0, x1, y1, sid in self.bubble_rects:
            if x1 - 24 <= x <= x1 + 6 and y0 - 6 <= y <= y0 + 20:
                return "x", sid
            if x0 <= x <= x1 and y0 <= y <= y1:
                return "bubble", sid
        if abs(x - self.cx) <= 22 and self.petbar_y - 7 <= y <= self.petbar_y + 7:
            return "petbar", None
        tx0, ty0, tx1, ty1 = self.tb_rect
        if self.toolbar_visible() and tx0 <= x <= tx1 and ty0 - 9 <= y <= ty1:
            if self.sync_c and math.hypot(x - self.sync_c[0], y - self.sync_c[1]) <= 9:
                return "sync", None
            n0, n1, n2, n3 = self.nc_rect
            if n0 <= x <= n2 and n1 <= y <= n3:
                return "newchat", None
            u = self.ulink_rect
            if u and u[0] - 3 <= x <= u[2] + 3 and u[1] - 3 <= y <= u[3] + 3:
                return "usagetab", None
            return "panel", None
        if abs(x - self.cx) <= self.pw and self.cy - self.ptop <= y < self.petbar_y - 7:
            return "pet", None
        return None, None

    def input_anchor_contains(self, pointer, sid):
        """The matching white handle on any visible monitor keeps its preview open."""
        if not self.conf["bubble"]:
            return False
        px,py = pointer
        views = [self.displays.root_view] + list(self.displays.mirrors.values())
        for view in views:
            if self.conf.get("all_monitors"):
                l,t,r,b = view.area
                if not (l <= px < r and t <= py < b):
                    continue
            ox,oy = view.origin
            for bx,by,bar_sid in self.bar_rects:
                if bar_sid == sid and abs(px-(ox+S(bx))) <= S(22) and oy+S(by-7) <= py <= oy+S(by+8):
                    return True
        return False

    def sync_usage(self, manual=False):
        """사용량 동기화 (판이 열릴 때 자동: 30초에 한 번까지, 버튼: 바로). 결과는 poll 이 반영."""
        now = time.time()
        if self.syncing or (not manual and now - self._sync_last < 30):
            return
        self.syncing, self._sync_last, self._sync_manual = True, now, manual
        threading.Thread(target=lambda: setattr(self, "_sync_result", run_usage_sync()), daemon=True).start()

    def toolbar_visible(self):
        return self.pet_hover or time.time() < self.hover_pet_until

    def on_motion(self, e):
        kind, sid = self.hit(*self.lpos(e))
        now = time.time()
        on_panel = kind in ("petbar", "panel", "newchat", "usagetab", "sync")   # 판은 펫 밑 막대에서만 열린다
        if on_panel and not self.toolbar_visible():
            self.sync_usage()   # 판이 열릴 때 최신 사용량으로
        if self.pet_hover and not on_panel:
            self.hover_pet_until = now + 0.8   # 막대에서 판으로 옮겨갈 여유
        self.pet_hover = on_panel
        if kind == "pet":
            if self.hover_since is None:
                self.hover_since = now
        else:
            self.hover_since = None
        self.hover_nc = kind == "newchat"
        self.hover_ul = kind == "usagetab"
        self.hover_sync = kind == "sync"
        self.hover_x = sid if kind == "x" else None
        self.hover_bubble = sid if kind in ("bubble", "x") else None
        self._hover_area=tuple(self.displays.event_area) if self.hover_bubble else None
        new_bar = sid if kind == "bar" else None
        self.hover_bar = new_bar
        self.root.config(cursor="hand2" if kind in ("x", "newchat", "usagetab", "sync", "bubble", "bar", "petbar") else "")
        if new_bar and not self._drag:   # 흰 막대에 올렸을 때만 입력창
            r = next(r for r in self.bubble_rects if r[4] == new_bar)
            # 말풍선 바로 아래 (막대 자리), 화면 밑이 모자라면 말풍선 바로 위
            ox, oy = self.displays.event_origin or (self.x, self.y)
            self.input.show_for(new_bar, ox + S(r[0]), oy + S(r[3] + 3), oy + S(r[1] - 3))

    def on_leave(self, e):
        if self.pet_hover:
            self.hover_pet_until = time.time() + 0.8
        self.pet_hover = False
        self.hover_bar = None
        self.hover_since = None
        self.hover_bubble = None
        self.hover_x = None
        self.hover_nc = False
        self.hover_ul = False
        self.hover_sync = False

    def on_press(self, e):
        self._drag_source_area = self.displays.event_area
        self._drag = (e.x_root, e.y_root, list(self.pc))
        self._drag_pending = False
        self._moved = False

    def on_drag(self, e):
        if not self._drag:
            return
        sx, sy, _ = self._drag
        if abs(e.x_root - sx) + abs(e.y_root - sy) > S(4):
            self.pet_hover = False
            self.hover_pet_until = 0.0
            self._moved = True
            if self.input.visible and not self.input.pinned:
                self.input.hide()
        if not self._moved:
            return
        self._drag_xy = (e.x_root, e.y_root)
        if not self._drag_pending:
            self._drag_pending = True
            self.root.after(8, self._apply_drag)

    def _apply_drag(self):
        self._drag_pending = False
        if not self._drag or not self._drag_xy:
            return
        sx, sy, pc = self._drag
        xr, yr = self._drag_xy
        self.pc = self.displays.drag_center(pc, xr - sx, yr - sy)
        self.x, self.y = self.pc[0] - S(self.cx), self.pc[1] - S(self.cy)
        if self.overlay_layout():
            self.draw_now()
        else:
            self.displays.present(moving=True)

    def on_release(self, e):
        moved = self._moved
        if self._drag and self._drag_xy:
            self._apply_drag()
        self._drag = None
        self._drag_xy = None
        if moved:
            self._frame_key = None
            self.conf["pc"] = self.pc
            save_conf(self.conf)
            return
        kind, sid = self.hit(*self.lpos(e))   # 끌지 않았으면 클릭
        try:
            if kind == "x":
                self.dismiss(sid)
            elif kind == "bubble":
                self.open_session(sid)
            elif kind == "newchat":
                self.new_chat()
            elif kind == "sync":
                self.sync_usage(manual=True)
            elif kind == "usagetab":
                run_ui("usage")   # 설정 > 사용량 탭을 열면 감시 도우미가 리셋 시각을 읽어 기억한다
            elif kind == "pet":
                if self.completions.pending:
                    self.acknowledge_completion()
                    self.draw_now()
                else:
                    focus_claude_window()
        except Exception:
            log_error()

    def open_session(self, sid):
        s = self.session(sid)
        if s:
            mode, title, _ = self.titles.target(s)
            run_ui("open", mode, title)
            self.acknowledge_completion(sid)

    def send_to(self, sid, text):
        s = self.session(sid)
        if s:
            mode, title, _ = self.titles.target(s)
            run_ui("send", mode, title, text=text)
            self.acknowledge_completion(sid)

    def new_chat(self):
        active = ((getattr(self, "chat", None) and self.chat.latest) or {}).get("active") or "code"
        run_ui("new", "chat" if active == "chat" else "code")

    def on_right(self, e):
        try:
            kind, sid = self.hit(*self.lpos(e))
            sid = sid if kind in ("bubble", "x", "bar") else None
            if sid:
                self.menu.popup(e.x_root,e.y_root,lambda:self.bubble_menu_items(sid),"말풍선 설정","이 대화에만 적용")
            else:
                self.menu.popup(e.x_root,e.y_root,lambda:self.menu_items(None))
        except Exception:
            log_error()

    def invalidate_bubble(self, sid, geometry=False):
        self.bubble_cache.pop(sid,None)
        if geometry:
            getattr(self,"_bubble_body_cache",{}).pop(sid,None)
            self._layout_request=None
        variants=getattr(self,"_bubble_variants",{})
        for key in list(variants):
            if key[0]==sid:variants.pop(key,None)
        self._render_profiles={}
        self._static=None
        self._frame_key=None
        self.draw_now()

    def adjust_bubble(self, sid, field, step):
        options=self.conf.setdefault("bubble_overrides",{}).setdefault(sid,{})
        upper=1.8 if field=="scale" else 1.6
        value=round(max(.8,min(upper,float(options.get(field,1))+step*.1)),1)
        if value==options.get(field,1):return
        options[field]=value
        save_conf(self.conf)
        self.invalidate_bubble(sid,geometry=True)

    def bubble_menu_items(self, sid):
        options=room_options(self.conf,sid)
        size=float(options.get("scale",1));font_size=float(options.get("font_scale",1))
        return [
            ("말풍선 크기",None,False,False,{"section":True,"disabled":True,"value":f"{size:.0%}"}),
            ("말풍선 크게",lambda:self.adjust_bubble(sid,"scale",1),False,True,{"icon":"plus","disabled":size>=1.8}),
            ("말풍선 작게",lambda:self.adjust_bubble(sid,"scale",-1),False,True,{"icon":"minus","disabled":size<=.8}),
            None,
            ("폰트 크기",None,False,False,{"section":True,"disabled":True,"value":f"{font_size:.0%}"}),
            ("폰트 크게",lambda:self.adjust_bubble(sid,"font_scale",1),False,True,{"icon":"plus","disabled":font_size>=1.6}),
            ("폰트 작게",lambda:self.adjust_bubble(sid,"font_scale",-1),False,True,{"icon":"minus","disabled":font_size<=.8}),
            None,
            ("말풍선 투명도",lambda:self.menu.navigate(lambda:self.transparency_menu_items(sid),"말풍선 투명도"),
             False,True,{"icon":"bubble","arrow":True}),
        ]

    def menu_items(self, sid):
        section=lambda title:(title,None,False,True,{"section":True})
        items = [section("작업"),
            ("Claude 창 열기",focus_claude_window,False,False,{"icon":"open"}),
            ("새 대화 시작",self.new_chat,False,False,{"icon":"new"})]
        if self.completions.pending:
            items.append((f"완료 {len(self.completions.pending)}건 확인",self.acknowledge_completion,False,False,{"icon":"check"}))
        items += [section("펫"),
            ("펫 변경",lambda:self.menu.navigate(lambda:self.skin_menu_items(sid),"펫 변경","함께할 캐릭터를 선택하세요"),False,True,{"icon":"pet","arrow":True}),
            ("펫 크기",lambda:self.menu.navigate(self.pet_size_menu_items,"펫 크기","조금씩 크기를 조절하세요"),False,True,{"icon":"size","arrow":True,"value":f"{self.pix*100:.0f}%"}),
            ("모든 화면 표시 해제" if self.conf.get("all_monitors") else "모든 화면에 표시",self.toggle_all_monitors,False,False,{"icon":"screens"}),
            section("말풍선"),
            ("말풍선 모두 숨기기" if self.conf["bubble"] else "말풍선 보이기",self.toggle_bubble,False,False,{"icon":"bubble"}),
            ("말풍선 투명도",lambda:self.menu.navigate(lambda:self.transparency_menu_items(None),"말풍선 투명도"),False,True,{"icon":"bubble","arrow":True}),
        ]
        if sid:items.append(("이 말풍선 숨기기",lambda:self.dismiss(sid),False,False,{"icon":"bubble"}))
        items += [section("실행 설정"),
            ("자동 실행",self.open_autorun_menu,False,True,{"icon":"clock","arrow":True,"value":autorun_summary(BASE)}),
            ("업데이트",self.open_update_menu,False,False,{"icon":"clock","arrow":True}),
            None,("펫 숨기기",self.quit,True,False,{"icon":"power"})]
        return items

    def pet_size_menu_items(self):
        return [
            ("뒤로",lambda:self.menu.navigate(lambda:self.menu_items(None)),False,True,{"icon":"back"}),None,
            ("현재 크기",None,False,True,{"section":True,"value":f"{self.pix*100:.0f}%"}),
            ("조금 더 크게",lambda:self.resize(1),False,True,{"icon":"plus","disabled":self.pix>=PIX_MAX}),
            ("조금 더 작게",lambda:self.resize(-1),False,True,{"icon":"minus","disabled":self.pix<=PIX_MIN}),
        ]

    def open_update_menu(self):
        from tray_host import notify,OPEN_UPDATES
        notify(OPEN_UPDATES)

    def open_autorun_menu(self):
        self.menu.navigate(lambda:autorun_menu_items(BASE,
            lambda:self.menu.navigate(lambda:self.menu_items(None)),self.toggle_autorun,
            lambda mode:set_mode(BASE,mode)),"자동 실행","펫을 자동으로 켜는 시점")

    def transparency_menu_items(self, sid=None):
        level,auto=opacity_options(self.conf,sid)
        self.menu.caption="이 대화에만 적용" if sid else "모든 말풍선의 기본 설정"
        back=(lambda:self.menu.navigate(lambda:self.bubble_menu_items(sid),"말풍선 설정","이 대화에만 적용")) if sid else (lambda:self.menu.navigate(lambda:self.menu_items(None)))
        return [
            ("뒤로",back,False,True,{"icon":"back"}),
            None,
            ("투명도",None,False,True,{"slider":{"value":level,"min":0,"max":80,
                "change":lambda value:self.set_bubble_transparency(value,persist=False,sid=sid),
                "commit":lambda:save_conf(self.conf)}}),
            None,
            ("뒤쪽 글자 자동 감지",lambda:self.toggle_auto_transparency(sid),False,True,
             {"icon":"bubble","selected":auto}),
        ]

    def set_bubble_transparency(self, level, persist=True, sid=None):
        level=max(0,min(80,int(level)))
        if sid is not None:
            options=self.conf.setdefault("bubble_overrides",{}).setdefault(sid,{})
            options["transparency"]=level
            if persist:save_conf(self.conf)
            self.invalidate_bubble(sid)
            return
        if self.conf.get("bubble_transparency",30)==level:
            return
        self.conf["bubble_transparency"]=level
        self._bubble_variants={}
        self._render_profiles={}
        if persist:
            save_conf(self.conf)
        self._static=None
        self._frame_key=None
        self.draw_now()

    def skin_menu_items(self, sid=None):
        items = [("뒤로", lambda: self.menu.navigate(lambda: self.menu_items(sid)), False, True, {"icon": "back"}), None]
        cur = self.conf.get("skin") or "robot"
        builtin = [("robot", "로봇")] + [(k, m.NAME) for k, m in BUILTIN_SKINS.items()]
        for key, label in builtin + imagepet.list_skins():
            items.append((label, lambda k=key: self.choose_skin(k), False, True,
                          {"icon": "pet", "skin": key, "selected": key == cur}))
        return items

    def toggle_all_monitors(self):
        enabled = not self.conf.get("all_monitors", False)
        if not enabled:
            # Keep the pet on the display where this menu was opened.
            self.pc = list(self.displays.menu_center)
        self.conf["all_monitors"] = enabled
        self.conf["pc"] = list(self.pc)
        save_conf(self.conf)
        self.geom()
        self._frame_key = None
        self.displays.sync()
        self.draw_now()

    def choose_skin(self, key):
        self.conf["skin"] = None if key == "robot" else key
        save_conf(self.conf)
        set_skin(self.conf["skin"])
        self.geom()
        self._frame_key = None
        self._static = None
        self.draw_now()

    def toggle_bubble(self):
        self.conf["bubble"] = not self.conf["bubble"]
        save_conf(self.conf)

    def resize(self, step):
        new = round(min(max(self.pix * (1.1 ** step), PIX_MIN), PIX_MAX), 2)
        if new == self.pix:
            return
        self.pix = new
        self.geom()
        self._frame_key = None
        self.conf["fc"] = new
        save_conf(self.conf)
        self.draw_now()

    def dismiss(self, sid):
        self.acknowledge_completion(sid)
        set_dismissed(sid)
        self.sessions = [s for s in self.sessions if s["session_id"] != sid]
        if self.input.sid == sid:
            self.input.hide(force=True)
        self.hover_bubble = self.hover_x = None

    def toggle_autorun(self):
        set_enabled(BASE, is_suspended(BASE))

    def poll_shell_priority(self):
        try:
            _shell_priority.enforce()
        except Exception:
            log_error()
        self.root.after(100, self.poll_shell_priority)

    def poll_tray_command(self):
        try:
            conn, _ = _lock.accept()
        except BlockingIOError:
            pass
        else:
            with conn:
                conn.settimeout(.05)
                try:
                    command=conn.recv(16)
                    if command==b"quit":
                        self.quit(notify_host=False)
                        return
                    if command in (b"can-update",b"prepare-update"):
                        safe=(not self._drag and not self.menu.open_ and not self.syncing
                            and not self.input.has_focus() and not self.input.value().strip())
                        conn.sendall(b"yes" if safe else b"no")
                        if safe and command==b"prepare-update":
                            self.quit(notify_host=False)
                            return
                except OSError:
                    pass
        self.root.after(200, self.poll_tray_command)

    def quit(self, notify_host=True):
        if notify_host and __name__ == "__main__":
            from tray_host import notify, HIDE
            notify(HIDE)
        if self.text_watcher:
            self.text_watcher.stop()
        try:
            self.chat.stop()
        except Exception:
            pass
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
        self.root.destroy()

    def keep_on_top(self):
        try:
            self.displays.topmost()
            if self.input.visible:
                self.input.frame.topmost()
                self.input.win.lift()
            if self.menu.open_:
                self.menu.layer.topmost()
        except Exception:
            pass
        self.root.after(2000, self.keep_on_top)

    # ---- 말풍선 (지피티 펫처럼: 굵은 제목 + 회색 본문, 연회색 알약) ----
    def bubble_content(self, s, st):
        now = time.time()
        label = {"working": "작업 중", "waiting": "기다리는 중", "done": "완료", "idle": "쉬는 중"}[st]
        if st in ("working", "waiting") and s.get("turn_start"):
            label += " " + fmt_dur(now - s["turn_start"])
        elif st == "done" and s.get("turn_start") and s.get("turn_end"):
            label += " " + fmt_dur(s["turn_end"] - s["turn_start"])
        title = self.titles.target(s)[2]
        plan = s.get("plan") or []
        line3 = ""
        if st == "working":
            cur = next((i for i, p in enumerate(plan) if p["status"] == "in_progress"), None)
            line2 = (f"{cur + 1}/{len(plan)} · {plan[cur]['content']}" if cur is not None
                     else (s.get("prompt") or s.get("detail") or "작업 중"))
            line3 = s.get("tool") or ""
        elif st == "done":
            line2 = s.get("summary") or s.get("detail") or "작업 완료"
            line3 = "요청: " + s["prompt"] if s.get("prompt") else ""
        else:
            line2 = s.get("detail") or "입력을 기다려요"
            line3 = s.get("prompt") or ""
        frac = sum(p["status"] == "completed" for p in plan) / len(plan) if plan else None
        return title, label, line2, line3, frac

    def bubble(self, s, st, t, xhover):
        content = self.bubble_content(s, st)
        transparency=bubble_level(self,s["session_id"])
        opacity=1-transparency/100
        dimensions=bubble_geometry(getattr(self,"conf",{}),s["session_id"],st,self.BW)
        key = (st, xhover, transparency,dimensions) + content
        sid=s["session_id"]
        variants=self.__dict__.setdefault("_bubble_variants",{})
        variant=variants.get((sid,transparency))
        if variant and variant[0]==key:
            return variant[1]
        hit = self.bubble_cache.get(sid)
        if hit and hit[0] == key:
            return hit[1]
        bodies=self.__dict__.setdefault("_bubble_body_cache",{})
        base_key=(st,xhover,dimensions)+content
        base=bodies.get(sid)
        if base and base[0]==base_key:
            source,h,m=base[1]
            img=source.copy() if transparency else source
            if transparency:
                img.putalpha(img.getchannel("A").point(lambda a:round(a*opacity)))
            result=(img,h,m)
            self.bubble_cache[sid]=(key,result)
            variants[(sid,transparency)]=(key,result)
            return result
        title, label, line2, line3, frac = content
        BW,h,row_scale,font_scale,size_scale=dimensions
        pad=16*size_scale
        ftitle=scaled_bubble_font(F_TITLE,font_scale)
        fbody=scaled_bubble_font(F_BODY,font_scale)
        fsmall=scaled_bubble_font(F_SMALL,font_scale)
        rows = [("head",19*row_scale),("l2",39*row_scale)]
        y=39*row_scale
        if st == "working":  # 작업 중: 항상 큰 말풍선 (진행 막대 + 실행 중인 명령 줄)
            y += 13*row_scale
            rows.append(("bar", y))
            y += 17*row_scale
            rows.append(("l3", y))
            line3 = line3 or "생각 중…"
            frac = frac or 0.0
        # 완료·기다림: 작은 말풍선 (제목 + 한 줄)
        r = min(h / 2,22*size_scale)
        m = 10
        Wb, Hb = S(BW + 2 * m), S(h + 2 * m)
        img = Image.new("RGBA", (Wb, Hb), (0, 0, 0, 0))
        sh, sm = soft_shadow(S(BW), S(h), S(r), S(4), 90)
        img.alpha_composite(sh, (S(m) - sm, S(m + 2) - sm))
        big = Image.new("RGBA", (Wb * SS, Hb * SS), (0, 0, 0, 0))
        pen = Pen(big, m, m)
        pen.rrect(0, 0, BW, h, r, rgba(C["bubble_line"]))
        # 위는 밝고 아래로 갈수록 살짝 어두운 연회색
        inner = Image.new("L", big.size, 0)
        Pen(inner, m, m).rrect(1, 1, BW - 1, h - 1, r - 1, 255)
        g = Image.linear_gradient("L").resize((1, int((h - 2) * SCALE * SS))).resize((big.width, int((h - 2) * SCALE * SS)))
        top, bot = C["bubble_top"], C["bubble_bot"]
        grad = Image.merge("RGB", [g.point(lambda v, a=a, b=b: int(a + (b - a) * v / 255)) for a, b in zip(top, bot)])
        canvas = Image.new("RGB", big.size, top)
        canvas.paste(grad, (0, int((m + 1) * SCALE * SS)))
        big.paste(canvas, (0, 0), inner)
        col = C[st]
        cx, cy = pad + 4,19*row_scale
        if st == "working":
            pen.arc(cx, cy, 4.5, 0, 360, 1.8, rgba(col, 70))
        else:
            pen.oval(cx, cy, 4, 4, rgba(col))
        for kind, yy in rows:
            if kind == "bar":
                pen.rrect(pad, yy - 2, BW - pad, yy + 2, 2, rgba(C["bar_bg"]))
                if frac > 0:
                    pen.rrect(pad, yy - 2, pad + max(4, (BW - 2 * pad) * frac), yy + 2, 2, rgba(col))
        if xhover:  # 오른쪽 위 닫기(X)
            xc, yc = BW - 7, 7
            pen.oval(xc, yc, 9, 9, rgba((60, 60, 66)))
            pen.line([(xc - 3.2, yc - 3.2), (xc + 3.2, yc + 3.2)], 1.6, (255, 255, 255, 255))
            pen.line([(xc - 3.2, yc + 3.2), (xc + 3.2, yc - 3.2)], 1.6, (255, 255, 255, 255))
        X = lambda v: S(m + v)
        lab_w = fsmall.getlength(label) / SCALE
        right = BW - pad - (14 if xhover else 0)
        # 맨 윗줄(대화 이름 · 상태)은 덧입힘 외곽선 없이 → 아래 줄들보다 살짝 가볍게
        bold_text(big, (X(right), X(19*row_scale)), label, fsmall, C["sub"], "rm", stroke=0)
        bold_text(big, (X(pad + 11), X(19*row_scale)), trunc(title, ftitle, S(right - pad - 11 - lab_w - 10)),
                  ftitle, C["title"], "lm", stroke=0)
        for kind, yy in rows:
            if kind == "l2":
                bold_text(big, (X(pad), X(yy)), trunc(line2, fbody, S(BW - 2 * pad)), fbody, C["text"], "lm")
            elif kind == "l3":
                bold_text(big, (X(pad), X(yy)), trunc(line3, fsmall, S(BW - 2 * pad)), fsmall, C["faint"], "lm")
        img.alpha_composite(big.resize((Wb, Hb), Image.LANCZOS))
        bodies[sid]=(base_key,(img,h,m))
        if transparency:
            img=img.copy()
            img.putalpha(img.getchannel("A").point(lambda a:round(a*opacity)))
        result=(img,h,m)
        self.bubble_cache[sid]=(key,result)
        variants[(sid,transparency)]=(key,result)
        return result

    # ---- 그리기 ----
    def static_layers(self, placed, tb):
        """말풍선·생각 꼬리·흰 막대·바닥 그림자·새 대화 버튼 층. 이것들이 그대로면 다시 그리지 않는다.
        반환: 말풍선 층 복사본 (그 위에 불빛 → 꼬리·막대 층 → 펫 순서로 얹는다)."""
        skey = (self._layout_signature, tuple((p[0], p[1], id(p[3])) for p in placed), self.pix, self.Wp, self.Hp,
                tb, self.hover_nc, self.hover_ul, self.hover_sync, self.syncing, self.hover_bar, self.usage)
        if getattr(self, "_static", None) and self._static[0] == skey:
            return self._static[1].copy()
        bub = Image.new("RGBA", (self.Wp, self.Hp), (0, 0, 0, 0))
        fxw = Image.new("RGBA", (self.Wp * SS, self.Hp * SS), (0, 0, 0, 0))
        fx = Pen(fxw)
        self.bubble_rects = []
        self.bar_rects = []
        cx0, cy0 = self.cx, self.cy
        dots = []   # 펫과 말풍선을 잇는 생각 방울 (x, y, 반지름)
        for sid, slot, xh, bimg, h, m in placed:
            x0, by, x1, _ = self._bubble_boxes[sid]
            bub.alpha_composite(bimg, (S(x0) - S(m), S(by) - S(m)))
            self.bubble_rects.append((x0, by, x1, by + h, sid))
            # 말풍선 아래 작은 흰 막대 (여기에 마우스를 올리면 입력창)
            bxc = (x0 + x1) / 2
            bar_y = by + h + 7
            draw_bar(fx, bxc, bar_y, self.hover_bar == sid,1-bubble_level(self,sid)/100)
            self.bar_rects.append((bxc, bar_y, sid))
            ax = min(max(cx0, x0 + 8), x1 - 8)
            ay = min(max(cy0, by + 8), by + h - 8)
            dx, dy = cx0 - ax, cy0 - ay
            dist = math.hypot(dx, dy) or 1
            ux, uy = dx / dist, dy / dist
            dots += [(ax + ux * 8, ay + uy * 8, 4.2,sid), (ax + ux * 15.5, ay + uy * 15.5, 2.6,sid)]
        if dots:   # 말풍선과 같은 모양: 옅은 그림자 + 회색 테두리 + 위 밝고 아래 살짝 어두운 바탕
            k = SCALE * SS
            for x, y, r, sid in dots:   # 그림자는 방울 주변 작은 조각만 흐리게 (전체 그림을 흐리면 느림)
                half = r + 5
                patch = Image.new("RGBA", (int(2 * half * k) + 2,) * 2, (0, 0, 0, 0))
                Pen(patch, half, half).oval(0, 1.2, r + 0.6, r + 0.6, (0, 0, 0, round(55*(1-bubble_level(self,sid)/100))))
                patch = patch.filter(ImageFilter.GaussianBlur(S(1.6) * SS))
                px, py = int((x - half) * k), int((y - half) * k)
                if px >= 0 and py >= 0:
                    fxw.alpha_composite(patch, (px, py))
            mid = tuple((a + b) // 2 for a, b in zip(C["bubble_top"], C["bubble_bot"]))
            for x, y, r, sid in dots:
                alpha=round(255*(1-bubble_level(self,sid)/100))
                fx.oval(x, y, r, r, rgba(C["bubble_line"],alpha))
                fx.oval(x, y + 0.25, r - 1, r - 1.1, rgba(mid,alpha))
                fx.oval(x, y - 0.35, r - 1.3, r - 1.5, rgba(C["bubble_top"],alpha))
        # 바닥 그림자
        u = self.f / SCALE
        density = getattr(pixelpet, "pixel_density", 1.0)
        fx.oval(cx0, cy0 + (pixelpet.GH - pixelpet.center()[1] - 9 * density) * u,
                24 * u * density, 3 * u * density, (0, 0, 20, 70))
        # 펫 밑 흰 막대 (여기에 올리면 판이 열림)
        draw_bar(fx, cx0, self.petbar_y, tb)
        if tb:  # 판: 새 대화 버튼 + 사용량
            x0, y0, x1, y1 = self.tb_rect
            r = self.PANEL_H / 2
            shadow = Image.new("RGBA", fxw.size, (0, 0, 0, 0))
            Pen(shadow).rrect(x0, y0 + 2, x1, y1 + 2, r, (0, 0, 0, 60))
            fxw.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S(4) * SS)))
            fx.rrect(x0, y0, x1, y1, r, rgba(C["bubble_line"]))
            fx.rrect(x0 + 1, y0 + 1, x1 - 1, y1 - 1, r - 1, rgba(C["bubble_top"]))
            # 왼쪽 위 작은 동기화 버튼 (판 테두리에 걸친 동그라미 + 돌아가는 화살표)
            sx, sy = self.nc_rect[2] + 5, y0 + 1   # 새 대화 버튼과 사용량 글자 사이, 위 테두리에 걸침
            self.sync_c = (sx, sy)
            fx.oval(sx, sy + 0.8, 8.6, 8.6, (0, 0, 0, 30))
            fx.oval(sx, sy, 8, 8, rgba(C["bubble_line"]))
            fx.oval(sx, sy, 7, 7, rgba(C["menu_hover"] if self.hover_sync else (255, 255, 255)))
            ink_s = rgba(C["working"] if self.syncing else C["sub"])
            k = SCALE * SS
            ar = 3.6
            ImageDraw.Draw(fxw).arc([(sx - ar) * k, (sy - ar) * k, (sx + ar) * k, (sy + ar) * k], 300, 230,
                                    fill=ink_s, width=max(1, int(1.3 * k)))
            ex, ey = sx + ar * math.cos(math.radians(300)), sy + ar * math.sin(math.radians(300))
            fx.line([(ex - 2.4, ey - 1.0), (ex, ey), (ex - 0.4, ey + 2.4)], 1.2, ink_s)
            n0, n1, n2, n3 = self.nc_rect
            ic, iy = (n0 + n2) / 2, (n1 + n3) / 2
            fx.oval(ic, iy, 15, 15, rgba(C["bubble_line"]))
            fx.oval(ic, iy, 14, 14, rgba(C["menu_hover"] if self.hover_nc else (255, 255, 255)))
            ink = rgba(C["title"])
            # 새 대화 아이콘: 열린 네모 + 연필
            fx.line([(ic + 1, iy - 6), (ic - 5, iy - 6), (ic - 6, iy - 5), (ic - 6, iy + 5), (ic - 5, iy + 6),
                     (ic + 5, iy + 6), (ic + 6, iy + 5), (ic + 6, iy - 1)], 1.4, ink)
            fx.line([(ic - 2, iy + 2), (ic + 6, iy - 6)], 2.0, ink)
            fx.oval(ic - 2.3, iy + 2.3, 1.0, 1.0, ink)
            # 사용량 두 줄: 5시간 / 주간 - 각 줄에 %, 막대, 리셋 시각 (리셋은 앱 화면에서 읽어 기억한 값)
            tx, bar_x1 = n2 + 10, x1 - 16
            us = self.usage
            self.ulink_rect = None
            if not us:
                bold_text(fxw, (S(tx), S(y0 + self.PANEL_H / 2)), "사용량 정보 없음", F_SMALL, C["title"], "lm")
            else:
                for i, (name, pct, rst) in enumerate((("현재", us["fh"], us.get("sreset")),
                                                      ("주간", us["sd"], us.get("wreset")))):
                    yy = y0 + 16 + i * 22
                    bold_text(fxw, (S(tx), S(yy)), f"{name} {pct:.0f}%", F_SMALL, C["title"], "lm")
                    if rst:
                        bold_text(fxw, (S(bar_x1), S(yy + 0.5)), f"리셋 {rst}", F_TINY, C["sub"], "rm", stroke=0)
                    elif self.ulink_rect is None:   # 리셋을 아직 모르면: 사용량 탭으로 가는 글자 버튼 (한 번만)
                        label = "사용량 탭 열기 ›"
                        lw = F_TINY.getlength(label) / SCALE
                        self.ulink_rect = (bar_x1 - lw, yy - 6, bar_x1, yy + 6)
                        bold_text(fxw, (S(bar_x1), S(yy + 0.5)), label, F_TINY, C["working"], "rm",
                                  stroke=1 if self.hover_ul else 0)
                        if self.hover_ul:
                            fx.rrect(bar_x1 - lw, yy + 5.2, bar_x1, yy + 5.9, 0.3, rgba(C["working"]))
                    frac = max(0.0, min(1.0, pct / 100))
                    fx.rrect(tx, yy + 8, bar_x1, yy + 10.5, 1.25, rgba(C["bar_bg"]))
                    if frac > 0:
                        col = C["done"] if frac < 0.5 else (C["waiting"] if frac < 0.8 else C["danger"])
                        fx.rrect(tx, yy + 8, tx + max(3, (bar_x1 - tx) * frac), yy + 10.5, 1.25, rgba(col))
        self._static = (skey, bub, fxw.resize((self.Wp, self.Hp), Image.LANCZOS))
        return bub.copy()

    def render(self, t):
        now,mono=getattr(self,"_draw_clock",(time.time(),time.monotonic()))
        st = self.pet_state()
        self.overlay_layout()
        q = lambda v, step: round(v / step) * step

        placed = []
        if self.conf["bubble"]:
            for s, slot in self.assign_slots():
                xh = self.hover_x == s["session_id"]
                placed.append((s["session_id"], slot, xh) + self.bubble(s, s["_state"], t, xh))

        spin_phase = int(t * 6) % 12 if any(s["_state"] == "working" for s in self.sessions) and placed else None
        since = now - self.celebrate_since
        celebrate = bool(self.completions.pending)
        hover = self.hover_since is not None
        hov_t = now - self.hover_since if hover else 0
        bob = 0
        if celebrate:
            bob = int(abs(math.sin(since * 8)) * 5.99)
        elif hover and hov_t < 0.4:
            bob = 2
        if celebrate:
            arms, wave = "up_both", int(math.sin(since * 10) > 0)
        elif hover:
            arms, wave = "up_right", int(math.sin(hov_t * 9) > 0)
        elif st == "waiting":
            arms, wave = "up_right", 0
        else:
            arms, wave = "down", 0
        if now > self.next_blink:
            self.next_blink = now + random.uniform(3, 6)
        closing = (self.next_blink - now) < 0.14
        eyes = "happy" if (celebrate or hover or st == "done") else ("wide" if st == "waiting" else
                                                                      ("blink" if closing else "open"))
        stars = tuple(int((math.sin(since * 6 + i * 1.7) + 1) > 0.6) for i in range(4)) if celebrate else ()
        glow, rk = signature_glow(st, t, since if self.celebrate_since else None)
        anim = ()
        if getattr(pixelpet, "ANIMATED", False):
            if hasattr(pixelpet, "frame_token"):
                # Cache by the actual state/frame instead of an unbounded timer tick.
                token = pixelpet.frame_token(st, eyes, arms, st == "waiting" and not hover and not celebrate,
                                            stars, mono)
                anim = (("frame", token),)
                if hasattr(pixelpet, "effect_token"):
                    effect = pixelpet.effect_token(mono)
                    if effect is not None:
                        anim += (("fx_phase", effect),)
            else:
                anim = (("breath", int(t / 1.5) % 2), ("flick", int(t * 6) % 3),
                        ("sway", int(t / 1.1) % 2), ("tick", int(t * 12)))
        glow, rk = q(glow, 0.03), q(rk, 0.05)
        tb = self.toolbar_visible()
        key = (self._layout_signature, tuple((p[0], p[1], id(p[3])) for p in placed), self.pix, st, bob, arms, wave, eyes, stars, glow, rk,
               id(pixelpet), anim, spin_phase,
               tb, self.hover_nc, self.hover_ul, self.hover_sync, self.syncing, self.hover_bar, self.usage)
        if key == self._frame_key:
            return None
        self._frame_key = key

        img = self.static_layers(placed, tb)
        cx0, cy0 = self.cx, self.cy
        u = self.f / SCALE
        density = getattr(pixelpet, "pixel_density", 1.0)
        # 안테나 전구 불빛 (흐리게 번진 빛만, 픽셀 펫 뒤) — 전구 주변 작은 영역만 흐리게
        if glow > 0:
            bulb = pixelpet.PAL["bulb"][st]
            gx_, gy_ = pixelpet.center()
            bcx, bcy = pixelpet.bulb_center()
            bx_, by_ = S(cx0 + (bcx - gx_) * u), S(cy0 + (bcy - bob * density - gy_) * u)
            r_, blur = S(9 * u * density * rk), S(4.4 * u * density * rk)
            gl, pad = signature_halo(tuple(bulb), r_, blur, glow)
            img.alpha_composite(gl, (bx_ - pad, by_ - pad))
        img.alpha_composite(self._static[2])
        if spin_phase is not None:
            for session in self.sessions:
                sid=session["session_id"]
                if session["_state"] == "working" and sid in self._bubble_boxes:
                    spinner=bubble_spinner(spin_phase,bubble_level(self,sid))
                    x0,by,_,_=self._bubble_boxes[sid]
                    _,_,row,_,scale=bubble_geometry(self.conf,sid,session["_state"],self.BW)
                    img.alpha_composite(spinner,(S(x0)-S(10)+S(10+16*scale+4)-S(8), S(by)-S(10)+S(10+19*row)-S(8)))
        # 픽셀 펫 (최근접 확대, 소수 배율 지원; 같은 자세는 캐시 재사용)
        spr = pet_sprite(st, eyes, arms, bob, st == "waiting" and not hover and not celebrate, stars, wave, self.f, id(pixelpet), anim)
        img.alpha_composite(spr, (S(cx0 - self.spr_off[0]), S(cy0 - self.spr_off[1])))
        return img

    def draw_now(self):
        topology_changed=self.displays.sync()
        anchor=work_area(self.pc)
        areas=[anchor]+list(self.displays.mirrors)
        profiles=self.__dict__.setdefault("_render_profiles",{})
        live=frozenset(s["session_id"] for s in self.sessions)
        for profile in list(profiles):
            if frozenset(sid for sid,_ in profile)!=live:profiles.pop(profile,None)
        images={}
        assignments={}
        changed=bool(topology_changed)
        self._draw_clock=(time.time(),time.monotonic())
        t=self._draw_clock[0]-self.t0
        try:
            for area in areas:
                self._opacity_area=tuple(area)
                profile=tuple((s["session_id"],bubble_level(self,s["session_id"])) for s in self.sessions)
                assignments[area]=profile
                cached=profiles.pop(profile,None)
                if cached:
                    self._frame_key,self._static,last_image=cached
                else:
                    self._frame_key=None
                    self._static=None
                    last_image=None
                img=self.render(t)
                if img is not None:
                    last_image=img;changed=True
                images[area]=last_image
                profiles[profile]=(self._frame_key,self._static,last_image)
        finally:
            self._opacity_area=tuple(anchor)
            self.__dict__.pop("_draw_clock",None)
        if assignments!=getattr(self,"_last_area_profiles",None):changed=True
        self._last_area_profiles=assignments
        if changed:
            self.displays.present(images=images)
        while len(profiles)>8:
            profiles.pop(next(iter(profiles)))

    def animate(self):
        if not self._drag or not self._moved:
            try:
                self.draw_now()
            except Exception:
                log_error()
        self.root.after(80, self.animate)


if __name__ == "__main__":
    os.makedirs(STATE_DIR, exist_ok=True)
    Pet().root.mainloop()
