"""Persistent, skin-independent completion acknowledgements."""


class CompletionState:
    def __init__(self, data=None):
        data = data or {}
        self.pending = dict(data.get("pending") or {})
        self.acknowledged = dict(data.get("acknowledged") or {})

    def snapshot(self):
        return {"pending": dict(self.pending), "acknowledged": dict(self.acknowledged)}

    def acknowledge(self, sid=None):
        changed = False
        for key in list(self.pending) if sid is None else [sid]:
            if key in self.pending:
                self.acknowledged[key] = self.pending.pop(key)
                changed = True
        return changed

    def update(self, sessions):
        """Missing/aged-out rooms never silently clear an unacknowledged completion."""
        before = self.snapshot()
        for session in sessions:
            sid = session["session_id"]
            state = session.get("state", session.get("_state"))
            if state == "working":
                # Starting another turn in the same room supersedes its previous result.
                self.acknowledge(sid)
            elif state == "done":
                token = str(session.get("turn_end") or session.get("updated") or "done")
                if self.acknowledged.get(sid) != token:
                    self.pending[sid] = token
        return self.snapshot() != before
