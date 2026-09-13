"""Windows-user-bound encryption and atomic local state."""
import json
import os
from pathlib import Path
import re
import threading
import hashlib
from datetime import datetime, timezone


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


class CredentialStore:
    """Only encrypted bytes persist; DPAPI uses the current Windows user."""
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        import win32crypt
        if not self.path.exists():
            return {}
        return json.loads(win32crypt.CryptUnprotectData(self.path.read_bytes(), None, None, None, 0)[1])

    def get(self, profile_id, portal):
        value = self._read().get(profile_id, {}).get(portal)
        if not value or not value.get("username") or not value.get("password"):
            raise ValueError(f"Save local credentials for {profile_id} / {portal} first")
        return dict(value)

    def save(self, profile_id, portal, username, password, surveyor_code):
        import win32crypt
        if not profile_id.strip() or portal not in ("uiic", "newindia", "oic") or not username.strip() or not password:
            raise ValueError("Profile ID, insurer, username and password are required")
        data = self._read()
        data.setdefault(profile_id.strip(), {})[portal] = {
            "username": username.strip(), "password": password, "surveyor_code": surveyor_code.strip(),
        }
        encrypted = win32crypt.CryptProtectData(json.dumps(data).encode(), "App-3 surveyor credentials", None, None, None, 0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_bytes(encrypted)
        os.replace(temp, self.path)


class OperatorCredentialStore(CredentialStore):
    """Separate DPAPI file for DocWriter login; access tokens are never persisted."""

    def get(self):
        if not self.path.exists():
            return None
        data = self._read()
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k] for k in ("email", "password")):
            raise ValueError("Invalid saved DocWriter login")
        return data

    def save(self, email, password):
        import win32crypt
        if not email.strip() or not password:
            raise ValueError("Operator email and password are required")
        encrypted = win32crypt.CryptProtectData(
            json.dumps({"email": email.strip(), "password": password}).encode(),
            "App-3 DocWriter operator login", None, None, None, 0,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with temp.open("wb") as output:
            output.write(encrypted)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, self.path)

    def forget(self):
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(".tmp").unlink(missing_ok=True)


class AutoPickupPreference:
    """Small non-secret preference; missing or damaged files safely mean OFF."""

    def __init__(self, path):
        self.path = Path(path)

    def get(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data.get("auto_pickup") is True if isinstance(data, dict) else False
        except (OSError, ValueError, TypeError):
            return False

    def set(self, enabled):
        atomic_json(self.path, {"auto_pickup": bool(enabled)})


class CompletedCaseStore:
    """Non-secret local history used only to organize downloaded web cases."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def all(self):
        with self.lock:
            if not self.path.exists():
                return []
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise ValueError("Invalid completed-cases history")
            return [dict(item) for item in data]

    def upsert(self, entry):
        case_id = entry.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("Completed case is missing case_id")
        with self.lock:
            entries = self.all()
            existing = next((item for item in entries if item.get("case_id") == case_id), {})
            merged = {**existing, **entry}
            entries = [item for item in entries if item.get("case_id") != case_id]
            entries.insert(0, merged)
            atomic_json(self.path, entries)
            return dict(merged)

    def remove(self, case_id):
        with self.lock:
            entries = self.all()
            kept = [item for item in entries if item.get("case_id") != case_id]
            if len(kept) != len(entries):
                atomic_json(self.path, kept)


class CaseState:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.recovery_marker = self.path.with_suffix(self.path.suffix + ".recovery")
        self.recovery_error = ""
        self.current = None
        if self.recovery_marker.exists():
            try:
                self.recovery_error = str(json.loads(self.recovery_marker.read_text(encoding="utf-8")).get("error") or "")
            except (OSError, ValueError, AttributeError):
                self.recovery_error = "The active-case journal was quarantined after an earlier read failure"
        if self.path.exists():
            try:
                self.current = json.loads(self.path.read_text(encoding="utf-8"))
                if self.current is not None:
                    if not isinstance(self.current, dict) or not all(key in self.current for key in ("job", "phase", "folder", "portal")):
                        raise ValueError("Invalid current-case journal")
                    job = self.current["job"]
                    if not isinstance(job, dict) or not all(job.get(key) for key in ("case_id", "case_ref", "surveyor_profile_id", "insurer")):
                        raise ValueError("Invalid current-case job")
            except (ValueError, TypeError) as exc:
                quarantine_dir = self.path.parent / "quarantine"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                quarantined = quarantine_dir / f"{self.path.stem}.{stamp}.corrupt"
                os.replace(self.path, quarantined)
                self.current = None
                self.recovery_error = f"Damaged active-case journal was quarantined: {exc}"
                atomic_json(self.recovery_marker, {
                    "error": self.recovery_error,
                    "quarantined_file": str(quarantined),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    def set(self, value):
        with self.lock:
            atomic_json(self.path, value)
            self.current = value
            self.recovery_error = ""
            self.recovery_marker.unlink(missing_ok=True)

    def update(self, **changes):
        with self.lock:
            self.set({**self.current, **changes})


def case_key(case_id):
    return hashlib.sha256(str(case_id).encode("utf-8")).hexdigest()[:24]


def readable_case_folder(job):
    """Stable Windows-safe folder name with a case-id suffix for uniqueness."""
    parts = [job.get("case_ref", "case"), job.get("vehicle_no", "vehicle")]
    readable = "__".join(
        re.sub(r"[^A-Za-z0-9._-]+", "_", str(part)).strip(" ._") or "unknown"
        for part in parts
    )
    return f"{readable[:105]}__{case_key(job.get('case_id', ''))[:6]}"


class CaseRepository:
    """Atomic per-case state records that survive independent folder deletion."""

    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.recovery_dir = self.state_dir / "quarantine"
        self.lock = threading.RLock()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _recovery_path(self, case_id):
        return self.recovery_dir / f"{case_key(case_id)}.recovery.json"

    def _quarantine(self, path, error):
        """Move one unreadable record aside without affecting healthy cases."""
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        quarantined = self.recovery_dir / f"{path.stem}.{stamp}.corrupt"
        os.replace(path, quarantined)
        marker = self.recovery_dir / f"{path.stem}.recovery.json"
        atomic_json(marker, {
            "error": f"Damaged local case state was quarantined: {error}",
            "quarantined_file": str(quarantined),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _recovery_record(self, case_id):
        marker = self._recovery_path(case_id)
        if not marker.exists():
            return None
        try:
            details = json.loads(marker.read_text(encoding="utf-8"))
            message = str(details.get("error") or "Damaged local case state was quarantined")
        except (OSError, ValueError, AttributeError):
            message = "Damaged local case state was quarantined"
        return {
            "case_id": case_id,
            "job": {"case_id": case_id},
            "local_status": "needs attention",
            "phase": "needs attention",
            "state_recovery_error": message,
            "last_error": message,
        }

    def _path(self, case_id):
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("Case state is missing case_id")
        return self.state_dir / f"{case_key(case_id)}.json"

    @staticmethod
    def _validate(value):
        if not isinstance(value, dict) or not isinstance(value.get("case_id"), str):
            raise ValueError("Invalid per-case state")
        job = value.get("job")
        if not isinstance(job, dict) or job.get("case_id") != value["case_id"]:
            raise ValueError("Per-case job identity mismatch")
        return value

    def get(self, case_id):
        with self.lock:
            path = self._path(case_id)
            if not path.exists():
                return self._recovery_record(case_id)
            try:
                return dict(self._validate(json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, TypeError) as exc:
                self._quarantine(path, exc)
                return self._recovery_record(case_id)

    def all(self):
        with self.lock:
            records = []
            for path in sorted(self.state_dir.glob("*.json")):
                try:
                    records.append(dict(self._validate(json.loads(path.read_text(encoding="utf-8")))))
                except (ValueError, TypeError) as exc:
                    self._quarantine(path, exc)
            return records

    def set(self, value):
        value = dict(self._validate(value))
        with self.lock:
            atomic_json(self._path(value["case_id"]), value)
            self._recovery_path(value["case_id"]).unlink(missing_ok=True)
            return dict(value)

    def upsert(self, case_id, **changes):
        with self.lock:
            current = self.get(case_id) or {"case_id": case_id, "job": {"case_id": case_id}}
            if "job" in changes:
                changes["job"] = {**current.get("job", {}), **changes["job"]}
            return self.set({**current, **changes})

    def remove(self, case_id):
        with self.lock:
            self._path(case_id).unlink(missing_ok=True)
            self._recovery_path(case_id).unlink(missing_ok=True)


def portal_for(insurer):
    names = {
        "uiic": "uiic", "nia": "newindia", "oic": "oic",
        "newindia": "newindia",
        "united india insurance company limited": "uiic",
        "the new india assurance company limited": "newindia",
        "new india assurance company limited": "newindia",
        "oriental insurance company limited": "oic",
        "united india": "uiic", "united india insurance": "uiic",
        "new india": "newindia", "new india assurance": "newindia", "new india insurance": "newindia",
        "oriental": "oic", "oriental insurance": "oic",
    }
    try:
        return names[" ".join(insurer.lower().split())]
    except (KeyError, AttributeError):
        raise ValueError(f"Unsupported insurer: {insurer}") from None
