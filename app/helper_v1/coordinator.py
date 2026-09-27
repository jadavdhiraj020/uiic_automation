"""Single-run lifecycle, cooperative Stop, progress, and restart recovery."""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time

from .base44 import Base44V1Client, RemoteError
from .contracts import ContractError
from .intake import ZipIntake
from .outbox import CallbackOutbox, TERMINAL
from .portal import UiicAdapter
from .preparation import prepare_uiic_case


LOG = logging.getLogger("app.helper_v1")


class BusyError(RuntimeError):
    pass


class RunCoordinator:
    def __init__(self, root, client=None, intake=None, prepare=None, adapter=None, heartbeat_interval=30):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)
        self.client = client or Base44V1Client()
        self.intake = intake or ZipIntake(self.root, self.client)
        self.prepare = prepare or prepare_uiic_case
        self.adapter = adapter or UiicAdapter()
        self.heartbeat_interval = heartbeat_interval
        self.lock = threading.RLock()
        self.active = None
        self.recovered_outboxes = []
        self._recover()

    def _log(self, message):
        LOG.info("%s", message)

    def _run_record_path(self, run_id):
        name = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return self.root / "runs" / f"{name}.json"

    def _recover(self):
        for path in (self.root / "runs").glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("abandoned") or (data.get("last_status") in TERMINAL and not data.get("pending")):
                    continue
                outbox = CallbackOutbox.recover(path, self.client, logger=self._log)
                self.recovered_outboxes.append(outbox)
                if outbox.last_status not in TERMINAL:
                    outbox.enqueue("failed", "Windows helper restarted during this run. Portal actions were not repeated; start a fresh run.")
                self._log(f"Recovered callback outbox for run {data['run_id']}")
            except Exception as exc:
                self._log(f"Could not recover local callback record {path.name}: {type(exc).__name__}: {exc}")

    def start(self, request):
        with self.lock:
            existing = self.active
            if existing is not None:
                if existing["request"].run_id == request.run_id and existing["request"].dispatch_id == request.dispatch_id:
                    if existing["context"] is not None:
                        return "accepted"
                    raise BusyError("this run is still redeeming its launch token; retry shortly")
                raise BusyError("another UIIC run is active; wait until it fully stops")
            old_record = self._run_record_path(request.run_id)
            if old_record.exists():
                try:
                    previous = json.loads(old_record.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise BusyError("existing run record is damaged; refusing to replay this run ID") from exc
                if previous.get("dispatch_id") != request.dispatch_id:
                    raise BusyError("run_id was already used for a different dispatch")
                # A browser retry for an already accepted run must never start
                # a second insurer automation, even after a helper restart.
                return "accepted"
            state = {"request": request, "context": None, "outbox": None,
                     "stop": threading.Event(), "engine": None, "thread": None,
                     "heartbeat": None, "review": False, "submitted": False,
                     "last_progress": 0.0, "last_message": "Starting UIIC run",
                     "stale": False}
            self.active = state
        try:
            # Synchronous redemption is deliberately bounded below the browser's
            # eight-second timeout. Invalid/consumed tokens are never retried.
            context = self.client.redeem(request)
            state["context"] = context
            path = self._run_record_path(request.run_id)
            state["outbox"] = CallbackOutbox(path, context, self.client,
                on_stale=lambda: self._stale(state), logger=self._log)
            if state["stop"].is_set():
                # Redemption changes the Base44 run to running. A Stop racing
                # with that request still needs a durable stopped callback.
                self._event(state, "stopped", "Run stopped during launch redemption")
                with self.lock:
                    if self.active is state:
                        self.active = None
                return "accepted"
            thread = threading.Thread(target=self._execute, args=(state,),
                                      name=f"uiic-run-{request.run_id}", daemon=True)
            state["thread"] = thread
            thread.start()
            return "accepted"
        except Exception as exc:
            if state["outbox"] is not None and not state["stop"].is_set():
                self._event(state, "failed", f"Helper could not start the run: {type(exc).__name__}")
            with self.lock:
                if self.active is state:
                    self.active = None
            raise

    def stop(self, run_id, dispatch_id):
        with self.lock:
            state = self.active
            if state is None or state["request"].run_id != run_id or state["request"].dispatch_id != dispatch_id:
                raise BusyError("no matching active run")
            state["stop"].set()
            engine = state["engine"]
        if engine is not None:
            engine.request_stop()
        return "accepted"

    def shutdown(self):
        """Stop the active run cooperatively during helper process shutdown."""
        with self.lock:
            state = self.active
            if state is None:
                return
            state["stop"].set()
            engine = state["engine"]
            thread = state["thread"]
        if engine is not None:
            engine.request_stop()
        if thread is not None:
            thread.join(timeout=15)

    def _stale(self, state):
        state["stale"] = True
        state["stop"].set()
        engine = state["engine"]
        if engine is not None:
            engine.request_stop()

    def _sanitize(self, state, message):
        text = str(message)
        context = state["context"]
        if context:
            for secret in (context.run_token, context.portal_password, state["request"].launch_token):
                if secret:
                    text = text.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(password|token|cookie)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)[:1000]

    def _event(self, state, status, message, confirmation_no=None):
        if state["stale"] or state["outbox"] is None:
            return False
        return state["outbox"].enqueue(status, self._sanitize(state, message), confirmation_no)

    def _progress(self, state, message):
        if state["stop"].is_set() or state["submitted"]:
            return
        safe = self._sanitize(state, message)
        self._log(f"Run {state['request'].run_id}: {safe}")
        state["last_message"] = safe
        now = time.monotonic()
        if now - state["last_progress"] >= 10 and not state["outbox"].has_pending():
            self._event(state, "awaiting_final_submit" if state["review"] else "running", safe)
            state["last_progress"] = now

    def _review(self, state):
        if state["stop"].is_set():
            return
        state["review"] = True
        self._event(state, "awaiting_final_submit", "UIIC forms are ready. Review the visible browser and manually click Final Submit.")

    def _submission(self, state, record):
        if not isinstance(record, dict) or state["stop"].is_set():
            return
        if record.get("automation_dispatch_id") != state["request"].dispatch_id:
            return
        message = self._sanitize(state, record.get("portal_message") or "Insurer response recorded")
        if record.get("confirmed_success"):
            # Never infer completion from successful form filling. This callback
            # comes from the existing manual Final Submit monitor.
            state["submitted"] = True
            if not state["review"]:
                self._review(state)
            self._event(state, "completed", message)
            engine = state["engine"]
            if engine is not None:
                engine.request_stop()
        else:
            self._log(f"Run {state['request'].run_id}: insurer response not confirmed: {message}")

    def _heartbeat_loop(self, state):
        while not state["stop"].wait(self.heartbeat_interval):
            outbox = state["outbox"]
            if state["submitted"] or state["stale"] or outbox.last_status in TERMINAL:
                return
            if not outbox.has_pending():
                status = "awaiting_final_submit" if state["review"] else "running"
                self._event(state, status, state["last_message"])

    def _execute(self, state):
        context = state["context"]
        try:
            self._event(state, "running", "UIIC helper accepted the run; downloading case ZIP")
            heartbeat = threading.Thread(target=self._heartbeat_loop, args=(state,),
                                         name=f"heartbeat-{context.run_id}", daemon=True)
            state["heartbeat"] = heartbeat
            heartbeat.start()
            staged = self.intake.stage(context, state["stop"].is_set)
            if state["stop"].is_set():
                raise InterruptedError("stopped after case download")
            self._progress(state, f"ZIP verified: {staged.file_count} files; preparing UIIC case")
            prepared = self.prepare(staged, state["stop"].is_set)
            staged.claim = prepared.claim
            if state["stop"].is_set():
                raise InterruptedError("stopped during case preparation")
            self._progress(state, "UIIC case prepared; opening visible Chromium")
            result = self.adapter.run(context, staged,
                lambda msg: self._progress(state, msg),
                lambda: self._review(state),
                lambda record: self._submission(state, record),
                lambda engine: state.__setitem__("engine", engine),
                state["stop"].is_set)
            if not state["submitted"] and not state["stop"].is_set():
                if getattr(result, "success", False):
                    raise RuntimeError("Browser closed before a confirmed manual Final Submit")
                raise RuntimeError(getattr(result, "message", "UIIC automation failed"))
            if state["stop"].is_set() and not state["submitted"] and not state["stale"]:
                self._event(state, "stopped", "UIIC browser work stopped before Final Submit")
        except InterruptedError as exc:
            if not state["stale"]:
                self._event(state, "stopped", str(exc))
        except Exception as exc:
            if isinstance(exc, RemoteError) and exc.status == 409:
                self._stale(state)
                self._log(f"Run {context.run_id} stopped because Base44 rejected the dispatch with HTTP 409")
                return
            if not state["stale"]:
                status = "stopped" if state["stop"].is_set() else "failed"
                self._event(state, status, f"{type(exc).__name__}: {exc}")
            self._log(f"Run {context.run_id} ended: {type(exc).__name__}: {self._sanitize(state, exc)}")
        finally:
            state["stop"].set()
            engine = state["engine"]
            if engine is not None:
                engine.request_stop()
            heartbeat = state["heartbeat"]
            if heartbeat is not None:
                heartbeat.join(timeout=2)
            with self.lock:
                if self.active is state:
                    self.active = None
