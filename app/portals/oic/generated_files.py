"""Safely replace files created by the OIC automation, never unrelated files."""

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from app.utils import ensure_dir, user_data_dir

_publish_lock = threading.Lock()


def _digest(path):
    checksum = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _owner_path(target, portal_id="oic"):
    normalized = os.path.normcase(os.path.abspath(target))
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return os.path.join(user_data_dir("portals", portal_id, "generated_file_owners"), key + ".json")


def _matches_owner(target, owner_path):
    try:
        with open(owner_path, encoding="utf-8") as stream:
            owner = json.load(stream)
        return (isinstance(owner, dict) and not os.path.islink(target) and os.path.isfile(target)
                and owner.get("sha256") == _digest(target))
    except (OSError, ValueError, TypeError):
        return False


def has_generated_owner(target, *, portal_id="oic"):
    return _matches_owner(target, _owner_path(target, portal_id))


def publish_generated(staged_path, target, *, portal_id="oic", allow_legacy=False, stop_cb=None):
    """Publish a completed file over a tracked output or an identified legacy output."""
    target = os.path.abspath(target)
    owner_path = _owner_path(target, portal_id)
    if not os.path.isfile(staged_path) or os.path.getsize(staged_path) == 0:
        raise ValueError("Generated file is empty or missing")
    with _publish_lock:
        if os.path.lexists(target):
            owned = _matches_owner(target, owner_path)
            legacy = (allow_legacy and not os.path.lexists(owner_path)
                      and not os.path.islink(target) and os.path.isfile(target))
            if not owned and not legacy:
                raise FileExistsError(
                    f"Cannot replace '{Path(target).name}': it is not a verified, unchanged app-generated file. "
                    "Move or rename it and rescan."
                )
        digest = _digest(staged_path)
        ensure_dir(os.path.dirname(owner_path))
        fd, pending = tempfile.mkstemp(prefix="oic-owner-", suffix=".tmp", dir=os.path.dirname(owner_path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"sha256": digest}, stream)
            if stop_cb and stop_cb():
                return None
            os.replace(staged_path, target)
            os.replace(pending, owner_path)
        finally:
            if os.path.exists(pending):
                os.unlink(pending)
    return target
