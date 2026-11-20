"""Claude Code 훅이 없는 환경(코워크, 일반 채팅)의 진행상황을 state/*.json 으로 옮긴다.

- CoworkWatcher: 데스크톱 앱이 이 PC에 남기는 코워크 세션 기록(Claude Code 형식 jsonl)을
  바뀔 때만 끝부분을 읽어 상태를 계산한다. 코워크 대화마다 말풍선이 하나씩 생긴다.
- ChatWatcher: chat_watch.ps1 (Windows 접근성 정보)로 앱의 '채팅/Code' 모드 버튼 상태와
  '응답 중' 표시를 읽는다. 일반 채팅은 대화 내용이 PC에 저장되지 않아 말풍선 하나로 묶어 보여준다.
  같은 도우미가 Code 입력창 옆 사용량 버튼·설정 사용량 탭의 리셋 시각도 함께 읽는다.
두 감시자 모두 앱이 어느 모드를 보고 있든 계속 동작하므로, 모드를 오가도 말풍선은 그대로다.
"""
import glob
import json
import os
import subprocess
import threading
import time
from datetime import datetime

from pet_hook import apply_plan, last_reply, save, short, tool_detail

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE, "state")


def _iso(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _write_state(sid, new):
    """기존 파일의 created·dismissed 등은 유지하며 갱신."""
    p = os.path.join(STATE_DIR, f"{sid}.json")
    try:
        with open(p, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = {}
    st = dict(old)
    st.update(new)
    st["session_id"] = sid
    st.setdefault("created", new.get("created") or time.time())
    if st == old:
        return
    save(p, st)  # 원자적 저장 (pet_hook.save)


def _read_state(sid):
    try:
        with open(os.path.join(STATE_DIR, f"{sid}.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---- 코워크 -------------------------------------------------------------
class CoworkWatcher:
    ROOTS = [r"%LOCALAPPDATA%\Claude-Data\claude_*\local-agent-mode-sessions",
             r"%APPDATA%\Claude\local-agent-mode-sessions"]
    INTERVAL = 3.0

    def __init__(self):
        self.meta = {}     # meta 파일 → (mtime, info)
        self.seen = {}     # 기록 파일 → mtime
        self.last = 0.0

    def poll(self):
        now = time.time()
        if now - self.last < self.INTERVAL:
            return
        self.last = now
        for root in self.ROOTS:
            for mf in glob.glob(os.path.join(os.path.expandvars(root), "*", "*", "local_*.json")):
                try:
                    self._one(mf, now)
                except Exception:
                    pass

    def _one(self, mf, now):
        mt = os.path.getmtime(mf)
        sdir = os.path.splitext(mf)[0]
        info = self.meta.get(mf)
        if info is None or info[0] != mt:
            if now - mt > 7 * 86400 and info is None:
                # 오래된 세션은 메타 파일을 열지 않고, 기록 파일 날짜만 본다
                cands = glob.glob(os.path.join(sdir, ".claude", "projects", "*", "*.jsonl"))
                if not cands or now - max(os.path.getmtime(c) for c in cands) > 86400:
                    self.meta[mf] = (mt, None)
                    return
            with open(mf, encoding="utf-8") as f:
                d = json.load(f)
            tr = glob.glob(os.path.join(sdir, ".claude", "projects", "*", f"{d.get('cliSessionId')}.jsonl"))
            info = (mt, {"title": d.get("title") or d.get("initialMessage") or "코워크",
                         "archived": bool(d.get("isArchived")), "transcript": tr[0] if tr else None,
                         "created": (d.get("createdAt") or 0) / 1000 or None,
                         "sid": "cowork_" + str(d.get("sessionId") or os.path.basename(sdir))})
            self.meta[mf] = info
        info = info[1]
        if not info or info["archived"] or not info["transcript"]:
            return
        tr = info["transcript"]
        tmt = os.path.getmtime(tr)
        if now - tmt > 86400 or self.seen.get(tr) == tmt:
            return
        self.seen[tr] = tmt
        st = self._from_transcript(tr, tmt)
        st.update(title=short(info["title"], 40), cwd="", source="cowork", updated=tmt)
        if info["created"]:
            st["created"] = info["created"]
        _write_state(info["sid"], st)

    @staticmethod
    def _from_transcript(path, tmt):
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 300_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        if size > 300_000:
            lines = lines[1:]
        recs = []
        for line in lines:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("type") in ("user", "assistant") and not r.get("isSidechain") and not r.get("isMeta"):
                recs.append(r)
        if not recs:
            return {"state": "idle", "detail": "대기 중"}
        # 마지막 사용자 요청 (도구 결과가 아닌 것)
        start_i, prompt = 0, ""
        for i in range(len(recs) - 1, -1, -1):
            c = (recs[i].get("message") or {}).get("content")
            if recs[i]["type"] != "user":
                continue
            if isinstance(c, str):
                start_i, prompt = i, c
                break
            if isinstance(c, list) and not any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                texts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
                start_i, prompt = i, " ".join(texts)
                break
        st = {"prompt": short(prompt, 80), "turn_start": _iso(recs[start_i].get("timestamp"))}
        plan_st = {"plan": []}
        tool = ""
        for r in recs[start_i:]:
            if r["type"] != "assistant":
                continue
            for x in (r.get("message") or {}).get("content") or []:
                if not isinstance(x, dict) or x.get("type") != "tool_use":
                    continue
                name, inp = str(x.get("name") or ""), x.get("input") or {}
                if name == "TodoWrite" and isinstance(inp.get("todos"), list):
                    plan_st["plan"] = [{"content": str(t.get("activeForm") if t.get("status") == "in_progress" and t.get("activeForm") else t.get("content", "")),
                                        "status": t.get("status", "pending")} for t in inp["todos"] if isinstance(t, dict)]
                elif name.endswith("update_plan"):
                    apply_plan(plan_st, inp)
                else:
                    tool = tool_detail(name, inp)
        st["plan"] = plan_st["plan"]
        last = recs[-1]
        msg = last.get("message") or {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        has_tool = any(isinstance(x, dict) and x.get("type") == "tool_use" for x in content)
        if last["type"] == "assistant" and not has_tool and msg.get("stop_reason") != "tool_use":
            text = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
            st.update(state="done", detail="작업 완료! 확인해 주세요", tool="",
                      turn_end=_iso(last.get("timestamp")) or tmt, summary=last_reply(text, None))
            for p in st["plan"]:
                if p["status"] == "in_progress":
                    p["status"] = "completed"
        else:
            st.update(state="working", tool=tool, turn_end=None, summary="", detail="작업 중")
        return st


# ---- 일반 채팅 ------------------------------------------------------------
class ChatWatcher:
    SID = "chat"

    def __init__(self):
        self.latest = None
        self.proc = None
        self.prev = _read_state(self.SID).get("state")
        self.last_write = 0.0
        self._stopped = False
        self.start()

    def start(self):
        if self._stopped:
            return
        self._last_start = time.time()
        ps1 = os.path.join(BASE, "chat_watch.ps1")
        try:
            self.proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                 "-File", ps1, str(os.getpid())],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
        except Exception:
            self.proc = None
            return
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        try:
            with proc.stdout:
                for raw in proc.stdout:
                    if self.proc is not proc:
                        break
                    try:
                        self.latest = json.loads(raw.decode("utf-8-sig", "replace"))
                    except (ValueError, UnicodeError):
                        pass
        except OSError:
            pass

    def stop(self):
        self._stopped = True
        try:
            if self.proc:
                self.proc.kill()
                self.proc.wait(timeout=1)
        except Exception:
            pass

    def poll(self):
        if self._stopped:
            return
        now = time.time()
        if self.proc is None or self.proc.poll() is not None:  # 실패·종료 시 재시도 (10초에 한 번까지)
            if now - getattr(self, "_last_start", 0) > 10:
                self._last_start = now
                self.start()
        o = self.latest
        if not o or not o.get("ok"):
            return
        signature = tuple(o.get(k) for k in ("chat", "responding", "active", "doc"))
        if signature == getattr(self, "_chat_signature", None) and (self.prev != "working" or now-self.last_write < 10):
            return  # 사용량만 바뀌면 대화 상태 파일은 건드리지 않음; 작업 중에는 10초 heartbeat
        self._chat_signature = signature
        status = str(o.get("chat") or "").strip()
        low = status.lower()
        working = bool(o.get("responding")) or any(k in low for k in ("respond", "working", "thinking", "generat", "running", "응답", "작업"))
        attention = ("awaiting" in low or "input" in low or "입력" in low) and not working
        now = time.time()
        old = _read_state(self.SID)
        doc = str(o.get("doc") or "")
        if doc.endswith(" - Claude"):
            doc = doc[: -len(" - Claude")]
        new = {"title": "채팅 · 코워크", "cwd": "", "source": "chat"}
        if working:
            new.update(state="working", detail="Claude가 답하는 중", tool=short(doc, 60) if o.get("active") == "chat" else "",
                       summary="", turn_end=None, plan=[])
            if self.prev != "working":
                new["turn_start"] = now
            if self.prev != "working" or now - self.last_write >= 10:
                new["updated"] = now
        elif attention:
            new.update(state="done", detail="답변이 도착했어요", tool="",
                       summary="채팅에서 답변을 확인해 주세요" + (f" ({status})" if status and "awaiting" not in low else ""))
            if self.prev == "working":
                new.update(turn_end=now)
            if self.prev != "done":
                new["updated"] = now
        else:
            if self.prev == "working":  # 보고 있는 사이에 답이 끝남
                new.update(state="done", detail="답변 완료", summary="", turn_end=now, updated=now)
            elif not old:
                return  # 채팅 활동을 아직 본 적 없으면 펫을 만들지 않음
            else:
                return  # 완료 상태는 그대로 기억
        if not old and "updated" not in new:
            new["updated"] = now
        new.setdefault("created", 0.0)  # 채팅 펫은 항상 맨 앞(오른쪽)
        _write_state(self.SID, new)
        self.prev = new.get("state", self.prev)
        if "updated" in new:
            self.last_write = now
