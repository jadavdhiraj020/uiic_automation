"""Keep each PC's saved config in step with the shipped defaults, and export a PC's config.

Shared business config means three files per portal: ``field_mapping.json``,
``doc_mapping.json`` and ``automation_defaults.json``.

* **New EXE, new defaults:** when a portal's shipped defaults differ from the ones this PC
  last saw, the PC's saved copies of those three files are moved to a backup folder, so the
  new defaults apply. The first launch after this feature exists also counts as "different".
* **Export:** when App3 runs from the project folder, the PC's effective config is written
  into the shipped default files so it can be committed and pushed.

``settings.json`` is never refreshed or exported. It holds the portal username, password and
URL, which belong to one user.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from typing import Any, Iterable, Optional

from app import utils

logger = logging.getLogger(__name__)

STATE_FILE = "config_defaults_state.json"
BACKUP_DIR = "config_backups"
SHARED_KINDS = ("field_mapping", "doc_mapping", "automation_defaults")
# Key names that must never be written into the shipped files.
_PRIVATE_KEYS = {"username", "password", "portal_url"}
_PRIVATE_WORDS = ("password", "secret", "token", "api_key")


def _config_paths(kind: str, portal_id: str) -> dict[str, str]:
    """{"default": bundled path, "user": this PC's saved path} for one config file."""
    if kind == "field_mapping":
        return utils.field_mapping_paths(portal_id=portal_id)
    if kind == "doc_mapping":
        return utils.doc_mapping_paths(portal_id=portal_id)
    if kind == "automation_defaults":
        return utils.automation_defaults_paths(portal_id=portal_id)
    raise ValueError(f"Unknown config kind: {kind!r}")


def defaults_fingerprint(portal_id: str) -> str:
    """Hash of the shipped defaults, independent of spacing and line endings."""
    digest = hashlib.sha256()
    for kind in SHARED_KINDS:
        data = utils.read_json_file(_config_paths(kind, portal_id)["default"]) or {}
        digest.update(kind.encode("utf-8"))
        digest.update(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def _read_state(state_path: str) -> dict[str, Any]:
    state = utils.read_json_file(state_path)
    return state if isinstance(state, dict) else {}


def _backup_saved_copies(portal_id: str, stamp: str, backup_root: Optional[str]) -> list[str]:
    """Move this PC's saved copies out of the way. Returns the files that were moved."""
    root = backup_root or utils.user_data_dir(BACKUP_DIR)
    moved = []
    for kind in SHARED_KINDS:
        saved = _config_paths(kind, portal_id)["user"]
        if not os.path.isfile(saved):
            continue
        target_dir = os.path.join(root, stamp, portal_id)
        os.makedirs(target_dir, exist_ok=True)
        shutil.move(saved, os.path.join(target_dir, os.path.basename(saved)))
        moved.append(saved)
    return moved


def refresh_saved_config(
    portal_ids: Iterable[str],
    state_path: Optional[str] = None,
    backup_root: Optional[str] = None,
) -> list[str]:
    """Apply new shipped defaults. Returns the portals whose saved copies were replaced."""
    state_path = state_path or utils.user_data_dir(STATE_FILE)
    state = _read_state(state_path)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    refreshed: list[str] = []
    changed = False
    for portal_id in portal_ids:
        fingerprint = defaults_fingerprint(portal_id)
        if state.get(portal_id) == fingerprint:
            continue
        moved = _backup_saved_copies(portal_id, stamp, backup_root)
        state[portal_id] = fingerprint
        changed = True
        if moved:
            refreshed.append(portal_id)
            logger.info(
                "New shipped defaults for %s: moved %d saved config file(s) to the backup folder.",
                portal_id, len(moved),
            )
    if changed:
        utils.write_json_file(state_path, state)
    return refreshed


def refresh_saved_config_for_all_portals() -> list[str]:
    """Startup hook: refresh every registered portal (packaged EXE only).

    A run from the project folder is the developer's own PC. Its saved settings are the
    source of Export as Shared Defaults, so they are never moved away automatically.
    """
    if not utils.is_frozen():
        return []
    from app.portals import registry

    return refresh_saved_config(info.portal_id for info in registry.list_portals())


# ── Export ───────────────────────────────────────────────────────────────────

def _has_private_key(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            lowered = str(key).casefold()
            if lowered in _PRIVATE_KEYS or any(word in lowered for word in _PRIVATE_WORDS):
                return str(key)
            found = _has_private_key(inner)
            if found:
                return found
    elif isinstance(value, list):
        for inner in value:
            found = _has_private_key(inner)
            if found:
                return found
    return None


def _dumps(value: Any, inline_lists: bool, level: int = 0) -> str:
    """JSON text close to the hand-edited shipped files (2-space indent, optional inline lists)."""
    pad = "  " * level
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [
            f"{pad}  {json.dumps(str(key), ensure_ascii=False)}: {_dumps(inner, inline_lists, level + 1)}"
            for key, inner in value.items()
        ]
        return "{\n" + ",\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if inline_lists and not any(isinstance(item, (dict, list)) for item in value):
            return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
        rows = [f"{pad}  {_dumps(item, inline_lists, level + 1)}" for item in value]
        return "[\n" + ",\n".join(rows) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def _effective_config(kind: str, portal_id: str) -> dict[str, Any]:
    if kind == "field_mapping":
        return utils.load_field_mapping(portal_id=portal_id)
    if kind == "automation_defaults":
        return utils.load_automation_defaults(portal_id=portal_id)
    paths = _config_paths("doc_mapping", portal_id)
    # Not load_doc_mapping(): that injects the folder currently being scanned.
    return utils._merge_doc_mapping(
        utils.read_json_file(paths["default"]) or {}, utils.read_json_file(paths["user"]) or {}
    )


def export_to_project(portal_id: str, state_path: Optional[str] = None) -> list[str]:
    """Write this PC's effective config into the shipped default files. Returns the paths."""
    if utils.is_frozen():
        raise RuntimeError("Export works only when App3 runs from the project folder.")
    documents = {kind: _effective_config(kind, portal_id) for kind in SHARED_KINDS}
    for kind, document in documents.items():
        private = _has_private_key(document)
        if private:
            raise ValueError(f"{kind} contains '{private}', which must never be shipped. Nothing was written.")

    written = []
    for kind, document in documents.items():
        target = _config_paths(kind, portal_id)["default"]
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_dumps(document, inline_lists=(kind == "field_mapping")) + "\n")
        written.append(target)

    # This PC now matches the shipped defaults, so it must not refresh itself on the next launch.
    state_path = state_path or utils.user_data_dir(STATE_FILE)
    state = _read_state(state_path)
    state[portal_id] = defaults_fingerprint(portal_id)
    utils.write_json_file(state_path, state)
    return written
