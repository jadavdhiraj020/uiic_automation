"""
utils.py — Shared utilities for frozen (PyInstaller) and normal execution.

Primary goals for production reliability:
  - Resolve packaged resources correctly (read-only inside the bundle)
  - Provide a guaranteed writable per-user directory (config/logs/cache)
  - Keep runtime behavior consistent across machines and install locations
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

APP_SLUG = "UIIC_Surveyor_Automation"


def _get_portal_registry():
    """Lazy import to avoid circular dependency (registry imports utils)."""
    try:
        from app.portals import registry
        return registry
    except ImportError:
        return None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_base_dir() -> str:
    """
    Return the bundle root used for reading packaged resources.

    - Frozen exe: sys._MEIPASS (PyInstaller extraction dir; read-only semantics)
    - Source run: project root (directory containing `main.py`)
    """
    if is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_exe_dir() -> str:
    """Directory containing the executable (or project root in source mode)."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return get_base_dir()


def resource_path(*parts: str) -> str:
    """Absolute path to a packaged (read-only) resource."""
    return os.path.join(get_base_dir(), *parts)


def user_data_dir(*parts: str) -> str:
    """
    Guaranteed writable per-user directory.

    Frozen exe should never write into sys._MEIPASS.
    We default to LOCALAPPDATA\\<APP_SLUG> (portable, no admin needed).
    """
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or str(Path.home())
    )
    return os.path.join(base, APP_SLUG, *parts)


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def settings_paths(portal_id: Optional[str] = None) -> dict[str, str]:
    """
    Canonical settings locations.

    - `default`: bundled default settings shipped with the app
    - `user`: writable user-specific settings (preferred at runtime)

    Portal-aware: when a portal is active via the registry, paths resolve
    to the portal-specific config directory automatically.
    """
    reg = _get_portal_registry()
    if reg is not None:
        try:
            return reg.portal_settings_paths(portal_id=portal_id)
        except Exception:
            pass
    return {
        "default": resource_path("app", "config", "settings.json"),
        "user": os.path.join(user_data_dir("config"), "settings.json"),
    }


def read_json_file(path: str) -> Optional[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            import json

            return json.load(f)
    except Exception:
        return None


def write_json_file(path: str, data: dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path))
    import json

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_settings(portal_id: Optional[str] = None) -> dict[str, Any]:
    """
    Load settings with a stable precedence:
      user settings override bundled defaults.
    """
    paths = settings_paths(portal_id=portal_id)
    base = read_json_file(paths["default"]) or {}
    override = read_json_file(paths["user"]) or {}
    base.update(override)
    return base


def save_settings(overrides: dict[str, Any], portal_id: Optional[str] = None) -> str:
    """Merge and save settings into the writable user settings file."""
    paths = settings_paths(portal_id=portal_id)
    current = load_settings(portal_id=portal_id)
    current.update(overrides or {})
    write_json_file(paths["user"], current)
    return paths["user"]


# ── Field Mapping persistence ─────────────────────────────────────────────

def field_mapping_paths(portal_id: Optional[str] = None) -> dict[str, str]:
    """
    Canonical field-mapping file locations.

    - `default`: bundled read-only mapping shipped with the app
    - `user`: writable user-specific mapping in AppData

    Portal-aware: routes to portal-specific config when active.
    """
    reg = _get_portal_registry()
    if reg is not None:
        try:
            return reg.portal_field_mapping_paths(portal_id=portal_id)
        except Exception:
            pass
    return {
        "default": resource_path("app", "config", "field_mapping.json"),
        "user": os.path.join(user_data_dir("config"), "field_mapping.json"),
    }


def load_field_mapping(portal_id: Optional[str] = None) -> dict[str, Any]:
    """
    Load the field mapping with user overrides.

    Bundled defaults are the base document. Per-field deep merge ensures:
      - User label/offset overrides are respected
      - New bundled keys (e.g. allow_text_values) carry through even if
        the user's saved copy predates them
    """
    paths = field_mapping_paths(portal_id=portal_id)
    base = read_json_file(paths["default"]) or {}
    user = read_json_file(paths["user"]) or {}
    merged = {}
    
    # Maintain the precise order from the base config file and only keep keys present in base
    all_keys = list(base.keys())
            
    for key in all_keys:
        b = base.get(key)
        u = user.get(key)
        if isinstance(b, dict) and isinstance(u, dict):
            # Per-field deep merge: bundled defaults + user overrides
            field = dict(b)
            field.update(u)
            merged[key] = field
        elif u is not None:
            merged[key] = u
        else:
            merged[key] = b
    return merged


def save_field_mapping(mapping: dict[str, Any], portal_id: Optional[str] = None) -> str:
    """Save a complete field mapping document to the writable user location."""
    paths = field_mapping_paths(portal_id=portal_id)
    write_json_file(paths["user"], mapping)
    return paths["user"]


def reset_field_mapping(portal_id: Optional[str] = None) -> None:
    """Delete user field mapping so the bundled default is used again."""
    paths = field_mapping_paths(portal_id=portal_id)
    try:
        if os.path.exists(paths["user"]):
            os.remove(paths["user"])
    except OSError:
        pass


# ── Document Mapping persistence ──────────────────────────────────────────

def doc_mapping_paths(portal_id: Optional[str] = None) -> dict[str, str]:
    """
    Canonical doc-mapping file locations.

    - `default`: bundled read-only mapping shipped with the app
    - `user`: writable user-specific mapping in AppData

    Portal-aware: routes to portal-specific config when active.
    """
    reg = _get_portal_registry()
    if reg is not None:
        try:
            return reg.portal_doc_mapping_paths(portal_id=portal_id)
        except Exception:
            pass
    return {
        "default": resource_path("app", "config", "doc_mapping.json"),
        "user": os.path.join(user_data_dir("config"), "doc_mapping.json"),
    }


def _merge_doc_mapping(base: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """Merge portal doc mappings while preserving new bundled sections."""
    merged = dict(base or {})
    for key, value in (user or {}).items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            section = dict(base_value)
            for k, val in value.items():
                if k in base_value:
                    section[k] = val
            merged[key] = section
        elif key in merged:
            if isinstance(base_value, list) and isinstance(value, list):
                merged[key] = [v for v in value if v in base_value]
            else:
                merged[key] = value
    return merged


def load_doc_mapping(portal_id: Optional[str] = None) -> dict[str, Any]:
    """
    Load doc mapping with user overrides layered over bundled defaults.

    This preserves newly bundled top-level sections such as
    ``document_upload_tab`` when an older user override file exists.
    """
    paths = doc_mapping_paths(portal_id=portal_id)
    base = read_json_file(paths["default"]) or {}
    user = read_json_file(paths["user"]) or {}
    return _merge_doc_mapping(base, user)


def save_doc_mapping(mapping: dict[str, Any], portal_id: Optional[str] = None) -> str:
    """Save a complete doc mapping document to the writable user location."""
    paths = doc_mapping_paths(portal_id=portal_id)
    write_json_file(paths["user"], mapping)
    return paths["user"]


def reset_doc_mapping(portal_id: Optional[str] = None) -> None:
    """Delete user doc mapping so the bundled default is used again."""
    paths = doc_mapping_paths(portal_id=portal_id)
    try:
        if os.path.exists(paths["user"]):
            os.remove(paths["user"])
    except OSError:
        pass


# Automation Defaults persistence

def automation_defaults_paths(portal_id: Optional[str] = None) -> dict[str, str]:
    """
    Canonical automation-default file locations.

    These are user-facing business defaults such as remarks text, HSN code,
    payment method, and common Yes/No values. Technical selectors, waits, and
    retry behavior intentionally stay out of this config.
    """
    reg = _get_portal_registry()
    if reg is not None:
        try:
            return reg.portal_automation_defaults_paths(portal_id=portal_id)
        except Exception:
            pass
    return {
        "default": resource_path("app", "config", "automation_defaults.json"),
        "user": os.path.join(user_data_dir("config"), "automation_defaults.json"),
    }


def load_automation_defaults(portal_id: Optional[str] = None) -> dict[str, Any]:
    """Load automation defaults with user values layered over bundled defaults."""
    paths = automation_defaults_paths(portal_id=portal_id)
    base = read_json_file(paths["default"]) or {}
    user = read_json_file(paths["user"]) or {}
    merged = dict(base)
    for key, value in user.items():
        if key in merged or not str(key).startswith("_"):
            merged[key] = value
    return merged


def save_automation_defaults(defaults: dict[str, Any], portal_id: Optional[str] = None) -> str:
    """Save automation defaults into the writable user config file."""
    paths = automation_defaults_paths(portal_id=portal_id)
    current = load_automation_defaults(portal_id=portal_id)
    current.update(defaults or {})
    write_json_file(paths["user"], current)
    return paths["user"]


def reset_automation_defaults(portal_id: Optional[str] = None) -> None:
    """Delete user automation defaults so bundled defaults are used again."""
    paths = automation_defaults_paths(portal_id=portal_id)
    try:
        if os.path.exists(paths["user"]):
            os.remove(paths["user"])
    except OSError:
        pass
