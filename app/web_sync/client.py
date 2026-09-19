"""The deployed Base44 contract. No portal secrets enter this client."""
from contextlib import contextmanager
import re
import threading

import requests

APP_ID = "6a906023a09ef23a2e1dfcaf"
BASE_URL = f"https://base44.app/api/apps/{APP_ID}"
_INDIVIDUAL_DOWNLOAD_SLOTS = threading.BoundedSemaphore(3)
_QUEUE_PAGE_LIMIT = 25


class ApiError(RuntimeError):
    def __init__(self, status, operation, code="", detail=""):
        self.status = status
        self.operation = operation
        self.code = str(code or "")
        self.detail = str(detail or "")
        suffix = f" ({self.code})" if self.code else ""
        safe_detail = re.sub(r"\s+", " ", self.detail).strip()[:500]
        detail_suffix = f": {safe_detail}" if safe_detail else ""
        super().__init__(f"{operation}: HTTP {status}{suffix}{detail_suffix}")


class ClientClosedError(RuntimeError):
    """Raised when App-3 shutdown cancels an outstanding Web Sync operation."""


class DownloadLimitError(ValueError):
    """A streamed response exceeded the caller's explicit safety limit."""


class Client:
    def __init__(self, email, password, session=None):
        self.email, self.password = email, password
        self.token = None
        self.session = session
        self._sessions = threading.local()
        self._session_registry = set()
        self._sessions_lock = threading.RLock()
        self._closed = threading.Event()
        self.lock = threading.RLock()
        self.queue_warning = ""
        self.auto_pickup_blocker = ""

    def _session(self):
        if self._closed.is_set():
            raise ClientClosedError("Web Sync request cancelled because App-3 is closing")
        if self.session is not None:
            return self.session
        if not getattr(self._sessions, "value", None):
            new_session = requests.Session()
            with self._sessions_lock:
                if self._closed.is_set():
                    new_session.close()
                    raise ClientClosedError("Web Sync request cancelled because App-3 is closing")
                self._sessions.value = new_session
                self._session_registry.add(new_session)
        return self._sessions.value

    def wait_before_retry(self, seconds):
        """Wait for a retry while allowing shutdown to wake the worker immediately."""
        if self._closed.wait(max(0, float(seconds))):
            raise ClientClosedError("Web Sync retry cancelled because App-3 is closing")

    @contextmanager
    def individual_download_slot(self):
        """Share three individual-file transfer slots across every staged case."""
        acquired = False
        try:
            while not acquired:
                if self._closed.is_set():
                    raise ClientClosedError("Web Sync download cancelled because App-3 is closing")
                acquired = _INDIVIDUAL_DOWNLOAD_SLOTS.acquire(timeout=0.2)
            yield
        finally:
            if acquired:
                _INDIVIDUAL_DOWNLOAD_SLOTS.release()

    def close(self):
        """Signal cancellation and close all known per-thread HTTP sessions."""
        self._closed.set()
        with self._sessions_lock:
            sessions = list(self._session_registry)
            if self.session is not None:
                sessions.append(self.session)
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass

    def _login_locked(self):
        with self._session().post(
                BASE_URL + "/auth/login",
                headers={"X-App-Id": APP_ID, "Content-Type": "application/json", "Accept": "application/json"},
                json={"email": self.email, "password": self.password},
                timeout=(15, 60), allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                self.token = None
                raise ApiError(response.status_code, "Login")
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("Login returned no access_token")
            self.token = token

    def login(self):
        with self.lock:
            self._login_locked()

    def call(self, function, body, destination=None, max_bytes=None):
        if self._closed.is_set():
            raise ClientClosedError("Web Sync request cancelled because App-3 is closing")
        with self.lock:
            if not self.token:
                self._login_locked()
            token = self.token
        for attempt in range(2):
            if self._closed.is_set():
                raise ClientClosedError("Web Sync request cancelled because App-3 is closing")
            with self._session().post(
                    BASE_URL + "/functions/" + function,
                    headers={"Authorization": f"Bearer {token}", "X-App-Id": APP_ID,
                             "Content-Type": "application/json", "Accept": "application/json"},
                    json=body, timeout=(15, 120), stream=destination is not None,
                    allow_redirects=False,
            ) as response:
                if response.status_code == 401 and attempt == 0:
                    response.close()
                    with self.lock:
                        if self.token == token:
                            self._login_locked()
                        token = self.token
                    continue
                if response.status_code != 200:
                    code = detail = ""
                    try:
                        error_data = response.json()
                        if isinstance(error_data, dict):
                            error_value = error_data.get("error")
                            code = error_data.get("code") or error_data.get("error_code") or ""
                            if isinstance(error_value, dict):
                                code = code or error_value.get("code") or ""
                                detail = error_value.get("message") or ""
                            elif isinstance(error_value, str):
                                detail = error_value
                                if error_value.strip().lower() == "stale_dispatch":
                                    code = "stale_dispatch"
                            code = code or error_data.get("reason") or ""
                            detail = detail or error_data.get("message") or ""
                    except (TypeError, ValueError, AttributeError):
                        pass
                    raise ApiError(response.status_code, function, code, detail)
                if destination is None:
                    data = response.json()
                    if not isinstance(data, dict) or data.get("error"):
                        raise ValueError(f"{function}: invalid response")
                    return data
                kind = response.headers.get("Content-Type", "").lower()
                if "json" in kind or "text/html" in kind:
                    raise ValueError("Download returned an error document instead of a binary file")
                limit = 512 * 1024 * 1024 if max_bytes is None else int(max_bytes)
                if limit <= 0:
                    raise ValueError("Download limit must be positive")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except (TypeError, ValueError):
                        declared_length = None
                    if declared_length is not None and declared_length > limit:
                        raise DownloadLimitError(f"Download exceeds the {limit:,}-byte safety limit")
                total = 0
                with open(destination, "wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if self._closed.is_set():
                            raise ClientClosedError("Web Sync download cancelled because App-3 is closing")
                        total += len(chunk)
                        if total > limit:
                            raise DownloadLimitError(f"Download exceeds the {limit:,}-byte safety limit")
                        output.write(chunk)
                if not total:
                    raise ValueError("Downloaded file is empty")
                return dict(response.headers)

    def jobs(self):
        jobs = self.call("getAutomationJobs", {"limit": _QUEUE_PAGE_LIMIT}).get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("getAutomationJobs returned no jobs list")
        pagination_warning = (
            "Base44 returned the full 25-item contract limit without pagination metadata; "
            "additional queued cases may not be available to App-3."
            if len(jobs) >= _QUEUE_PAGE_LIMIT else ""
        )

        visible = []
        unidentifiable = 0
        needs_attention = 0
        skipped = 0
        required = ("case_id", "case_ref", "insurer", "surveyor_profile_id", "automation_dispatch_id")
        for raw_job in jobs:
            if not isinstance(raw_job, dict) or raw_job.get("status") != "queued_for_automation":
                skipped += 1
                continue
            if not isinstance(raw_job.get("case_id"), str) or not raw_job["case_id"].strip():
                unidentifiable += 1
                skipped += 1
                continue
            job = dict(raw_job)
            errors = [key for key in required if not isinstance(job.get(key), str) or not job[key].strip()]
            if errors:
                job["_queue_validation_errors"] = errors
                needs_attention += 1
            visible.append(job)

        warnings = []
        if skipped:
            warnings.append(f"Skipped {skipped} invalid or unidentifiable queue item(s).")
        if needs_attention:
            warnings.append(f"{needs_attention} queued case(s) need missing Base44 fields corrected; they remain visible.")
        if pagination_warning:
            warnings.append(pagination_warning)
        self.queue_warning = " ".join(warnings)
        self.auto_pickup_blocker = ""
        if visible and visible[0].get("_queue_validation_errors"):
            self.auto_pickup_blocker = "Oldest queue item has missing case data. Correct it in Base44 before automatic staging can continue."
        return visible

    def claim(self, case_id, automation_dispatch_id):
        if not isinstance(automation_dispatch_id, str) or not automation_dispatch_id.strip():
            raise ValueError("Claim requires automation_dispatch_id")
        data = self.call("claimAutomationCase", {
            "case_id": case_id,
            "automation_dispatch_id": automation_dispatch_id,
        })
        job = data.get("job")
        if (
            data.get("claimed") is not True or not isinstance(job, dict)
            or job.get("case_id") != case_id
            or job.get("automation_dispatch_id") != automation_dispatch_id
            or job.get("status") != "automation_in_progress"
        ):
            raise ValueError("Claim was not confirmed")
        job = dict(job)
        job.setdefault("automation_dispatch_id", automation_dispatch_id)
        return job

    def report(self, payload):
        if payload.get("status") not in ("success", "failed"):
            raise ValueError("Invalid result status")
        if not isinstance(payload.get("automation_dispatch_id"), str) or not payload["automation_dispatch_id"].strip():
            raise ValueError("Result report requires automation_dispatch_id")
        data = self.call("reportAutomationResult", payload)
        expected = "uploaded" if payload["status"] == "success" else "ready_for_upload"
        if data.get("ok") is not True or data.get("case_id") != payload["case_id"] or data.get("status") != expected:
            raise ValueError("Result acknowledgement did not match this case")
        return data
