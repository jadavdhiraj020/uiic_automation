"""Durable, strictly ordered Base44 callbacks with Windows-user-bound tokens."""

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
import uuid

from app.web_sync.storage import atomic_json

from .base44 import RemoteError


TERMINAL = frozenset({"completed", "failed", "stopped"})
ALLOWED = TERMINAL | {"running", "awaiting_final_submit"}


def _protect(value):
    import win32crypt
    encrypted = win32crypt.CryptProtectData(value.encode("utf-8"), "DocWriter helper run token", None, None, None, 0)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect(value):
    import win32crypt
    encrypted = base64.b64decode(value, validate=True)
    return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode("utf-8")


@dataclass(frozen=True)
class CallbackContext:
    run_id: str
    dispatch_id: str
    callback_endpoint: str
    run_token: str


class CallbackOutbox:
    def __init__(self, path, context, client, on_stale=lambda: None, logger=lambda message: None,
                 recovered=None):
        self.path = Path(path)
        self.context = context
        self.client = client
        self.on_stale = on_stale
        self.log = logger
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = False
        self.data = recovered or {
            "run_id": context.run_id, "dispatch_id": context.dispatch_id,
            "callback_endpoint": context.callback_endpoint,
            "protected_run_token": _protect(context.run_token),
            "acknowledged_seq": 1, "pending": [], "last_status": "redeemed",
            "abandoned": False,
        }
        if recovered is None:
            self._save()
        self.thread = threading.Thread(target=self._deliver_loop, name=f"callback-{context.run_id}", daemon=True)
        self.thread.start()

    @classmethod
    def recover(cls, path, client, on_stale=lambda: None, logger=lambda message: None):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        context = CallbackContext(data["run_id"], data["dispatch_id"],
                                  data["callback_endpoint"], _unprotect(data["protected_run_token"]))
        return cls(path, context, client, on_stale, logger, recovered=data)

    def _save(self):
        atomic_json(self.path, self.data)

    @property
    def last_status(self):
        with self.lock:
            return self.data["last_status"]

    def has_pending(self):
        with self.lock:
            return bool(self.data["pending"])

    def enqueue(self, status, message, confirmation_no=None):
        if status not in ALLOWED:
            raise ValueError("unsupported callback status")
        with self.lock:
            if self.data["abandoned"] or self.data["last_status"] in TERMINAL:
                return False
            if status == "completed" and self.data["last_status"] != "awaiting_final_submit":
                raise ValueError("completed requires awaiting_final_submit first")
            last = self.data["pending"][-1]["seq"] if self.data["pending"] else self.data["acknowledged_seq"]
            event = {"event_id": str(uuid.uuid4()), "seq": last + 1,
                     "status": status, "message": str(message)[:1000]}
            if confirmation_no:
                event["confirmation_no"] = str(confirmation_no)[:120]
            self.data["pending"].append(event)
            self.data["last_status"] = status
            self._save()
            self.wake.set()
            return True

    def mark_abandoned(self, reason):
        with self.lock:
            self.data["abandoned"] = True
            self.data["abandon_reason"] = reason[:300]
            self._save()
            self.wake.set()

    def _deliver_loop(self):
        while not self.closed:
            with self.lock:
                if self.data["abandoned"]:
                    return
                event = dict(self.data["pending"][0]) if self.data["pending"] else None
                terminal_done = self.data["last_status"] in TERMINAL
            if event is None:
                if terminal_done:
                    return
                self.wake.wait(5)
                self.wake.clear()
                continue
            try:
                self.client.callback(self.context, event)
            except RemoteError as exc:
                if exc.status == 409:
                    self.mark_abandoned("Base44 rejected callback with HTTP 409; run stopped")
                    self.log(f"Callback seq {event['seq']} rejected with HTTP 409; stopping run")
                    self.on_stale()
                    return
                self.log(f"Callback seq {event['seq']} pending: HTTP {exc.status}")
                self.wake.wait(5)
                self.wake.clear()
                continue
            except Exception as exc:
                self.log(f"Callback seq {event['seq']} pending: {type(exc).__name__}")
                self.wake.wait(5)
                self.wake.clear()
                continue
            with self.lock:
                if self.data["pending"] and self.data["pending"][0]["event_id"] == event["event_id"]:
                    self.data["pending"].pop(0)
                    self.data["acknowledged_seq"] = event["seq"]
                    self.data["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
                    self._save()
                    self.log(f"Callback seq {event['seq']} acknowledged: {event['status']}")

    def stop(self):
        self.closed = True
        self.wake.set()
