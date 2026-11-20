"""Claude Code 훅 → 펫 상태 파일 기록.

Claude Code가 이벤트(프롬프트 제출, 도구 사용, 알림, 종료)마다 이 스크립트를 실행하고
stdin으로 JSON을 넘긴다. 세션별로 state/<session_id>.json 에 현재 상태를 저장하면
pet.pyw 가 그 파일을 읽어 화면에 표시한다. 어떤 경우에도 Claude 작업을 막지 않도록
예외는 모두 삼키고 아무것도 출력하지 않는다.
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE, "state")
PID_FILE = os.path.join(BASE, "pet.pid")
sys.path.insert(0, BASE)
from autorun import prepare_launch

TOOL_LABELS = {
    "Bash": "명령 실행", "PowerShell": "명령 실행",
    "Read": "파일 읽기", "Write": "파일 쓰기", "Edit": "파일 수정",
    "NotebookEdit": "노트북 수정", "Grep": "내용 검색", "Glob": "파일 찾기",
    "WebSearch": "웹 검색", "WebFetch": "웹 페이지 읽기",
    "Agent": "서브에이전트 실행", "Task": "서브에이전트 실행",
    "Skill": "스킬 불러오기", "ToolSearch": "도구 불러오기",
    "Artifact": "아티팩트 작업", "Workflow": "워크플로 실행",
}


def short(text, n=60):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(path, data):
    """원자적 저장: 프로세스마다 다른 임시 파일에 쓰고 바꿔치기.
    (훅 여러 개가 동시에 돌거나 펫이 파일을 읽는 순간이면 Windows 가 잠깐 거부하므로 몇 번 재시도)"""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    for i in range(6):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.015 * (i + 1))
    try:
        os.remove(tmp)
    except OSError:
        pass


def pid_alive(pid):
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p        # 64비트 핸들이 잘리지 않게
        k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


def ensure_pet(fresh=False):
    """펫이 안 떠 있으면 띄운다 (pythonw, 콘솔 없이, 훅과 분리)."""
    if not prepare_launch(BASE,automatic=True,source="claude"):
        return
    try:
        with open(PID_FILE) as f:
            if pid_alive(f.read().strip()):
                return
    except Exception:
        pass
    import subprocess  # 펫을 새로 띄울 때만 필요 → 매번 불러오지 않아 훅 시작이 빨라짐
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    args = [pyw, "-X", "utf8", "-I", os.path.join(BASE, "pet.pyw"), "--claude-session-start" if fresh else "--claude-start"]
    base_flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    for flags in (base_flags | 0x01000000, base_flags):  # BREAKAWAY_FROM_JOB 먼저 시도
        try:
            subprocess.Popen(args, creationflags=flags, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, cwd=BASE)
            return
        except Exception:
            continue


def tool_detail(name, inp):
    inp = inp or {}
    if name.startswith("mcp__"):
        parts = name.split("__")
        label = parts[-1].replace("_", " ")
    else:
        label = TOOL_LABELS.get(name, name)
    target = ""
    if name in ("Read", "Write", "Edit", "NotebookEdit"):
        target = os.path.basename(str(inp.get("file_path") or inp.get("notebook_path") or ""))
    elif name in ("Bash", "PowerShell"):
        target = inp.get("description") or inp.get("command") or ""
    elif name in ("Grep", "Glob"):
        target = inp.get("pattern") or ""
    elif name == "WebSearch":
        target = inp.get("query") or ""
    elif name == "WebFetch":
        target = inp.get("url") or ""
    elif name in ("Agent", "Task"):
        target = inp.get("description") or ""
    elif name == "Skill":
        target = inp.get("skill") or ""
    return short(f"{label}: {target}" if target else label, 70)


def apply_plan(st, inp):
    plan = st.get("plan") or []
    if isinstance(inp.get("items"), list):
        plan = [{"content": str(i.get("content", "")), "status": i.get("status", "pending")}
                for i in inp["items"] if isinstance(i, dict)]
    if inp.get("advance"):
        cur = next((i for i, p in enumerate(plan) if p["status"] == "in_progress"), None)
        if cur is not None:
            plan[cur]["status"] = "completed"
            nxt = next((i for i in range(cur + 1, len(plan)) if plan[i]["status"] == "pending"), None)
            if nxt is not None:
                plan[nxt]["status"] = "in_progress"
    for n in inp.get("done") or []:
        if isinstance(n, int) and 1 <= n <= len(plan):
            plan[n - 1]["status"] = "completed"
    s = inp.get("start")
    if isinstance(s, int) and 1 <= s <= len(plan):
        for p in plan:
            if p["status"] == "in_progress":
                p["status"] = "pending"
        plan[s - 1]["status"] = "in_progress"
    st["plan"] = plan


def last_reply(given, transcript):
    """완료 시 말풍선에 남길 Claude 마지막 답변의 첫 문장."""
    text = given if isinstance(given, str) else ""
    if not text and transcript and os.path.exists(transcript):
        try:
            with open(transcript, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 400_000))
                lines = f.read().decode("utf-8", "replace").splitlines()
            for line in reversed(lines):
                if '"assistant"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("type") != "assistant":
                    continue
                content = (rec.get("message") or {}).get("content") or []
                texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                if any(t.strip() for t in texts):
                    text = "\n".join(texts)
                    break
        except Exception:
            text = ""
    for line in text.splitlines():  # 표·제목 기호를 뺀 첫 줄
        line = line.strip().lstrip("#>*-| ").replace("**", "").replace("`", "")
        if len(line) >= 4:
            return short(line, 90)
    return ""


def main():
    if any(os.path.exists(os.path.join(BASE,name)) for name in (".uninstalling",".update-in-progress")):
        return
    raw = sys.stdin.buffer.read()
    data = json.loads(raw.decode("utf-8-sig", "replace") or "{}")
    ev = data.get("hook_event_name", "")
    sid = str(data.get("session_id") or "unknown")
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{sid}.json")

    if ev == "SessionEnd":
        try:
            os.remove(path)
        except Exception:
            pass
        return

    st = load(path)
    now = time.time()
    st["session_id"] = sid
    st["cwd"] = data.get("cwd") or st.get("cwd", "")
    st["updated"] = now
    st.setdefault("created", now)  # 펫 줄 세우는 순서 (먼저 생긴 세션이 오른쪽)
    if data.get("transcript_path"):
        st["transcript"] = data["transcript_path"]

    if ev == "SessionStart":
        st.setdefault("state", "idle")
        st.setdefault("detail", "대기 중")
        ensure_pet(fresh=True)
    elif ev == "UserPromptSubmit":
        prompt = short(data.get("prompt"), 80)
        st.update(state="working", turn_start=now, turn_end=None,
                  detail="요청 읽는 중", tool="", plan=[], summary="", prompt=prompt)
        if not st.get("title") and prompt:
            st["title"] = short(prompt, 40)  # 이 대화의 이름표 (첫 요청)
        ensure_pet()
    elif ev == "PreToolUse":
        name = str(data.get("tool_name") or "")
        inp = data.get("tool_input") or {}
        if not st.get("turn_start") or st.get("state") in ("done", "idle"):
            st["turn_start"] = now
        if name.endswith("update_plan"):
            apply_plan(st, inp)
            st["state"] = "working"
        elif name == "AskUserQuestion":
            st.update(state="waiting", detail="질문에 답해 주세요")
        elif name == "ExitPlanMode":
            st.update(state="waiting", detail="계획 승인을 기다려요")
        elif name.endswith("wrap_up"):
            st.update(state="working", tool="마무리 정리 중")
        else:
            st.update(state="working", tool=tool_detail(name, inp))
    elif ev == "Notification":
        msg = str(data.get("message") or "")
        low = msg.lower()
        if "permission" in low or "권한" in msg or "approve" in low:
            st.update(state="waiting", detail="승인이 필요해요")
        elif st.get("state") != "done":
            st.update(state="waiting", detail=short(msg, 60) or "입력을 기다려요")
    elif ev in ("Stop", "SubagentStop"):
        if ev == "Stop":
            st.update(state="done", detail="작업 완료! 확인해 주세요", tool="", turn_end=now,
                      summary=last_reply(data.get("last_assistant_message"), st.get("transcript")))
            for p in st.get("plan") or []:
                if p["status"] == "in_progress":
                    p["status"] = "completed"
    save(path, st)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
